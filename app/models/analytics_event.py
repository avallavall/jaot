"""AnalyticsEvent model for tracking feature usage across the platform."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class AnalyticsEvent(Base):
    """Tracks feature usage events for admin analytics dashboard.

    Each record represents a single user action (solver.solve, marketplace.purchase,
    ai_builder.message, etc.). Events are logged fire-and-forget on the request's
    DB session, never blocking the main response.

    Columns:
    - id: Prefixed with "ae_"
    - user_id: Authenticated user who performed the action
    - org_id: User's organization at event time
    - event_type: domain.action string (e.g., "solver.solve")
    - country_code: ISO 3166-1 alpha-2 from geoIP lookup (no raw IP stored)
    - metadata: Optional JSON with event-specific data
    - created_at: UTC timestamp
    """

    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("ae_")
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_ae_event_type_created", "event_type", "created_at"),
        Index("ix_ae_user_created", "user_id", "created_at"),
        Index("ix_ae_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AnalyticsEvent(id={self.id!r}, type={self.event_type!r}, user={self.user_id!r})>"
