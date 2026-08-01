"""Admin platform settings endpoints.

Provides full CRUD for runtime platform settings with audit trail.
All endpoints are protected by the admin router's ``get_admin_user`` dependency.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request
from sqlalchemy import desc, func

from app.api.deps import DBSession
from app.models.platform_setting_audit import PlatformSettingAudit
from app.schemas.admin import SettingResetResponse
from app.schemas.admin_settings import (
    AuditEntryResponse,
    AuditLogResponse,
    SettingDefinitionResponse,
    SettingsRegistryResponse,
    SettingsUpdateRequest,
    SettingsUpdateResponse,
    SettingsValuesResponse,
    SettingValueResponse,
)
from app.services.platform_settings_service import PlatformSettingsService
from app.services.settings_registry import (
    REGISTRY_BY_CATEGORY,
    REGISTRY_BY_KEY,
    SettingCategory,
)

router = APIRouter(prefix="/settings", tags=["admin-settings"])


@router.get("/registry", response_model=SettingsRegistryResponse)
def get_registry() -> SettingsRegistryResponse:
    """Return full settings registry grouped by category.

    ADMIN-01: Admin can view all runtime-configurable settings grouped by category.
    """
    categories: dict[str, list[SettingDefinitionResponse]] = {}

    for category, definitions in REGISTRY_BY_CATEGORY.items():
        cat_key = category.value if isinstance(category, SettingCategory) else category
        categories[cat_key] = [
            SettingDefinitionResponse(
                key=d.key,
                label=d.label,
                description=d.description,
                category=cat_key,
                setting_type=d.setting_type.value,
                min_value=d.min_value,
                max_value=d.max_value,
                unit=d.unit,
                is_secret=d.is_secret,
                is_readonly=d.is_readonly,
            )
            for d in definitions
        ]

    return SettingsRegistryResponse(categories=categories)


@router.get("/values", response_model=SettingsValuesResponse)
def get_values(
    db: DBSession,
    category: str | None = Query(None, description="Filter by category"),
) -> SettingsValuesResponse:
    """Return all current setting values (or filtered by category).

    ADMIN-01: Secret values are masked as ``****``.
    """
    all_values = PlatformSettingsService.get_all_values(db)

    if category:
        # Filter to only keys in the requested category
        try:
            cat_enum = SettingCategory(category)
        except ValueError:
            # Unknown category — return empty
            return SettingsValuesResponse(settings={})

        category_keys = {d.key for d in REGISTRY_BY_CATEGORY.get(cat_enum, [])}
        filtered = {k: v for k, v in all_values.items() if k in category_keys}
    else:
        filtered = all_values

    settings = {
        key: SettingValueResponse(
            value=data["value"],
            env_default=data["default_value"],
            is_modified=data["is_modified"],
            last_changed_by=data["last_changed_by"],
            last_changed_at=data["last_changed_at"],
            source=data.get("source"),
        )
        for key, data in filtered.items()
    }

    return SettingsValuesResponse(settings=settings)


@router.put("/values", response_model=SettingsUpdateResponse)
def update_values(
    body: SettingsUpdateRequest,
    request: Request,
    db: DBSession,
) -> SettingsUpdateResponse:
    """Batch update settings with validation and audit trail.

    ADMIN-02: Validates each value against registry constraints.
    ADMIN-03: Creates audit records for every change.
    """
    user = getattr(request.state, "user", None)
    changed_by = getattr(user, "email", "admin") if user else "admin"

    valid_updates: dict[str, str] = {}
    errors: dict[str, str] = {}

    for key, value in body.updates.items():
        definition = REGISTRY_BY_KEY.get(key)
        if not definition:
            errors[key] = f"Unknown setting key: {key}"
            continue
        if definition.is_readonly:
            # Silently skip readonly keys (per spec)
            continue

        ok, err = PlatformSettingsService.validate_value(key, value)
        if not ok:
            errors[key] = err or "Validation failed"
        else:
            valid_updates[key] = value

    audits = PlatformSettingsService.bulk_set(db, valid_updates, changed_by=changed_by)
    db.commit()

    updated_keys = [a.setting_key for a in audits]
    return SettingsUpdateResponse(updated=updated_keys, errors=errors)


@router.post("/reset/{key}", response_model=SettingResetResponse)
def reset_setting(
    key: str,
    request: Request,
    db: DBSession,
) -> SettingResetResponse:
    """Reset a single setting to its registry default value.

    ADMIN-03: Logs the reset in audit trail.
    ADMIN-04: Writes registry default back to DB row.
    """
    user = getattr(request.state, "user", None)
    changed_by = getattr(user, "email", "admin") if user else "admin"

    audit = PlatformSettingsService.reset_to_default(db, key, changed_by=changed_by)
    db.commit()

    if audit is None:
        return SettingResetResponse(key=key, reset=False, reason="Key not found or is readonly")

    new_value = PlatformSettingsService.get(db, key)
    return SettingResetResponse(key=key, reset=True, default_value=new_value)


@router.get("/audit", response_model=AuditLogResponse)
def get_audit_log(
    db: DBSession,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    category: str | None = Query(None, description="Filter by category"),
    changed_by: str | None = Query(None, description="Filter by admin user"),
    from_date: datetime | None = Query(None, description="Filter from date"),
    to_date: datetime | None = Query(None, description="Filter to date"),
) -> AuditLogResponse:
    """Return paginated audit log with optional filters.

    ADMIN-03: All setting changes logged in audit trail.
    """
    query = db.query(PlatformSettingAudit)

    if category:
        query = query.filter(PlatformSettingAudit.category == category)
    if changed_by:
        query = query.filter(PlatformSettingAudit.changed_by == changed_by)
    if from_date:
        query = query.filter(PlatformSettingAudit.changed_at >= from_date)
    if to_date:
        query = query.filter(PlatformSettingAudit.changed_at <= to_date)

    total = query.with_entities(func.count(PlatformSettingAudit.id)).scalar() or 0

    items = (
        query.order_by(desc(PlatformSettingAudit.changed_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return AuditLogResponse(
        items=[AuditEntryResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# GET/PUT /plans are gone with the four tiers. The instance limits are seven
# ordinary settings in the `limits` category now, so the generic values
# endpoints above edit them — the tier table and the loose fields used to render
# the SAME 28 keys twice on one tab, with two different editors.
