"""Profile schemas for organizations, users, and reviews."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrganizationPublicProfile(BaseModel):
    """Public profile of an organization."""

    id: str
    name: str
    slug: str | None = None
    bio: str | None = None
    logo_url: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    is_verified: bool = False
    created_at: datetime
    # Stats
    total_models_published: int = 0
    total_activations: int = 0
    total_executions: int = 0
    total_reviews: int = 0
    avg_rating: float | None = None

    model_config = ConfigDict(from_attributes=True)


class UserPublicProfile(BaseModel):
    """Public profile of a user."""

    id: str
    name: str
    display_name: str | None = None
    slug: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    organization_id: str
    organization_name: str | None = None
    organization_verified: bool = False
    created_at: datetime
    # Stats
    total_reviews: int = 0
    avg_rating_given: float | None = None

    model_config = ConfigDict(from_attributes=True)


class ReviewResponse(BaseModel):
    """Response for a model review."""

    id: str
    catalog_id: str
    user_id: str
    user_name: str
    user_avatar_url: str | None = None
    organization_name: str | None = None
    rating: int
    title: str | None = None
    comment: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewListResponse(BaseModel):
    """Paginated list of reviews."""

    items: list[ReviewResponse]
    total: int
    page: int
    page_size: int
    avg_rating: float | None = None
    rating_distribution: dict[int, int]  # {1: count, 2: count, ...}


class CreateReviewRequest(BaseModel):
    """Request to create a review."""

    rating: int = Field(..., ge=1, le=5)
    title: str | None = Field(None, max_length=200)
    comment: str | None = Field(None, max_length=2000)


class UpdateOrgProfileRequest(BaseModel):
    """Request to update organization profile."""

    slug: str | None = Field(None, max_length=100)
    bio: str | None = Field(None, max_length=1000)
    logo_url: str | None = Field(None, max_length=500)
    website_url: str | None = Field(None, max_length=500)
    linkedin_url: str | None = Field(None, max_length=500)
    twitter_url: str | None = Field(None, max_length=500)
    is_public_profile: bool | None = None


class UpdateUserProfileRequest(BaseModel):
    """Request to update user profile."""

    slug: str | None = Field(None, max_length=100)
    display_name: str | None = Field(None, max_length=100)
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=500)
    linkedin_url: str | None = Field(None, max_length=500)
    twitter_url: str | None = Field(None, max_length=500)
    is_public_profile: bool | None = None
    locale: str | None = Field(None, max_length=10)


class ReportRequest(BaseModel):
    """Request to report a review."""

    reason: str = Field(..., max_length=500)


class UserReviewResponse(BaseModel):
    """Review written by a user."""

    id: str
    catalog_id: str
    model_name: str
    rating: int
    title: str | None = None
    comment: str | None = None
    created_at: datetime
