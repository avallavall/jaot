"""Pydantic v2 schemas for the trigger API (CRUD, fire, and run history)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


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
    # Exactly one pair, enforced below. A trigger used to accept only the builder
    # pair, and the studio never creates a builder document — so nothing built in
    # the studio could be automated.
    document_id: str | None = Field(
        default=None, description="Builder document this trigger is attached to"
    )
    version_id: str | None = Field(default=None, description="Pinned model version snapshot ID")
    model_project_id: str | None = Field(
        default=None, description="Studio model project this trigger is attached to"
    )
    model_project_version_id: str | None = Field(
        default=None, description="Pinned committed version of that project"
    )
    override_schema: list[OverrideFieldSchema] | None = Field(
        default=None,
        description="Declared override fields. If None, any key is accepted.",
    )
    webhook_url: HttpUrl = Field(..., description="URL to receive trigger completion events")
    webhook_secret: str | None = Field(
        default=None, description="Secret for signing outbound webhook payloads"
    )
    workspace_id: str | None = Field(default=None, description="Workspace this run belongs to")

    @model_validator(mode="after")
    def exactly_one_model_source(self) -> "TriggerCreate":
        """A trigger fires one model. Refuse ambiguity rather than pick for them.

        Rejecting both-at-once matters as much as rejecting neither: with both
        set, which model runs would be decided by a precedence rule the caller
        never saw, and they would find out from the solve.
        """
        has_document = bool(self.document_id and self.version_id)
        has_project = bool(self.model_project_id and self.model_project_version_id)
        if has_document == has_project:
            raise ValueError(
                "Provide either document_id + version_id, or "
                "model_project_id + model_project_version_id — exactly one pair."
            )
        if self.document_id and not self.version_id:
            raise ValueError("document_id requires version_id")
        if self.model_project_id and not self.model_project_version_id:
            raise ValueError("model_project_id requires model_project_version_id")
        return self


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
    # Exactly one pair is populated; `source` says which without the reader
    # having to infer it from nulls.
    source: Literal["document", "project"] = Field(
        ..., description="Which kind of model this fires"
    )
    document_id: str | None
    version_id: str | None
    model_project_id: str | None = None
    model_project_version_id: str | None = None
    # The id alone told the reader nothing. The name comes from the studio
    # project or the builder document, whichever pair is set, and is None when
    # that model has been deleted.
    model_name: str | None = Field(default=None, description="Name of the model this trigger fires")
    has_active_schedule: bool = Field(
        default=False,
        description="Whether an enabled cron schedule exists for this trigger",
    )
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
    execution_time_ms: int | None
    webhook_delivered: bool | None
    webhook_attempts: int
    created_at: datetime
    completed_at: datetime | None


class TriggerToggleRequest(BaseModel):
    """Request body for enabling or disabling a trigger."""

    enabled: bool = Field(..., description="True to enable the trigger, False to disable it")
