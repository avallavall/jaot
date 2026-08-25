"""
Celery tasks for onboarding email sequence.

Tasks:
    - send_onboarding_email: Send a specific onboarding email to a user
    - schedule_onboarding_sequence: Schedule the sequence for a new user
    - send_notification_email: Deliver one notification off the request path

We use Celery's `apply_async(countdown=...)` for scheduling future sends.
"""

import logging
from datetime import timedelta
from typing import Any

from app.config import settings
from app.services import email_layout
from app.services.email_service import EmailService
from app.services.onboarding_emails import (
    ONBOARDING_SEQUENCE,
)
from app.shared.core.celery_app import celery_app

logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when an email send attempt fails (SMTP rejection, transport error)."""


@celery_app.task(  # type: ignore[misc]
    name="app.tasks.email_tasks.send_onboarding_email",
    bind=True,
    max_retries=settings.CELERY_MAX_RETRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
)
def send_onboarding_email(
    self: Any, user_email: str, user_name: str, day: int, **kwargs: Any
) -> dict[str, Any]:
    """
    Send a specific onboarding email.

    Args:
        user_email: Recipient email address
        user_name: User's display name
        day: Day offset (0, 1, 3, 14)
        **kwargs: Extra args passed to the email generator (e.g. api_key_prefix)
    """
    generator = ONBOARDING_SEQUENCE.get(day)
    if not generator:
        logger.error(f"No onboarding email for day {day}")
        return {"status": "error", "reason": f"no template for day {day}"}

    locale = kwargs.get("locale")

    try:
        # Each generator has different signatures
        if day == 0:
            subject, html = generator(
                user_name, kwargs.get("api_key_prefix", "ok_live_"), locale=locale
            )
        else:
            subject, html = generator(user_name, locale=locale)

        success = EmailService.send(
            to=user_email,
            subject=subject,
            html=html,
            # The address the rest of the platform publishes — the footer of
            # every email, the privacy and terms pages, the help menu.
            # `founders@jaot.io` appeared here and in one email body, and
            # nowhere else in the product.
            reply_to=email_layout.SUPPORT_EMAIL,
        )

        if success:
            logger.info(f"Onboarding day {day} email sent to {user_email}")
            return {"status": "sent", "day": day, "to": user_email}
        raise EmailDeliveryError(f"EmailService.send returned False for day {day} → {user_email}")

    except Exception as exc:
        logger.error(f"Failed to send onboarding day {day} to {user_email}: {exc}")
        raise self.retry(exc=exc) from exc


@celery_app.task(  # type: ignore[misc]
    name="app.tasks.email_tasks.send_notification_email",
    bind=True,
    max_retries=settings.CELERY_MAX_RETRIES,
    default_retry_delay=settings.CELERY_DEFAULT_RETRY_DELAY,
)
def send_notification_email(self: Any, notification_id: str) -> dict[str, Any]:
    """Deliver one notification by email, and record only what happened.

    Off the request path on purpose. Sending inline meant a slow or unreachable
    SMTP server added up to ``SMTP_TIMEOUT`` seconds to whatever the reader had
    just done — adopting a model, leaving a review — for an email that is not
    part of that action at all. A retry here also costs the reader nothing.

    The in-app notification is written before this is queued, so a mail server
    that is down loses nothing but the copy in the inbox.
    """
    from app.models import Notification, User
    from app.services import email_layout as layout
    from app.shared.db.session import SessionLocal
    from app.shared.utils.datetime_helpers import utcnow

    db = SessionLocal()
    try:
        notification = db.query(Notification).filter(Notification.id == notification_id).first()
        if notification is None:
            # Deleted between queueing and delivery. Nothing to chase.
            logger.info("Notification %s is gone — nothing to send", notification_id)
            return {"status": "gone", "notification_id": notification_id}
        if notification.email_sent:
            return {"status": "already_sent", "notification_id": notification_id}

        user = db.query(User).filter(User.id == notification.user_id).first()
        if user is None or not user.email:
            logger.warning("No address for notification %s — not sent", notification_id)
            return {"status": "no_address", "notification_id": notification_id}

        # The title and the message carry user-supplied text: a notification
        # about an execution names the model, and a model is named by whoever
        # made it. The layout escapes what it is given.
        body = layout.heading(notification.title) + layout.paragraph(notification.message)
        if notification.link:
            body += layout.button(notification.link, notification.title)

        sent = EmailService.send(
            to=user.email,
            subject=notification.title,
            html=layout.wrap(body, getattr(user, "locale", None)),
            db=db,
        )
        if not sent:
            raise EmailDeliveryError(f"EmailService.send returned False for {notification_id}")

        notification.email_sent = True
        notification.email_sent_at = utcnow()
        db.commit()
        return {"status": "sent", "notification_id": notification_id}
    except EmailDeliveryError as exc:
        db.rollback()
        logger.error("Notification email %s failed: %s", notification_id, exc)
        raise self.retry(exc=exc) from exc
    except Exception as exc:
        db.rollback()
        logger.error("Notification email %s failed: %s", notification_id, exc, exc_info=True)
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


@celery_app.task(name="app.tasks.email_tasks.schedule_onboarding_sequence")  # type: ignore[misc]
def schedule_onboarding_sequence(
    user_email: str, user_name: str, api_key_prefix: str = "ok_live_", locale: str | None = None
) -> dict[str, Any]:
    """
    Schedule the full onboarding email sequence for a new user.

    Called once when a user signs up. Schedules 5 emails:
        Day 0  — immediately
        Day 1  — 24 hours later
        Day 3  — 72 hours later
        Day 7  — 168 hours later
        Day 14 — 336 hours later
    """
    day_offsets = sorted(ONBOARDING_SEQUENCE.keys())

    for day in day_offsets:
        eta_delta = timedelta(days=day)

        # Day 0 is sent immediately (but still via task for consistency)
        if day == 0:
            eta_delta = timedelta(seconds=5)  # Small delay to avoid race conditions

        send_onboarding_email.apply_async(
            kwargs={
                "user_email": user_email,
                "user_name": user_name,
                "day": day,
                "api_key_prefix": api_key_prefix,
                "locale": locale,
            },
            eta=None,  # Will use countdown instead
            countdown=int(eta_delta.total_seconds()),
        )

    logger.info(f"Onboarding sequence scheduled for {user_email}: days {day_offsets}")
    return {
        "status": "scheduled",
        "user_email": user_email,
        "days": day_offsets,
    }
