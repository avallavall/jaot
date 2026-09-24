"""
Celery tasks for onboarding email sequence.

Tasks:
    - send_onboarding_email: Send a specific onboarding email to a user
    - schedule_onboarding_sequence: Send the day-0 email to a new user
    - send_due_onboarding_emails: Hourly beat sweep that sends the later emails
    - send_notification_email: Deliver one notification off the request path

The later emails are not queued with a countdown. A worker holds a delayed
message unacknowledged until it is due, and RabbitMQ closes a channel that
holds one longer than ``consumer_timeout`` (30 minutes by default).
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
        subject, html = layout.notification(
            notification.type,
            notification.data,
            notification.title,
            notification.message,
            notification.link,
            getattr(user, "locale", None),
        )

        sent = EmailService.send(to=user.email, subject=subject, html=html, db=db)
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
    Send the day-0 onboarding email to a new user.

    Called once when a user signs up. Day 0 gets a 5-second delay so the row
    it describes is committed first. The later days are sent by
    :func:`send_due_onboarding_emails`.

    They were queued here with a countdown of up to 14 days. A worker holds
    such a message unacknowledged until it is due, and RabbitMQ closes a
    channel that holds one longer than ``consumer_timeout`` (30 minutes). The
    worker then lost its connection every 30 minutes, the other tasks running
    on it at that moment could not acknowledge and ran again, and a user who
    had deleted their account still got the later emails.
    """
    send_onboarding_email.apply_async(
        kwargs={
            "user_email": user_email,
            "user_name": user_name,
            "day": 0,
            "api_key_prefix": api_key_prefix,
            "locale": locale,
        },
        countdown=5,
    )

    logger.info("Onboarding day 0 queued for a new user")
    return {"status": "scheduled", "user_email": user_email, "days": [0]}


#: The onboarding days sent by the sweep: every day in the sequence after 0.
_LATER_DAYS: tuple[int, ...] = tuple(sorted(d for d in ONBOARDING_SEQUENCE if d > 0))
#: How long after the last email is due a user is still looked at. A sweep
#: that did not run for this long does not send old emails to old accounts.
_SWEEP_GRACE_DAYS = 2
#: At most this many emails per sweep. The rest go out an hour later.
_SWEEP_LIMIT = 500


@celery_app.task(name="send_due_onboarding_emails")  # type: ignore[misc]
def send_due_onboarding_emails() -> dict[str, Any]:
    """Send each new user the onboarding email that is due now. Run hourly by beat.

    A user gets only the latest email that is due: a user 15 days old who
    never got day 3 gets day 14 and not both. Each user is claimed with a
    conditional UPDATE, so two sweeps at once send one email. The address,
    name and language are read now, so a deleted or deactivated account gets
    nothing, and a user who changed their language gets the new one.
    """
    from sqlalchemy import and_, func, or_, update

    from app.models import User
    from app.shared.db.session import SessionLocal
    from app.shared.utils.datetime_helpers import utcnow

    now = utcnow()
    sent_through = func.coalesce(User.onboarding_last_day, 0)
    is_due = or_(
        *(
            and_(User.created_at <= now - timedelta(days=day), sent_through < day)
            for day in _LATER_DAYS
        )
    )
    summary = {"queued": 0, "errors": 0}
    db = SessionLocal()
    try:
        candidates = (
            db.query(User.id, User.created_at)
            .filter(
                User.is_active.is_(True),
                User.created_at > now - timedelta(days=_LATER_DAYS[-1] + _SWEEP_GRACE_DAYS),
                is_due,
            )
            .order_by(User.created_at)
            .limit(_SWEEP_LIMIT)
            .all()
        )
        for user_id, created_at in candidates:
            day = max(d for d in _LATER_DAYS if created_at <= now - timedelta(days=d))
            try:
                claimed = db.execute(
                    update(User)
                    .where(
                        User.id == user_id,
                        User.is_active.is_(True),
                        func.coalesce(User.onboarding_last_day, 0) < day,
                    )
                    .values(onboarding_last_day=day)
                    .returning(User.email, User.name, User.locale)
                ).first()
                if claimed is None:
                    db.rollback()  # another sweep sent it, or the account went
                    continue
                # Queued before the commit: when the broker refuses it, the
                # rollback leaves the email due for the next sweep.
                send_onboarding_email.delay(
                    user_email=claimed.email,
                    user_name=claimed.name,
                    day=day,
                    locale=claimed.locale,
                )
                db.commit()
                summary["queued"] += 1
            except Exception as exc:  # noqa: BLE001 — one user must not stop the sweep
                db.rollback()
                summary["errors"] += 1
                logger.error("Onboarding day %s for user %s failed: %s", day, user_id, exc)
    finally:
        db.close()
    if summary["queued"] or summary["errors"]:
        logger.info("Onboarding sweep: %s", summary)
    return summary
