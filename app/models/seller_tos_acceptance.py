"""Seller Terms of Service acceptance tracking (per D-16)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class SellerToSAcceptance(Base):
    """Tracks when a seller organization accepted the Seller ToS."""

    __tablename__ = "seller_tos_acceptances"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )
    tos_version: Mapped[str] = mapped_column(String(50), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    accepted_by_user_id: Mapped[str] = mapped_column(String, nullable=False)

    def __repr__(self) -> str:
        return f"<SellerToSAcceptance(org={self.organization_id}, version={self.tos_version})>"
