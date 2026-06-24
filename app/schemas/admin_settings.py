"""Pydantic schemas for admin settings API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SettingDefinitionResponse(BaseModel):
    """A single setting entry from the registry."""

    key: str
    label: str
    description: str
    category: str
    setting_type: str
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None
    is_secret: bool = False
    is_readonly: bool = False


class SettingsRegistryResponse(BaseModel):
    """Full registry grouped by category."""

    categories: dict[str, list[SettingDefinitionResponse]]


class SettingValueResponse(BaseModel):
    """A single setting's current value with metadata."""

    value: str
    env_default: str | None = None
    is_modified: bool = False
    last_changed_by: str | None = None
    last_changed_at: str | None = None
    source: str | None = None


class SettingsValuesResponse(BaseModel):
    """All setting values."""

    settings: dict[str, SettingValueResponse]


class SettingsUpdateRequest(BaseModel):
    """Batch update request."""

    updates: dict[str, str]


class SettingsUpdateResponse(BaseModel):
    """Result of a batch update."""

    updated: list[str]
    errors: dict[str, str]


class AuditEntryResponse(BaseModel):
    """A single audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    setting_key: str
    old_value: str | None = None
    new_value: str | None = None
    changed_by: str
    changed_at: datetime
    category: str | None = None


class AuditLogResponse(BaseModel):
    """Paginated audit log."""

    items: list[AuditEntryResponse]
    total: int
    page: int
    page_size: int


class PlanTiersResponse(BaseModel):
    """All plan tier configurations."""

    plans: dict[str, dict[str, str]]


class PlanTiersUpdateRequest(BaseModel):
    """Update plan tier configurations."""

    plans: dict[str, dict[str, str]]
