"""
Celery tasks for onboarding email sequence.

Tasks:
    - send_onboarding_email: Send a specific onboarding email to a user
    - schedule_onboarding_sequence: Schedule all 5 emails for a new user
    - process_pending_onboarding: Periodic task to send due onboarding emails

The sequence is stored in the `onboarding_emails` table (or as scheduled Celery tasks).
We use Celery's `apply_async(eta=...)` for scheduling future sends.
"""

import logging
from datetime import timedelta
from typing import Any

from app.config import settings
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
        day: Day offset (0, 1, 3, 7, 14)
        **kwargs: Extra args passed to the email generator (e.g. api_key_prefix, credits_balance)
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
        elif day == 7:
            subject, html = generator(user_name, kwargs.get("credits_balance", 200), locale=locale)
        else:
            subject, html = generator(user_name, locale=locale)

        success = EmailService.send(
            to=user_email,
            subject=subject,
            html=html,
            reply_to="founders@jaot.io",
        )

        if success:
            logger.info(f"Onboarding day {day} email sent to {user_email}")
            return {"status": "sent", "day": day, "to": user_email}
        else:
            raise EmailDeliveryError(
                f"EmailService.send returned False for day {day} → {user_email}"
            )

    except Exception as exc:
        logger.error(f"Failed to send onboarding day {day} to {user_email}: {exc}")
        raise self.retry(exc=exc) from exc


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
