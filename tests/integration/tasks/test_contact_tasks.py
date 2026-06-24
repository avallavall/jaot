"""RED integration tests for send_contact_email Celery task — Phase 9 Wave 0.

These tests are intentionally failing today. Wave 1 lands:
  - app/tasks/contact_tasks.py::send_contact_email (bind=True, max_retries=5)
  - PSS read of CONTACT_RECIPIENT at task time (NOT at enqueue)
  - SMTPException retry path with exponential backoff
  - Terminal-failure status flip + one-off admin notification

Expected RED failure mode: ModuleNotFoundError on
`from app.tasks.contact_tasks import send_contact_email`.

Covers Phase 9 decisions D-04 (autoretry), D-07 (PSS recipient), D-09 (reply-to format).
Mitigates threat T-09-10 (Celery PII leak — only message_id traverses the broker).
"""

from __future__ import annotations

import smtplib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.models.contact_message import ContactMessage
from app.services.email_service import EmailService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.tasks.contact_tasks import send_contact_email


def _seed_message(db_session, **overrides: Any) -> ContactMessage:
    """Insert a baseline ContactMessage row and return it."""
    msg = ContactMessage(
        id=generate_id("ctc_"),
        created_at=utcnow().replace(tzinfo=None),
        name="Alice Example",
        email="alice@example.com",
        subject="Question about pricing",
        body="Hi team, I have a quick question about the pro plan.",
        locale="en",
        user_id=None,
        organization_id=None,
        ip_address="127.0.0.1",
        status="pending",
        attempts=0,
    )
    for k, v in overrides.items():
        setattr(msg, k, v)
    db_session.add(msg)
    db_session.commit()
    db_session.refresh(msg)
    return msg


class _FakeTaskSelf:
    """Minimal stand-in for Celery's `self` to invoke a bound task synchronously."""

    def __init__(self, retries: int = 0, max_retries: int = 5) -> None:
        self.request = MagicMock()
        self.request.retries = retries
        self.max_retries = max_retries
        self.retry = MagicMock(side_effect=AssertionError("self.retry() was called"))


# Test 1 — Happy path: PSS recipient read at task time + correct reply-to


def test_send_contact_email_reads_pss_recipient(db_session):
    """Task reads CONTACT_RECIPIENT from PSS at execution time and calls EmailService.send correctly."""
    from app.services.platform_settings_service import PlatformSettingsService

    PlatformSettingsService.set(db_session, "CONTACT_RECIPIENT", "ops@example.com")
    db_session.commit()

    msg = _seed_message(db_session)

    with patch.object(EmailService, "send", return_value=True) as mock_send:
        # Invoke the bound task body synchronously via .apply() — Celery's eager
        # invoker drives the same code path the worker executes.
        result = send_contact_email.apply(args=(msg.id,)).get()

    assert mock_send.call_count == 1
    kwargs = mock_send.call_args.kwargs
    assert kwargs["to"] == "ops@example.com"
    assert kwargs["subject"].startswith("[JAOT Contact] ")
    assert msg.subject in kwargs["subject"]
    assert kwargs["reply_to"] == f"{msg.name} <{msg.email}>"

    db_session.refresh(msg)
    assert msg.status == "sent"
    assert msg.sent_at is not None
    assert msg.attempts == 1
    assert result.get("status") == "sent"


# Test 2 — Transient SMTP failure triggers exponential retry


def test_send_contact_email_retries_on_smtp_exception(db_session):
    """SMTPException raises self.retry(countdown=60 * 2**retries)."""
    msg = _seed_message(db_session)

    with patch.object(EmailService, "send", side_effect=smtplib.SMTPException("transient")):
        with patch(
            "app.tasks.contact_tasks.send_contact_email.retry",
            side_effect=Exception("retry-signal"),
        ) as mock_retry:
            with pytest.raises(Exception, match="retry-signal"):
                send_contact_email.apply(args=(msg.id,), throw=True).get()

    assert mock_retry.called
    kwargs = mock_retry.call_args.kwargs
    assert "exc" in kwargs
    # Countdown follows 60 * 2**retries — first attempt (retries=0) → 60s.
    countdown = kwargs.get("countdown")
    assert countdown in {60, 120, 240, 480, 960}

    db_session.refresh(msg)
    assert msg.attempts >= 1


# Test 3 — Retries exhausted → status=failed + one admin notification


def test_send_contact_email_final_failure_flips_status(db_session):
    """When retries exhausted, status='failed' and exactly ONE admin notice is sent."""
    msg = _seed_message(db_session, attempts=5)

    # Simulate "this is the last attempt" — self.request.retries == max_retries.
    call_log: list[dict[str, Any]] = []

    def _record_send(**kwargs: Any) -> bool:
        call_log.append(kwargs)
        # The primary delivery and the fire-and-forget admin notice both target the
        # same CONTACT_RECIPIENT, so call ORDER — not the recipient address — is what
        # distinguishes them: first call = the primary attempt → simulate a permanent
        # failure; second call = the admin notice → succeeds.
        if len(call_log) == 1:
            raise smtplib.SMTPException("permanent")
        return True

    with patch.object(EmailService, "send", side_effect=_record_send):
        # Force the task into terminal-failure branch. The task body must
        # detect self.request.retries >= max_retries and skip self.retry().
        with patch(
            "app.tasks.contact_tasks.send_contact_email.retry",
            side_effect=Exception("MaxRetriesExceededError"),
        ):
            try:
                send_contact_email.apply(args=(msg.id,), throw=True).get()
            except Exception:
                # Final failure may propagate; we assert on DB state below.
                pass

    db_session.refresh(msg)
    assert msg.status == "failed"
    assert msg.last_error is not None
    # Exactly 2 EmailService.send invocations: the primary attempt + 1 admin notice.
    # The admin notice MUST NOT recursively enqueue another send_contact_email.
    assert len(call_log) == 2, (
        f"Expected 2 EmailService.send invocations (1 primary + 1 admin notice), "
        f"got {len(call_log)}: {call_log}"
    )


# Test 4 — Only message_id traverses Celery broker (T-09-10 mitigation)


def test_send_contact_email_passes_only_message_id_via_celery(db_session):
    """`.delay()` signature must accept ONLY message_id — no PII through the broker."""
    msg = _seed_message(db_session)

    with patch("app.tasks.contact_tasks.send_contact_email.apply_async") as mock_apply_async:
        send_contact_email.delay(msg.id)

    # `.delay(x)` translates to `.apply_async(args=(x,))` internally.
    assert mock_apply_async.call_count == 1
    call_args, call_kwargs = mock_apply_async.call_args
    # The argument tuple/list must contain exactly the message id — nothing else.
    positional_args = call_kwargs.get("args", call_args[0] if call_args else ())
    assert list(positional_args) == [msg.id], (
        f"Celery args should be [message_id] only; got {positional_args}. "
        f"PII (name/email/body) must never traverse the broker (T-09-10)."
    )
    # And no kwargs payload (which would also serialize through the broker).
    payload_kwargs = call_kwargs.get("kwargs") or {}
    assert "name" not in payload_kwargs
    assert "email" not in payload_kwargs
    assert "body" not in payload_kwargs
