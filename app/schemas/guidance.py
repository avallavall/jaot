"""Guidance system schemas for skill level and wizard state."""

from enum import Enum

from pydantic import BaseModel, Field


class SkillLevel(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    expert = "expert"


class GuidanceResponse(BaseModel):
    """Response schema for guidance state."""

    skill_level: SkillLevel
    wizard_step: int  # 0=not started, 1-4=in progress, 5=completed
    wizard_dismissed: bool
    wizard_completed: bool


class GuidanceUpdate(BaseModel):
    """Partial update schema for guidance state."""

    skill_level: SkillLevel | None = None
    wizard_step: int | None = Field(None, ge=0, le=5)
    wizard_dismissed: bool | None = None
    wizard_completed: bool | None = None
