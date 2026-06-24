"""Refresh token model for JWT session revocation."""

import secrets
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class RefreshToken(Base):
    """Stores refresh token metadata for revocation support.

    Each refresh token has a unique ``jti`` (JWT ID) that is stored here.
    When a user logs out or a token is rotated, the record is marked
    ``revoked=True`` so subsequent usage is rejected.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"rt_{secrets.token_hex(8)}"
    )
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    jti: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, revoked={self.revoked})>"
