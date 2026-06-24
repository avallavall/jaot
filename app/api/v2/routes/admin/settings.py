"""Admin platform settings endpoints.

Provides full CRUD for runtime platform settings with audit trail.
All endpoints are protected by the admin router's ``get_admin_user`` dependency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models.platform_setting_audit import PlatformSettingAudit
from app.schemas.admin_settings import (
    AuditEntryResponse,
    AuditLogResponse,
    PlanTiersResponse,
    PlanTiersUpdateRequest,
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
from app.shared.db.base import get_db

router = APIRouter(prefix="/settings", tags=["admin-settings"])


@router.get("/commission")
async def get_commission_rate(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Get the current marketplace commission rate."""
    rate = PlatformSettingsService.get_commission_rate(db)
    return {
        "commission_rate": rate,
        "key": "marketplace_commission_rate",
    }


@router.put("/commission")
async def update_commission_rate(
    rate: float = Query(..., ge=0.0, le=0.50, description="Commission rate (0.0 to 0.50)"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update the marketplace commission rate.

    Rate must be between 0.0 (0%) and 0.50 (50%).
    """
    PlatformSettingsService.set(db, "marketplace_commission_rate", str(rate), updated_by="admin")
    db.commit()
    return {
        "commission_rate": rate,
        "key": "marketplace_commission_rate",
        "updated": True,
    }


@router.get("/registry", response_model=SettingsRegistryResponse)
async def get_registry() -> SettingsRegistryResponse:
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
async def get_values(
    category: str | None = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
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
async def update_values(
    body: SettingsUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
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


@router.post("/reset/{key}")
async def reset_setting(
    key: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Reset a single setting to its registry default value.

    ADMIN-03: Logs the reset in audit trail.
    ADMIN-04: Writes registry default back to DB row.
    """
    user = getattr(request.state, "user", None)
    changed_by = getattr(user, "email", "admin") if user else "admin"

    audit = PlatformSettingsService.reset_to_default(db, key, changed_by=changed_by)
    db.commit()

    if audit is None:
        return {"key": key, "reset": False, "reason": "Key not found or is readonly"}

    new_value = PlatformSettingsService.get(db, key)
    return {"key": key, "reset": True, "default_value": new_value}


@router.get("/audit", response_model=AuditLogResponse)
async def get_audit_log(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    category: str | None = Query(None, description="Filter by category"),
    changed_by: str | None = Query(None, description="Filter by admin user"),
    from_date: datetime | None = Query(None, description="Filter from date"),
    to_date: datetime | None = Query(None, description="Filter to date"),
    db: Session = Depends(get_db),
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


@router.get("/plans", response_model=PlanTiersResponse)
async def get_plan_tiers(
    db: Session = Depends(get_db),
) -> PlanTiersResponse:
    """Return all plan tier configurations.

    Returns all 4 plans (free, starter, pro, business) with 9 fields each.
    """
    plans = PlatformSettingsService.get_plan_tiers(db)
    return PlanTiersResponse(plans=plans)


@router.put("/plans", response_model=PlanTiersResponse)
async def update_plan_tiers(
    body: PlanTiersUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> PlanTiersResponse:
    """Update plan tier configurations.

    Validates each field against registry constraints (per-field only).
    """
    user = getattr(request.state, "user", None)
    changed_by = getattr(user, "email", "admin") if user else "admin"

    errors: dict[str, str] = {}
    for tier, fields in body.plans.items():
        for field, value in fields.items():
            key = f"plan_{tier}_{field}"
            if key not in REGISTRY_BY_KEY:
                errors[key] = f"Unknown plan field: {tier}.{field}"
                continue
            ok, err = PlatformSettingsService.validate_value(key, value)
            if not ok:
                errors[key] = err or "Validation failed"

    if not errors:
        PlatformSettingsService.set_plan_tiers(db, body.plans, changed_by=changed_by)
        db.commit()

    plans = PlatformSettingsService.get_plan_tiers(db)
    return PlanTiersResponse(plans=plans)
