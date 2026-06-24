"""Pydantic schemas for the visual model builder CRUD API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BuilderDocumentCreate(BaseModel):
    """Request body for creating a new builder document."""

    name: str = Field(default="Untitled Model", max_length=255)


class BuilderDocumentUpdate(BaseModel):
    """Request body for partial update of a builder document.

    All fields are optional; only provided fields are applied.
    Use model.model_dump(exclude_unset=True) to get only the set fields.
    """

    name: str | None = Field(default=None, max_length=255)
    canvas_json: dict[str, Any] | None = None
    model_json: dict[str, Any] | None = None


class BuilderDocumentResponse(BaseModel):
    """Full representation of a builder document returned by GET/{id} and mutations."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    created_by: str | None
    name: str
    canvas_json: dict[str, Any]
    model_json: dict[str, Any] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BuilderDocumentListResponse(BaseModel):
    """Slim representation used in list endpoints (omits heavy JSON fields)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime
    updated_at: datetime
