"""Pydantic v2 schemas for the trigger API (CRUD, fire, and run history)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class OverrideFieldSchema(BaseModel):
    """Schema definition for a single override field on a trigger.

    Callers of /fire supply values for declared fields in override_data.
    The model_field_path is used by TriggerService.apply_overrides() to
    locate the target field in the model JSON.
    """

    name: str = Field(..., description="Unique name for this override field")
    type: Literal["string", "number", "integer", "boolean", "array", "object"] = Field(
        ..., description="JSON Schema-compatible type"
    )
    model_field_path: str = Field(
        ..., description="Dot-separated path into model_json where this value is placed"
    )
    default: Any | None = Field(default=None, description="Default value if not supplied")
    required: bool = Field(default=False, description="Whether callers must supply this field")
    description: str | None = Field(default=None, description="Human-readable description")


class TriggerCreate(BaseModel):
    """Request body for creating a new SolveTrigger."""

    name: str = Field(..., min_length=1, max_length=255, description="Trigger display name")
    description: str | None = Field(default=None, description="Optional longer description")
    document_id: str = Field(..., description="Builder document this trigger is attached to")
    version_id: str = Field(..., description="Pinned model version snapshot ID")
    override_schema: list[OverrideFieldSchema] | None = Field(
        default=None,
        description="Declared override fields. If None, any key is accepted.",
    )
    webhook_url: HttpUrl = Field(..., description="URL to receive trigger completion events")
    webhook_secret: str | None = Field(
        default=None, description="Secret for signing outbound webhook payloads"
    )
    workspace_id: str | None = Field(default=None, description="Workspace to deduct credits from")


class TriggerUpdate(BaseModel):
    """Request body for partially updating a SolveTrigger.

    version_id is intentionally excluded — it is locked at creation time.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None)
    override_schema: list[OverrideFieldSchema] | None = Field(default=None)
    webhook_url: HttpUrl | None = Field(default=None)
    webhook_secret: str | None = Field(default=None)


class TriggerResponse(BaseModel):
    """Full trigger representation — trigger_secret is NEVER included.

    trigger_secret_prefix shows the first 8 chars so clients can identify
    which secret they used when it's time to rotate it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    created_by: str | None
    name: str
    description: str | None
    document_id: str
    version_id: str
    trigger_secret_prefix: str = Field(
        ..., description="First 8 characters of the SHA-256 hash for identification"
    )
    override_schema: list[dict[str, Any]] | None
    webhook_url: str
    webhook_secret_prefix: str | None
    workspace_id: str | None = None
    is_enabled: bool
    total_runs: int
    last_fired_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TriggerCreateResponse(TriggerResponse):
    """Response returned only on trigger creation.

    Includes the plaintext trigger_secret — this is the ONLY time it is
    shown. The caller must store it securely.
    """

    trigger_secret: str = Field(..., description="Plaintext trigger secret — shown once only")


class TriggerFireRequest(BaseModel):
    """Request body for firing a trigger.

    The trigger_secret can be supplied either in this body field OR via
    the Authorization: Bearer <secret> header. The header takes priority.
    """

    override_data: dict[str, Any] | None = Field(
        default=None, description="Key-value pairs to override in the model inputs"
    )
    trigger_secret: str | None = Field(
        default=None,
        description="Trigger secret (alternative to Authorization header)",
    )


class TriggerFireResponse(BaseModel):
    """Response returned immediately when a trigger is fired.

    The run is created synchronously; the solve is queued asynchronously.
    Poll GET /{trigger_id}/runs/{run_id} for final status.
    """

    run_id: str
    status: str = "pending"


class TriggerRunResponse(BaseModel):
    """Full run representation including result_data and override_data."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trigger_id: str
    organization_id: str
    override_data: dict[str, Any] | None
    source: str
    status: str
    execution_id: str | None
    result_data: dict[str, Any] | None
    error_message: str | None
    credits_consumed: int
    execution_time_ms: int | None
    webhook_delivered: bool | None
    webhook_attempts: int
    created_at: datetime
    completed_at: datetime | None


class TriggerToggleRequest(BaseModel):
    """Request body for enabling or disabling a trigger."""

    enabled: bool = Field(..., description="True to enable the trigger, False to disable it")
