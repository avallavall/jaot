"""Pydantic v2 schemas for the cron schedule API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreateRequest(BaseModel):
    """Request body for creating a cron schedule on a trigger."""

    cron_expression: str = Field(
        ...,
        min_length=9,
        max_length=100,
        examples=["0 9 * * 1-5"],
        description="Standard 5-field cron expression (minute hour dom month dow)",
    )
    timezone: str = Field(
        default="UTC",
        max_length=64,
        examples=["America/New_York"],
        description="IANA timezone name",
    )


class ScheduleUpdateRequest(BaseModel):
    """Request body for updating a cron schedule."""

    cron_expression: str | None = Field(
        None,
        min_length=9,
        max_length=100,
        description="Standard 5-field cron expression",
    )
    timezone: str | None = Field(
        None,
        max_length=64,
        description="IANA timezone name",
    )
    is_enabled: bool | None = None


class ScheduleResponse(BaseModel):
    """Response schema for a cron schedule."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trigger_id: str
    cron_expression: str
    timezone: str
    is_enabled: bool
    consecutive_failures: int
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CronValidationResponse(BaseModel):
    """Response schema for cron expression validation."""

    valid: bool
    next_runs: list[str]
