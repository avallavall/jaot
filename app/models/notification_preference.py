"""NotificationPreference model for per-user notification toggle settings."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class NotificationPreference(Base):
    """Per-user notification preference for a specific event type and channel.

    Event types: "sale", "review", "payout", "promotion_expiring"
    Channels: "in_app", "email"

    Each row represents whether a user has enabled/disabled a specific
    notification event type on a specific channel.
    """

    __tablename__ = "notification_preferences"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("npf_")
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "sale", "review", "payout", "promotion_expiring"
    channel: Mapped[str] = mapped_column(String(16), nullable=False)  # "in_app" or "email"
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "event_type", "channel", name="uq_notif_pref_user_event_channel"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationPreference(id={self.id!r}, user={self.user_id!r}, "
            f"event={self.event_type!r}, channel={self.channel!r}, enabled={self.enabled})>"
        )
