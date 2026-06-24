"""ModelViewEvent model for tracking marketplace impressions and views."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class ModelViewEvent(Base):
    """Tracks impression and view events for marketplace catalog models.

    Event types:
    - "impression": Model appeared in a listing/search result
    - "view": User clicked into the model detail page
    """

    __tablename__ = "model_view_events"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("mve_")
    )
    catalog_model_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("model_catalog.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "impression" or "view"
    viewer_organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    viewer_country: Mapped[str | None] = mapped_column(
        String(2), nullable=True
    )  # ISO 3166-1 alpha-2
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )

    __table_args__ = (
        Index(
            "ix_mve_model_type_created",
            "catalog_model_id",
            "event_type",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelViewEvent(id={self.id!r}, model={self.catalog_model_id!r}, "
            f"type={self.event_type!r})>"
        )
