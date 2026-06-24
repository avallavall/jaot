"""GDPR compliance schemas."""

from pydantic import BaseModel, Field


class AccountDeleteRequest(BaseModel):
    """Request to delete user account (right to erasure)."""

    password: str
    confirmation: str = Field(..., pattern="^DELETE$")  # Must type "DELETE"
