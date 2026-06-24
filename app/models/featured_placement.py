"""FeaturedPlacement model for purchased marketplace promotions."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class PlacementType(str, Enum):
    """Types of featured placements available for purchase."""

    HOMEPAGE_CAROUSEL = "homepage_carousel"
    CATEGORY_SPOTLIGHT = "category_spotlight"
    SEARCH_BOOST = "search_boost"
    PROMOTED_BADGE = "promoted_badge"


class PlacementStatus(str, Enum):
    """Status of a featured placement."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class FeaturedPlacement(Base):
    """Purchased promotion placement for a marketplace model.

    Sellers buy placements to feature their models in specific locations
    (homepage carousel, category spotlight, search boost, promoted badge).
    Placements have a duration and auto-expire.
    """

    __tablename__ = "featured_placements"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("fpl_")
    )
    catalog_model_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_catalog.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    placement_type: Mapped[str] = mapped_column(String(32), nullable=False)  # PlacementType value
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PlacementStatus.ACTIVE.value
    )
    credits_paid: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            f"<FeaturedPlacement(id={self.id!r}, type={self.placement_type!r}, "
            f"status={self.status!r})>"
        )
