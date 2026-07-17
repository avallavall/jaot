"""Pydantic schemas for author notification preference and onboarding API responses."""

from pydantic import BaseModel

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
