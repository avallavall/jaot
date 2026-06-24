"""Celery tasks for the public contact form (Phase 9 D-04: durable retry semantics).

Only ``message_id`` traverses the Celery broker — never name/email/body — so a
broker-side compromise can't exfiltrate user-submitted PII (T-09-10).
"""

from __future__ import annotations

import html
import logging
import smtplib
from typing import Any

from app.models.contact_message import ContactMessage
from app.services.email_service import EmailService
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core.celery_app import celery_app
from app.shared.core.prometheus_metrics import CONTACT_SEND_ATTEMPTS
from app.shared.db.session import SessionLocal
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


class ContactEmailDeliveryError(RuntimeError):
    """EmailService.send returned False — surfaced so retry logic is uniform."""


def _log_send_attempt(
    *, message_id: str, result: str, attempt_number: int | None, max_retries: int
) -> None:
    """Single source of truth for the `contact_send_attempt` structured log shape."""
    logger.info(
        "contact_send_attempt",
        extra={
            "message_id": message_id,
            "result": result,
            "attempt_number": attempt_number,
            "max_retries": max_retries,
        },
    )


@celery_app.task(  # type: ignore[misc]
    name="app.tasks.contact_tasks.send_contact_email",
    bind=True,
    max_retries=5,
)
def send_contact_email(self: Any, message_id: str) -> dict[str, Any]:
    """Deliver a ``contact_messages`` row via SMTP (PSS-driven recipient, D-07).

    Retries transient SMTP errors with exponential backoff 60→120→240→480→960s
    (D-04). On terminal exhaustion the row's status flips to ``failed`` and a
    one-off admin alert is sent (fire-and-forget, NOT re-queued).

    The "is this the final attempt?" decision uses ``msg.attempts`` rather
    than ``self.request.retries`` so the body is robust against eager
    ``.apply()`` invocations from tests where Celery's request context is a
    stub. In production, ``msg.attempts`` advances in lockstep with
    ``self.request.retries`` because the row counter is incremented on every
    invocation before any send attempt.

    Args:
        message_id: ``ContactMessage.id`` (``ctc_``-prefixed). The ONLY value
            that traverses the Celery broker (T-09-10).
    """
    db = SessionLocal()
    try:
        msg = db.query(ContactMessage).filter(ContactMessage.id == message_id).first()
        if msg is None:
            logger.error("contact_messages row %s vanished before send", message_id)
            CONTACT_SEND_ATTEMPTS.labels(result="failed").inc()
            _log_send_attempt(
                message_id=message_id,
                result="failed",
                attempt_number=None,
                max_retries=self.max_retries,
            )
            return {"status": "missing", "message_id": message_id}

        msg.attempts += 1
        db.commit()

        recipient = PSS.get(db, "CONTACT_RECIPIENT")

        subject_line = f"[JAOT Contact] {msg.subject}"
        reply_to_header = f"{msg.name} <{msg.email}>"
        body_text = (
            f"Locale: {msg.locale or 'unknown'}\n"
            f"Submitted at: {msg.created_at.isoformat()}\n"
            f"From: {msg.name} <{msg.email}>\n"
            f"IP: {msg.ip_address or 'unknown'}\n"
        )
        if msg.user_id and msg.organization_id:
            body_text += f"Submitted by: user={msg.user_id} org={msg.organization_id}\n"
        body_text += f"\nSubject: {msg.subject}\n\n{msg.body}\n"

        # T-09-05: neutralize user-supplied <, >, & before wrapping in <pre>.
        html_body = f"<pre>{html.escape(body_text)}</pre>"

        try:
            success = EmailService.send(
                to=recipient,
                subject=subject_line,
                html=html_body,
                reply_to=reply_to_header,
                db=db,
            )
            if success:
                msg.status = "sent"
                msg.sent_at = utcnow().replace(tzinfo=None)
                db.commit()
                CONTACT_SEND_ATTEMPTS.labels(result="sent").inc()
                # T-09-09: NEVER log msg.body, msg.email, msg.name, recipient.
                _log_send_attempt(
                    message_id=message_id,
                    result="sent",
                    attempt_number=msg.attempts,
                    max_retries=self.max_retries,
                )
                return {"status": "sent", "message_id": message_id}
            raise ContactEmailDeliveryError("EmailService.send returned False")

        except (smtplib.SMTPException, OSError, ContactEmailDeliveryError) as exc:
            msg.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            db.commit()

            if msg.attempts <= self.max_retries:
                CONTACT_SEND_ATTEMPTS.labels(result="retry").inc()
                _log_send_attempt(
                    message_id=message_id,
                    result="retry",
                    attempt_number=msg.attempts,
                    max_retries=self.max_retries,
                )
                countdown = 60 * (2 ** (msg.attempts - 1))
                raise self.retry(exc=exc, countdown=countdown) from exc

            # Terminal exhaustion: do NOT call self.retry — that would risk
            # MaxRetriesExceededError surfacing as the task's terminal state.
            msg.status = "failed"
            db.commit()
            CONTACT_SEND_ATTEMPTS.labels(result="failed").inc()
            _log_send_attempt(
                message_id=message_id,
                result="failed",
                attempt_number=msg.attempts,
                max_retries=self.max_retries,
            )
            _send_failure_notification(msg, recipient, last_error=msg.last_error)
            logger.error("contact send failed permanently message_id=%s", message_id)
            return {"status": "failed", "message_id": message_id}
    finally:
        db.close()


def _send_failure_notification(msg: ContactMessage, recipient: str, last_error: str) -> None:
    """Fire-and-forget admin alert when delivery exhausts retries.

    D-04: this branch MUST NOT raise — we DO NOT re-queue or retry the
    failure notification (no recursive enqueue loop). Any exception is
    swallowed and logged.
    """
    diag_body = (
        f"Delivery for ContactMessage {msg.id} failed after exhausting retries.\n\n"
        f"Last error: {last_error}\n"
        f"From: {msg.name} <{msg.email}>\n"
        f"Subject: {msg.subject}\n"
    )
    try:
        EmailService.send(
            to=recipient,
            subject=f"[JAOT Contact ALERT] Delivery failed for {msg.id}",
            html=f"<pre>{html.escape(diag_body)}</pre>",
            reply_to=None,
        )
    except Exception:
        logger.exception(
            "Failed to send contact-form failure notice for message_id=%s — accepting silent drop",
            msg.id,
        )
