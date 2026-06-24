"""Pydantic schemas for verification request API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class VerificationRequestResponse(BaseModel):
    """Verification request details for the requesting org."""

    id: str
    organization_id: str
    status: str
    admin_note: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None


class AdminVerificationEntry(BaseModel):
    """Verification request entry for admin review queue."""

    id: str
    organization_id: str
    org_name: str
    profile_completeness: float  # 0.0 to 1.0
    models_published: int
    member_since: str  # ISO date string
    status: str
    created_at: datetime


class AdminVerificationDecision(BaseModel):
    """Admin decision on a verification request."""

    status: Literal["approved", "rejected"]
    admin_note: str | None = None
