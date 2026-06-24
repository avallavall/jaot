"""Usage record model for tracking API usage."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class UsageRecord(Base):
    """Record of API usage for billing and analytics."""

    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Relationships
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    # Request details
    problem_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    credits_used: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # success, error

    # Optional metadata (JSON field for flexibility)
    request_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    def __repr__(self) -> str:
        return (
            f"<UsageRecord(id={self.id}, problem={self.problem_type}, credits={self.credits_used})>"
        )
