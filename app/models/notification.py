"""Notification model for user notifications."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow

if TYPE_CHECKING:
    from app.models.user import User


class NotificationType(str, Enum):
    """Types of notifications."""

    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    CREDITS_LOW = "credits_low"
    CREDITS_DEPLETED = "credits_depleted"
    SYSTEM = "system"
    # Seller experience events
    NEW_SALE = "new_sale"
    PAYOUT_COMPLETED = "payout_completed"
    NEW_REVIEW = "new_review"
    PROMOTION_EXPIRING = "promotion_expiring"


class NotificationChannel(str, Enum):
    """Channels for delivering notifications."""

    IN_APP = "in_app"
    EMAIL = "email"
    BOTH = "both"


class Notification(Base):
    """
    User notifications.

    Stores notifications for users about execution results,
    credit alerts, and system messages.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    link: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Per-license dedup fields (E-12, D-7.1-09). reference_type identifies
    # the entity kind (e.g. "solver_license"), reference_id carries its PK.
    # Both nullable: pre-migration rows and notifications not tied to an
    # entity remain unaffected. Partial index idx_notifications_reference
    # speeds up the dedup query in scan_solver_license_expiries_impl.
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    channel: Mapped[str] = mapped_column(String(16), default="in_app")
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="joined")

    __table_args__ = (
        Index("ix_notification_user_unread", "user_id", "is_read"),
        Index("ix_notification_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, type={self.type}, user={self.user_id})>"

    def mark_as_read(self) -> None:
        """Mark notification as read."""
        self.is_read = True
        self.read_at = utcnow()
