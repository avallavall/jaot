"""Organization schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OrganizationBase(BaseModel):
    """Base organization schema."""

    name: str = Field(..., min_length=2, max_length=255)
    slug: str | None = None
    description: str | None = None
    website: str | None = None


class OrganizationCreate(OrganizationBase):
    """Schema for creating an organization."""

    owner_email: EmailStr
    owner_name: str
    owner_password: str = Field(..., min_length=8)
    plan: str = "free"


class OrganizationUpdate(BaseModel):
    """Schema for updating an organization."""

    name: str | None = Field(None, min_length=2, max_length=255)
    slug: str | None = None
    description: str | None = None
    website: str | None = None
    plan: str | None = None
    is_active: bool | None = None
    credits_balance: int | None = None


class OrganizationResponse(BaseModel):
    """Organization response schema."""

    id: str
    name: str
    slug: str | None = None
    description: str | None = None
    website: str | None = None
    plan: str
    is_active: bool
    credits_balance: int
    credits_earned: int
    credits_used_month: int
    created_at: datetime
    updated_at: datetime | None = None

    # Stats
    total_users: int | None = None
    total_models: int | None = None
    total_executions: int | None = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationPublicProfile(BaseModel):
    """Public organization profile (visible to anyone)."""

    id: str
    name: str
    slug: str | None = None
    description: str | None = None
    website: str | None = None
    created_at: datetime

    # Public stats
    published_models_count: int = 0
    total_model_executions: int = 0
    avg_model_rating: float | None = None

    model_config = ConfigDict(from_attributes=True)
