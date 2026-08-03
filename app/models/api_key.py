"""API Key model."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class APIKey(Base):
    """API Key for authentication."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Hashed key (never store plaintext)
    key_hash: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)  # e.g., "ok_live_"

    # Relationships. A key is a credential of its principal: it must not survive
    # the user or the organization it authenticates (QA 2026-08-02: this FK
    # blocked deleting an organization at all).
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Metadata
    name: Mapped[str | None] = mapped_column(String, nullable=True)  # User-friendly name
    description: Mapped[str | None] = mapped_column(String, nullable=True)  # Description
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, prefix={self.key_prefix}, active={self.is_active})>"
