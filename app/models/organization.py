"""Organization model."""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class Plan(str, Enum):
    """Subscription plan types."""

    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    BUSINESS = "business"


class Currency(str, Enum):
    """Supported currencies."""

    EUR = "EUR"  # Euro (base currency)
    USD = "USD"  # US Dollar
    GBP = "GBP"  # British Pound
    CHF = "CHF"  # Swiss Franc


class Organization(Base):
    """Organization/Company that uses the platform."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, default="free")  # free, starter, pro, business

    # Credits — three separate pools that sum to credits_balance:
    #   credits_subscription: refreshed monthly (use-it-or-lose-it at renewal)
    #   credits_purchased:    from top-ups, never expire, never withdrawable
    #   credits_earned:       from marketplace sales, withdrawable after hold period
    credits_balance: Mapped[int] = mapped_column(Integer, default=50)
    credits_subscription: Mapped[int] = mapped_column(Integer, default=50)
    credits_purchased: Mapped[int] = mapped_column(Integer, default=0)
    credits_used_month: Mapped[int] = mapped_column(Integer, default=0)
    monthly_quota: Mapped[int] = mapped_column(Integer, default=50)

    # Credits earned from marketplace sales (can be withdrawn)
    credits_earned: Mapped[int] = mapped_column(Integer, default=0)

    # Low-credits notification tracking (reset on any positive credit transaction)
    low_credits_notified: Mapped[bool] = mapped_column(default=False)

    # Rate limits (requests per minute)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=2)
    rate_limit_per_day: Mapped[int] = mapped_column(Integer, default=10)

    # Billing & Currency
    billing_email: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, default="EUR")  # EUR, USD, GBP, CHF

    # Stripe
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Stripe Connect (seller payouts)
    stripe_connect_account_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    stripe_connect_onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    # Chargeback fraud protection (per D-09)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    chargeback_count: Mapped[int] = mapped_column(Integer, default=0)

    # Webhooks
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Plugin & Builder capabilities
    max_private_plugins: Mapped[int] = mapped_column(Integer, default=5)
    ai_builder_enabled: Mapped[bool] = mapped_column(default=False)

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
