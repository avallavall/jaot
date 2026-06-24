"""User model."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class User(Base):
    """User that belongs to an organization."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)

    # Organization relationship
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False
    )

    # Role within organization
    role: Mapped[str] = mapped_column(String, default="member")  # admin, member

    # Password auth (NULL for API-key-only users)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # GDPR / Terms of Service
    tos_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Account lockout
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Plugin & Builder capabilities
    can_build_plugins: Mapped[bool] = mapped_column(Boolean, default=False)
    builder_tier: Mapped[str] = mapped_column(String, default="basic")  # basic, advanced, expert

    # Public Profile
    slug: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True, index=True
    )  # URL-friendly username
    display_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Public display name
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_public_profile: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # Show in public directory

    # Locale preference (NULL = use browser detection)
    locale: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)

    # Guidance preferences
    skill_level: Mapped[str] = mapped_column(
        String(20), default="beginner", nullable=False, server_default="beginner"
    )
    guidance_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=None)

    @property
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == "admin"

    @property
    def full_name(self) -> str:
        """Alias for name field for compatibility."""
        return self.name

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"
