"""Organization model."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class Plan(str, Enum):
    """Subscription plan types."""

    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"


class Organization(Base):
    """Organization/Company that uses the platform."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, default="free")  # free, starter, pro, business

    # Rate limits (requests per minute)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=60)
    rate_limit_per_day: Mapped[int] = mapped_column(Integer, default=2000)

    # Webhooks
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Plugin & Builder capabilities
    max_private_plugins: Mapped[int] = mapped_column(Integer, default=5)
    ai_builder_enabled: Mapped[bool] = mapped_column(default=False)

    # BYOK: the org's own Anthropic API key, Fernet-encrypted at rest (never stored
    # or returned in plaintext). When set, LLM calls for this org run on the org's
    # account instead of the shared platform key. See app/services/llm/byok.py.
    anthropic_api_key_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)

    # Public Profile
    slug: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True, index=True
    )  # URL-friendly name
    bio: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # Short description
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_verified: Mapped[bool] = mapped_column(default=False)  # Verified publisher badge
    is_public_profile: Mapped[bool] = mapped_column(default=False)  # Show in public directory

    # Workspace collaboration
    # FK to the organization owner. Uses use_alter=True to handle circular
    # dependency (users -> organizations, organizations -> users).
    # The owner bypasses all workspace-level permission checks.
    owner_user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="SET NULL", use_alter=True, name="fk_org_owner_user"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name={self.name}, plan={self.plan})>"
