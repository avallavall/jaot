"""Pydantic v2 schemas for the ModelProject API (P1a).

A ModelProject is the first-class model entity: a mutable HEAD draft plus an
append-only list of immutable, commit-grade versions.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    """Create a new (blank) ModelProject."""

    name: str = Field(default="Untitled Project", max_length=255)
    description: str | None = None
    workspace_id: str | None = None


class ProjectMetaUpdate(BaseModel):
    """Patch a project's metadata (name / description / status)."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class DraftUpdate(BaseModel):
    """Replace the mutable HEAD draft. Optimistic concurrency via the
    ``If-Match`` header (``draft_lock_version``), handled in the route."""

    model_json_: dict[str, Any] | None = Field(default=None, alias="model_json")
    canvas_json: dict[str, Any] | None = None
    dsl_source: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class CommitRequest(BaseModel):
    """Commit the current draft as an immutable version.

    ``summary`` ("What changed?") is required and non-empty; ``body`` ("Why?")
    is optional context.
    """

    summary: str = Field(max_length=500)
    body: str | None = None

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("commit summary must not be empty")
        return v.strip()


class DatasetCreate(BaseModel):
    """Create a named dataset ("scenario") — set members + param values for the
    project's parametric JModel. ``data_json`` shape and size are validated in the
    service against :class:`~app.domains.dsl.JModelData` (422 on violation)."""

    name: str = Field(max_length=255)
    description: str | None = None
    data_json: dict[str, Any]

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("dataset name must not be empty")
        return v.strip()


class DatasetUpdate(BaseModel):
    """Patch a dataset (only the provided fields change)."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    data_json: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.strip():
            raise ValueError("dataset name must not be empty")
        return v.strip()


class DatasetSummary(BaseModel):
    """Compact dataset row for the list view (no values — they can be MBs)."""

    id: str
    model_project_id: str
    name: str
    description: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetRead(DatasetSummary):
    """Full dataset view (values included — datasets are edited as a whole)."""

    data_json: dict[str, Any]


class VersionSummary(BaseModel):
    """Compact view of a committed version (for the project header / timeline)."""

    id: str
    sequence: int
    commit_summary: str
    problem_class: str | None = None
    created_by: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VersionRead(VersionSummary):
    """Full version snapshot."""

    model_project_id: str
    parent_version_id: str | None = None
    commit_body: str | None = None
    content_hash: str
    model_json: dict[str, Any]
    canvas_json: dict[str, Any] | None = None
    dsl_source: str | None = None
    stats_json: dict[str, Any] | None = None


class ProjectRead(BaseModel):
    """Full project view: metadata + the current draft + the committed HEAD."""

    id: str
    organization_id: str
    workspace_id: str | None = None
    name: str
    description: str | None = None
    status: str
    source_type: str | None = None
    source_ref: str | None = None
    current_version_id: str | None = None
    committed_count: int
    draft_model_json: dict[str, Any] | None = None
    draft_canvas_json: dict[str, Any] | None = None
    draft_dsl_source: str | None = None
    draft_content_hash: str | None = None
    draft_lock_version: int
    draft_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectListItem(BaseModel):
    """Compact project row for the list view."""

    id: str
    name: str
    description: str | None = None
    status: str
    source_type: str | None = None
    current_version_id: str | None = None
    committed_count: int
    updated_at: datetime
    # Attribution — the list is org-wide, so the row shows whose model it is.
    created_by: str | None = None
    created_by_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectExecutionItem(BaseModel):
    """Compact execution row for SERVER-DERIVED solve reconciliation (§14).

    Carries exactly what the workspace needs to RECONCILE a solve from the
    server when it opens — independent of browser memory, so a running solve
    survives navigation, reload, a duplicated tab, a new device, or power loss:

    * ``status`` + ``is_async`` + ``celery_task_id`` → re-attach a still-running
      async solve (resume polling + the live WebSocket from where it is).
    * terminal ``status`` + ``objective_value`` + ``completed_at`` → surface the
      last run ("resuelta · objetivo X · hace Ys") instead of a blank panel.
    """

    id: str
    status: str
    is_async: bool
    celery_task_id: str | None = None
    solver_name: str | None = None
    objective_value: float | None = None
    model_project_version_id: str | None = None
    # §8/S1: which named dataset the run was compiled against. `dataset_name`
    # is a snapshot — it survives dataset deletion (S3 compares runs by dataset).
    dataset_id: str | None = None
    dataset_name: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DiffEntry(BaseModel):
    """One changed element in a version-to-version structural diff."""

    kind: str  # "variable" | "constraint" | "objective"
    change: str  # "added" | "removed" | "modified"
    name: str
    detail: str | None = None


class VersionDiff(BaseModel):
    """Structural diff between two ModelProjectVersions."""

    from_version_id: str
    to_version_id: str
    entries: list[DiffEntry]
    objective_changed: bool = False
