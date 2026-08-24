"""Pydantic schemas for the author area: listings, reviews, notification prefs, onboarding."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

# --- Notification Preferences ---


class NotificationPreferenceEntry(BaseModel):
    """Single notification preference entry."""

    event_type: str  # "review" (money event types left with ADR-008)
    channel: str  # "in_app" or "email"
    enabled: bool


class NotificationPreferencesResponse(BaseModel):
    """All notification preferences for a user (event types x 2 channels)."""

    preferences: list[NotificationPreferenceEntry]


class UpdatePreferenceRequest(BaseModel):
    """Request to update a single notification preference."""

    event_type: str
    channel: str
    enabled: bool


# --- Onboarding ---


class OnboardingStep(BaseModel):
    """A single onboarding checklist step."""

    key: str
    completed: bool
    link: str


class OnboardingStatusResponse(BaseModel):
    """Onboarding checklist status for an author."""

    steps: list[OnboardingStep]
    all_complete: bool


# --- What I publish ---


class AuthorListingRow(BaseModel):
    """One of my marketplace listings, with the state and rollups the panel shows."""

    model_project_id: str
    display_name: str
    short_description: str | None = None
    category: str
    # draft | published | unpublished — see ModelProjectListing.status.
    status: str
    is_public: bool
    version: str
    logo_url: str | None = None
    #: Counted, not stored — the listing row carries no such column, so the
    #: default is what validating a row gives you and the service fills it in.
    total_activations: int = 0
    total_executions: int
    avg_rating: float | None = None
    success_rate: float | None = None
    published_at: datetime | None = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Reviews received ---


class AuthorReviewRow(BaseModel):
    """A review left on one of my models."""

    id: str
    model_project_id: str
    model_display_name: str
    rating: int
    title: str | None = None
    comment: str | None = None
    reviewer_name: str | None = None
    created_at: datetime


class AuthorReviewsResponse(BaseModel):
    """Reviews across all of my listings, newest first."""

    reviews: list[AuthorReviewRow]
    total: int
