"""A line break in user text does not reach an email header.

The public contact form puts the visitor's own words into two headers:
``Reply-To: {name} <{email}>`` and ``Subject: [JAOT Contact] {subject}``. The
schema bounds their length and validates the address, and the schema's own note
called header injection handled on that basis — but `EmailStr` only covers the
address half of Reply-To. The display name beside it, and the subject, had no
constraint at all.

Python 3.12 refuses to serialise a header holding an embedded newline, so
nothing was ever injected. What happened instead is that `HeaderParseError`
escaped `SMTPBackend.send`, which is documented as returning a bool, and then
escaped `send_contact_email`, whose `except` names SMTP errors and nothing
else. Celery marked the task failed with no retry, the row kept `status =
"queued"`, `last_error` stayed empty and no admin alert went out. The message
was dropped and nobody was told.

Sanitising where the header is built covers every caller and every field at
once, which is why the fix is not in the contact task.
"""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from app.services.email_service import SMTPBackend

pytestmark = pytest.mark.contract

INJECTION = "Mallory\r\nBcc: victim@example.com"


def _backend() -> SMTPBackend:
    return SMTPBackend(host="smtp.example.com", port=587, username="u", password="p")


def _sent_message(**send_kwargs: object) -> tuple[bool, str]:
    """Send through a stubbed SMTP server and return (result, the wire bytes)."""
    result, _envelope, wire = _sent_call(**send_kwargs)
    return result, wire


def _sent_call(**send_kwargs: object) -> tuple[bool, tuple[str, list[str]], str]:
    """(result, (MAIL FROM, RCPT TO), the message bytes).

    The envelope is returned separately because it is a different attack
    surface from the headers: ``sendmail(sender, recipients, msg)`` writes its
    first two arguments straight into the MAIL FROM and RCPT TO commands, so a
    line break there opens a second SMTP command rather than a second header.
    Reading only ``args[2]`` cannot see that, and cannot tell a fix that cleans
    the envelope from one that only cleans the headers.
    """
    backend = _backend()
    with patch("smtplib.SMTP") as smtp_cls:
        server = MagicMock()
        smtp_cls.return_value = server
        result = backend.send(**send_kwargs)  # type: ignore[arg-type]
        if not server.sendmail.called:
            return result, ("", []), ""
        args = server.sendmail.call_args.args
        return result, (args[0], list(args[1])), args[2]


# CONTRACT-TEST: a header built from user text never carries a line break.
#
# Every field, not only the two the contact form fills: the rule belongs to the
# header, so the next caller that puts user text in one is covered too.
@pytest.mark.parametrize("field", ["subject", "reply_to", "to", "from_email"])
def test_a_line_break_in_any_header_field_is_flattened(field: str) -> None:
    kwargs: dict[str, object] = {
        "to": "reader@example.com",
        "subject": "A subject",
        "html": "<p>Body</p>",
        "reply_to": "Someone <someone@example.com>",
        "from_email": "noreply@jaot.io",
    }
    kwargs[field] = "Mallory\r\nX-Evil: 1 <mallory@example.com>"

    sent, wire = _sent_message(**kwargs)

    assert sent is True, "a line break made the send fail instead of being cleaned"
    assert "\nX-Evil:" not in wire, "a second header was injected"


# CONTRACT-TEST: the send still answers with a bool, never an exception.
#
# `send_contact_email` catches SMTP errors and nothing else, so anything else
# escaping here loses the message with no retry and no alert.
def test_the_send_returns_a_bool_and_never_raises() -> None:
    sent, _ = _sent_message(
        to="reader@example.com",
        subject=INJECTION,
        html="<p>Body</p>",
        reply_to=INJECTION + " <mallory@example.com>",
    )
    assert sent is True


# CONTRACT-TEST: the text itself is kept, only the break goes.
def test_the_words_survive_the_cleaning() -> None:
    _, wire = _sent_message(
        to="reader@example.com",
        subject="Question about pricing",
        html="<p>Body</p>",
        reply_to=f"{INJECTION} <mallory@example.com>",
    )
    assert "Question about pricing" in wire
    assert "Mallory" in wire, "the display name was thrown away instead of cleaned"
    assert "mallory@example.com" in wire


# An ordinary send is untouched by any of this.
def test_a_normal_send_is_unchanged() -> None:
    sent, wire = _sent_message(
        to="reader@example.com",
        subject="Welcome to JAOT",
        html="<p>Body</p>",
        reply_to="JAOT Support <support@jaot.io>",
    )
    assert sent is True
    assert "Subject: Welcome to JAOT" in wire
    assert "Reply-To: JAOT Support <support@jaot.io>" in wire


def test_an_smtp_failure_still_reports_false() -> None:
    """The cleaning must not swallow the failures the callers rely on."""
    backend = _backend()
    with patch("smtplib.SMTP") as smtp_cls:
        server = MagicMock()
        smtp_cls.return_value = server
        server.sendmail.side_effect = smtplib.SMTPException("Relay denied")
        assert (
            backend.send(to="a@b.c", subject=INJECTION, html="<p>x</p>", reply_to=INJECTION)
            is False
        )


# CONTRACT-TEST: the SMTP envelope is cleaned too, not only the headers.
#
# `sendmail` writes its sender and recipient arguments into the MAIL FROM and
# RCPT TO commands. A line break there is an injected SMTP command, which is a
# worse outcome than an injected header — and it is invisible to any assertion
# that reads only the serialised message.
@pytest.mark.parametrize("field", ["to", "from_email"])
def test_the_envelope_carries_no_line_break(field: str) -> None:
    kwargs: dict[str, object] = {
        "to": "reader@example.com",
        "subject": "A subject",
        "html": "<p>Body</p>",
        "reply_to": "Someone <someone@example.com>",
        "from_email": "noreply@jaot.io",
    }
    kwargs[field] = "reader@example.com\r\nRCPT TO: victim@example.com"

    sent, (mail_from, rcpt_to), _wire = _sent_call(**kwargs)

    assert sent is True
    for part in [mail_from, *rcpt_to]:
        assert part.splitlines() == [part], f"a line break reached the SMTP envelope: {part!r}"


# CONTRACT-TEST: every character `str.splitlines` treats as a break is removed.
#
# The first fix matched `[\r\n]` only. `email.header` splits on
# `str.splitlines()`, which breaks on several more control characters, so a form
# feed pasted into a name still raised HeaderParseError and still lost the
# message.
@pytest.mark.parametrize(
    "ch",
    ["\r", "\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " "],
    ids=["CR", "LF", "VT", "FF", "FS", "GS", "RS", "NEL", "LS", "PS"],
)
def test_every_character_python_calls_a_line_break_is_removed(ch: str) -> None:
    sent, wire = _sent_message(
        to="reader@example.com",
        subject=f"Ann{ch}Bcc: victim@example.com",
        html="<p>Body</p>",
        reply_to="Someone <someone@example.com>",
    )

    assert sent is True, f"{ch!r} in a subject made the send fail instead of being cleaned"
    assert "\nBcc:" not in wire, f"{ch!r} let a second header through"
