"""Pydantic schemas for feedback endpoints (rating + admin analytics)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

VALID_ZONES = {"builder", "solver", "llm", "results", "dashboard", "models"}


class RatingCreate(BaseModel):
    """Request body for creating/updating a formulation rating."""

    rating: Literal["up", "down"]
    comment: str | None = None
    zone: str
    formulation_snapshot: dict[str, Any] | None = None

    @field_validator("zone")
    @classmethod
    def validate_zone(cls, v: str) -> str:
        if v not in VALID_ZONES:
            raise ValueError(
                f"Invalid zone '{v}'. Must be one of: {', '.join(sorted(VALID_ZONES))}"
            )
        return v


class RatingResponse(BaseModel):
    """Response for a single formulation rating."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    user_id: str
    organization_id: str
    rating: str
    comment: str | None = None
    zone: str
    formulation_snapshot: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class FeedbackListResponse(BaseModel):
    """Paginated list of feedback ratings."""

    items: list[RatingResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ZoneStats(BaseModel):
    """Aggregate statistics for a single zone."""

    zone: str
    total: int
    up: int
    down: int


class DailyTrend(BaseModel):
    """Daily feedback trend entry."""

    date: str  # ISO date string YYYY-MM-DD
    total: int
    up: int
    down: int


class FeedbackStatsResponse(BaseModel):
    """Aggregate feedback statistics for admin dashboard."""

    total: int
    up: int
    down: int
    avg_rating: float  # thumbs-up ratio 0.0-1.0 (up/total; 0.0 when total is 0)
    by_zone: list[ZoneStats]
    daily_trend: list[DailyTrend]  # sorted ascending by date
    period_days: int
