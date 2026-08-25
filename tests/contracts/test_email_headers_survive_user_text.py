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
    backend = _backend()
    with patch("smtplib.SMTP") as smtp_cls:
        server = MagicMock()
        smtp_cls.return_value = server
        result = backend.send(**send_kwargs)  # type: ignore[arg-type]
        if not server.sendmail.called:
            return result, ""
        return result, server.sendmail.call_args.args[2]


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
