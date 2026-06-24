"""Admin-specific schemas.

Extended versions with stats and admin fields for CRUD operations.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrganizationCreate(BaseModel):
    """Create organization request."""

    name: str
    plan: str = "free"
    credits_balance: int = 100
    monthly_quota: int = 100
    rate_limit_per_minute: int = 2
    rate_limit_per_day: int = 10
    ai_builder_enabled: bool = False
    max_private_plugins: int = 5


class OrganizationUpdate(BaseModel):
    """Update organization request."""

    name: str | None = None
    plan: str | None = None
    credits_balance: int | None = None
    monthly_quota: int | None = None
    rate_limit_per_minute: int | None = None
    rate_limit_per_day: int | None = None
    ai_builder_enabled: bool | None = None
    max_private_plugins: int | None = None
    is_active: bool | None = None
    is_verified: bool | None = None


class OrganizationResponse(BaseModel):
    """Organization response with stats."""

    id: str
    name: str
    plan: str
    credits_balance: int
    credits_used_month: int
    monthly_quota: int
    rate_limit_per_minute: int
    rate_limit_per_day: int
    ai_builder_enabled: bool
    max_private_plugins: int
    is_active: bool
    is_verified: bool = False
    created_at: datetime

    # Stats
    user_count: int | None = None
    api_key_count: int | None = None
    model_count: int | None = None

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    """Create user request."""

    organization_id: str
    name: str
    email: str | None = None
    is_admin: bool = False
    can_build_plugins: bool = False


class UserUpdate(BaseModel):
    """Update user request."""

    name: str | None = None
    email: str | None = None
    is_admin: bool | None = None
    can_build_plugins: bool | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    """User response."""

    id: str
    organization_id: str
    name: str
    email: str | None
    is_admin: bool
    can_build_plugins: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class APIKeyCreate(BaseModel):
    """Create API key request."""

    organization_id: str
    user_id: str
    name: str
    description: str | None = None


class APIKeyResponse(BaseModel):
    """API key response."""

    id: str
    organization_id: str
    user_id: str
    name: str
    description: str | None
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    # Only returned on creation
    full_key: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CreditAdjustment(BaseModel):
    """Credit adjustment request."""

    organization_id: str
    amount: int = Field(..., description="Positive to add, negative to subtract")
    reason: str


class AdminPaginatedResponse(BaseModel):
    """Paginated response for admin endpoints."""

    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


class UpdateModelBadgesRequest(BaseModel):
    """Request to update model badges."""

    is_official: bool | None = None
    is_featured: bool | None = None
    is_public: bool | None = None
