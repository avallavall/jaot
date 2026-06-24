"""VerificationRequest model for seller badge verification workflow."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class VerificationStatus(str, Enum):
    """Status of a verification request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VerificationRequest(Base):
    """Request from a seller organization to receive the verified publisher badge.

    Workflow:
    1. Seller submits request (status=pending)
    2. Admin reviews org profile, published models, etc.
    3. Admin approves (sets Organization.is_verified=True) or rejects with note
    """

    __tablename__ = "verification_requests"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("vrf_")
    )
    organization_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[str] = mapped_column(String(64), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=VerificationStatus.PENDING.value, index=True
    )
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            f"<VerificationRequest(id={self.id!r}, org={self.organization_id!r}, "
            f"status={self.status!r})>"
        )
