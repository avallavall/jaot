"""Pydantic schemas for the model version history API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelVersionListItem(BaseModel):
    """Slim representation of a version used in list endpoints.

    canvas_json is intentionally omitted to reduce payload size — potentially
    hundreds of KB per version for large canvases.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    organization_id: str
    change_summary: str
    is_named: bool
    version_name: str | None
    version_description: str | None
    sequence: int
    created_at: datetime


class ModelVersionResponse(BaseModel):
    """Full version representation including canvas_json and model_json.

    Returned by single-version GET and by create/promote/restore operations.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    organization_id: str
    canvas_json: dict[str, Any]
    model_json: dict[str, Any] | None = None
    change_summary: str
    is_named: bool
    version_name: str | None
    version_description: str | None
    sequence: int
    created_at: datetime


class CreateCheckpointRequest(BaseModel):
    """Request body for creating an unnamed version checkpoint."""

    canvas_json: dict[str, Any] = Field(
        ...,
        description="Current React Flow canvas state to snapshot",
    )


class PromoteVersionRequest(BaseModel):
    """Request body for promoting an unnamed checkpoint to a named version."""

    version_name: str = Field(..., min_length=1, max_length=255)
    version_description: str | None = Field(default=None, max_length=2000)


class RestoreRequest(BaseModel):
    """Request body for restoring a previous version.

    The caller must provide their current canvas state so the service can
    create a safety checkpoint before applying the target version.
    """

    current_canvas_json: dict[str, Any] = Field(
        ...,
        description="Current canvas state to checkpoint before restoring",
    )


class RestoreResponse(BaseModel):
    """Response after a successful restore operation."""

    checkpoint_id: str = Field(
        ...,
        description="ID of the safety checkpoint created from the pre-restore state",
    )
    document: dict[str, Any] = Field(
        ...,
        description="Updated document with canvas_json set to the restored version",
    )
