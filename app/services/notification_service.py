"""Notification service for sending and managing notifications."""

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import Notification, NotificationChannel, NotificationPreference, NotificationType
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for creating and managing notifications."""

    def __init__(self, db: Session):
        self.db = db

    def create_notification(
        self,
        user_id: str,
        organization_id: str,
        notification_type: NotificationType,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
        link: str | None = None,
        channel: NotificationChannel = NotificationChannel.IN_APP,
        reference_type: str | None = None,
        reference_id: str | None = None,
    ) -> Notification:
        """Create a new notification.

        Args:
            user_id: ID of the target user.
            organization_id: Org scoping (multi-tenancy invariant).
            notification_type: Enum value classifying the notification.
            title: Short display title.
            message: Full notification body.
            data: Optional JSON payload for the frontend.
            link: Optional deep-link URL.
            channel: Delivery channel (in_app, email, both).
            reference_type: Optional entity kind for per-entity dedup
                (e.g. "solver_license"). Part of the E-12 / D-7.1-12
                dedup infrastructure — callers that don't need dedup
                can omit this; the column stores NULL.
            reference_id: Optional entity primary key paired with
                reference_type (e.g. "lic_abc123"). NULL when not set.
        """
        notification = Notification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            organization_id=organization_id,
            type=notification_type.value,
            title=title,
            message=message,
            data=data,
            link=link,
            channel=channel.value,
            created_at=utcnow(),
            reference_type=reference_type,
            reference_id=reference_id,
        )

        self.db.add(notification)
        self.db.flush()
        self.db.refresh(notification)

        logger.info(f"Created notification {notification.id} for user {user_id}")

        if channel in (NotificationChannel.EMAIL, NotificationChannel.BOTH):
            self._send_email_notification(notification)

        return notification

    def notify_execution_completed(
        self,
        user_id: str,
        organization_id: str,
        execution_id: str,
        model_name: str,
        objective_value: float | None = None,
    ) -> Notification:
        """Notify user that an execution completed successfully."""
        message = f"Your optimization '{model_name}' completed successfully."
        if objective_value is not None:
            message += f" Objective value: {objective_value:.4f}"

        return self.create_notification(
            user_id=user_id,
            organization_id=organization_id,
            notification_type=NotificationType.EXECUTION_COMPLETED,
            title="Execution Completed",
            message=message,
            data={
                "execution_id": execution_id,
                "model_name": model_name,
                "objective_value": objective_value,
            },
            link=f"/solve/executions/{execution_id}",
        )

    def notify_execution_failed(
        self,
        user_id: str,
        organization_id: str,
        execution_id: str,
        model_name: str,
        error: str,
    ) -> Notification:
        """Notify user that an execution failed."""
        return self.create_notification(
            user_id=user_id,
            organization_id=organization_id,
            notification_type=NotificationType.EXECUTION_FAILED,
            title="Execution Failed",
            message=f"Your optimization '{model_name}' failed: {error[:100]}",
            data={
                "execution_id": execution_id,
                "model_name": model_name,
                "error": error,
            },
            link=f"/solve/executions/{execution_id}",
        )

    def notify_credits_low(
        self,
        user_id: str,
        organization_id: str,
        current_balance: int,
        threshold: int = 10,
    ) -> Notification:
        """Notify user that credits are running low."""
        return self.create_notification(
            user_id=user_id,
            organization_id=organization_id,
            notification_type=NotificationType.CREDITS_LOW,
            title="Credits Running Low",
            message=f"You have {current_balance} credits remaining. Consider adding more credits to avoid interruptions.",
            data={
                "current_balance": current_balance,
                "threshold": threshold,
            },
            link="/workspace/credits",
        )

    def notify_credits_depleted(
        self,
        user_id: str,
        organization_id: str,
    ) -> Notification:
        """Notify user that credits are depleted."""
        return self.create_notification(
            user_id=user_id,
            organization_id=organization_id,
            notification_type=NotificationType.CREDITS_DEPLETED,
            title="Credits Depleted",
            message="You have run out of credits. Add more credits to continue using optimization models.",
            link="/workspace/credits",
            channel=NotificationChannel.BOTH,
        )

    def get_user_notifications(
        self,
        user_id: str,
        organization_id: str,
        *,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[Notification]:
        """Get notifications for a user, scoped to their organization.

        Tenant isolation: ``organization_id`` is REQUIRED to prevent
        cross-tenant leakage. Making it positional-required (not optional)
        means a future caller cannot silently forget it.
        """
        query = self.db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.organization_id == organization_id,
        )

        if unread_only:
            query = query.filter(Notification.is_read == False)  # noqa: E712

        return query.order_by(Notification.created_at.desc()).limit(limit).all()

    def get_unread_count(self, user_id: str, organization_id: str) -> int:
        """Get count of unread notifications for a user in their organization.

        Tenant isolation: ``organization_id`` is REQUIRED.
        """
        return (
            self.db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.organization_id == organization_id,
                Notification.is_read == False,  # noqa: E712
            )
            .count()
        )

    def mark_as_read(
        self,
        notification_id: str,
        user_id: str,
        organization_id: str,
    ) -> Notification | None:
        """Mark a notification as read.

        Tenant isolation: ``organization_id`` is REQUIRED. The notification
        must belong to that organization or the call returns None.
        """
        notification = (
            self.db.query(Notification)
            .filter(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.organization_id == organization_id,
            )
            .first()
        )

        if notification:
            notification.mark_as_read()

        return notification

    def mark_all_as_read(self, user_id: str, organization_id: str) -> int:
        """Mark all notifications as read for a user in their organization.

        Tenant isolation: ``organization_id`` is REQUIRED.
        """
        return (
            self.db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.organization_id == organization_id,
                Notification.is_read == False,  # noqa: E712
            )
            .update(
                {
                    "is_read": True,
                    "read_at": utcnow(),
                }
            )
        )

    # --- Event type to NotificationType mapping ---
    _SELLER_EVENT_MAP: dict[str, NotificationType] = {
        "sale": NotificationType.NEW_SALE,
        "review": NotificationType.NEW_REVIEW,
        "payout": NotificationType.PAYOUT_COMPLETED,
        "promotion_expiring": NotificationType.PROMOTION_EXPIRING,
    }

    # Default preferences: in_app ON, email OFF (missing-row-means-default pattern)
    _DEFAULT_PREFS: dict[str, bool] = {"in_app": True, "email": False}

    def send_seller_notification(
        self,
        user_id: str,
        organization_id: str,
        event_type: str,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
        link: str | None = None,
    ) -> Notification | None:
        """Send a preference-aware seller notification.

        Checks user's notification preferences before dispatching.
        If no preference row exists for a (event_type, channel) combo,
        applies defaults: in_app=True, email=False.
        """
        notification_type = self._SELLER_EVENT_MAP.get(event_type)
        if not notification_type:
            logger.warning(f"Unknown seller event type: {event_type}")
            return None

        # Query user preferences for this event type
        prefs = (
            self.db.query(NotificationPreference)
            .filter(
                NotificationPreference.user_id == user_id,
                NotificationPreference.event_type == event_type,
            )
            .all()
        )
        pref_map: dict[str, bool] = {p.channel: p.enabled for p in prefs}

        in_app_enabled = pref_map.get("in_app", self._DEFAULT_PREFS["in_app"])
        email_enabled = pref_map.get("email", self._DEFAULT_PREFS["email"])

        if not in_app_enabled and not email_enabled:
            logger.debug(
                f"Seller notification skipped (all channels disabled) for user {user_id}, event {event_type}"
            )
            return None

        if in_app_enabled and email_enabled:
            channel = NotificationChannel.BOTH
        elif in_app_enabled:
            channel = NotificationChannel.IN_APP
        else:
            channel = NotificationChannel.EMAIL

        return self.create_notification(
            user_id=user_id,
            organization_id=organization_id,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data,
            link=link,
            channel=channel,
        )

    def _send_email_notification(self, notification: Notification) -> bool:
        """Send email notification (placeholder for future implementation)."""
        # Email delivery via SMTP is handled by EmailService (v2.0 backlog: dedicated transactional provider).
        logger.info(f"Email notification queued for {notification.user_id}: {notification.title}")

        notification.email_sent = True
        notification.email_sent_at = utcnow()

        return True
