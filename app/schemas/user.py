"""User schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema."""

    email: EmailStr
    name: str = Field(..., min_length=2, max_length=255)


class UserCreate(UserBase):
    """Schema for creating a user."""

    password: str = Field(..., min_length=8)
    organization_id: str
    is_admin: bool = False


class UserUpdate(BaseModel):
    """Schema for updating a user."""

    email: EmailStr | None = None
    name: str | None = Field(None, min_length=2, max_length=255)
    password: str | None = Field(None, min_length=8)
    is_admin: bool | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    """User response schema."""

    id: str
    email: str
    name: str
    organization_id: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    last_login: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserPublicProfile(BaseModel):
    """Public user profile (visible to anyone)."""

    id: str
    name: str
    slug: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    organization_name: str | None = None
    created_at: datetime

    # Public stats
    published_models_count: int = 0
    total_model_executions: int = 0

    model_config = ConfigDict(from_attributes=True)
