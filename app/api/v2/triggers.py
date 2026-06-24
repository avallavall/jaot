"""Trigger CRUD, fire, and run history endpoints.

Routes are mounted at /api/v2/triggers (registered in router.py).

Authentication model:
  - CRUD endpoints (GET, POST, PATCH, DELETE) require CurrentUser + CurrentOrg
    via standard API key auth (request.state populated by AuthMiddleware).
  - The /fire endpoint is per-trigger secret authenticated. No org API key
    is needed — callers supply the trigger_secret via Authorization: Bearer
    header or request body.
  - All trigger paths are in PUBLIC_ENDPOINTS_PREFIX in auth_middleware.py so
    the global API key middleware skips them. The CRUD endpoints still enforce
    auth via dependency injection (raise 401 if no user in request.state).
"""

import hashlib
import logging
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import desc

from app.api.deps import (
    CurrentOrg,
    CurrentUser,
    DBSession,
    OptionalRequireEditor,
    OptionalRequireViewer,
)
from app.models.audit_log import AuditAction
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.models.trigger import SolveTrigger, TriggerRun
from app.schemas.trigger import (
    TriggerCreate,
    TriggerCreateResponse,
    TriggerFireRequest,
    TriggerFireResponse,
    TriggerResponse,
    TriggerRunResponse,
    TriggerToggleRequest,
    TriggerUpdate,
)
from app.services import trigger_service
from app.services.audit_service import log_action
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.shared.utils.pagination import PaginatedResponse, create_paginated_response, paginate_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/triggers", tags=["triggers"])


def _get_trigger_or_404(db: DBSession, trigger_id: str, org_id: str) -> SolveTrigger:
    """Fetch a trigger owned by the org or raise 404."""
    trigger = (
        db.query(SolveTrigger)
        .filter(
            SolveTrigger.id == trigger_id,
            SolveTrigger.organization_id == org_id,
        )
        .first()
    )
    if not trigger:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trigger not found",
        )
    return trigger


def _get_trigger_public(db: DBSession, trigger_id: str) -> SolveTrigger:
    """Fetch a trigger by ID without org scoping (for the public /fire endpoint)."""
    trigger = db.query(SolveTrigger).filter(SolveTrigger.id == trigger_id).first()
    if not trigger:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trigger not found",
        )
    return trigger


def _hash_secret(plaintext: str) -> str:
    """Return SHA-256 hex digest of a plaintext secret."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _extract_fire_secret(request: Request, body: TriggerFireRequest) -> str | None:
    """Extract trigger secret from Authorization header or request body.

    Authorization: Bearer <secret> takes priority over body.trigger_secret.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :].strip()
    return body.trigger_secret


def _mask_secret(value: str | None, length: int = 8) -> str | None:
    """Return a masked prefix of a secret, or None if absent."""
    if not value:
        return None
    return value[:length] + "..."


def _trigger_to_response(trigger: SolveTrigger) -> dict[str, Any]:
    """Build response dict with masked secret prefixes."""
    return {
        "id": trigger.id,
        "organization_id": trigger.organization_id,
        "created_by": trigger.created_by,
        "name": trigger.name,
        "description": trigger.description,
        "document_id": trigger.document_id,
        "version_id": trigger.version_id,
        "trigger_secret_prefix": _mask_secret(trigger.trigger_secret),
        "override_schema": trigger.override_schema,
        "webhook_url": trigger.webhook_url,
        "webhook_secret_prefix": _mask_secret(trigger.webhook_secret),
        "workspace_id": trigger.workspace_id,
        "is_enabled": trigger.is_enabled,
        "total_runs": trigger.total_runs,
        "last_fired_at": trigger.last_fired_at,
        "created_at": trigger.created_at,
        "updated_at": trigger.updated_at,
    }


@router.post(
    "/",
    response_model=TriggerCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new solve trigger",
)
def create_trigger(
    body: TriggerCreate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor = None,
) -> dict[str, Any]:
    """Create an HTTP event trigger pinned to a specific model version.

    The plaintext trigger_secret is returned ONCE in this response.
    Store it securely — it will not be retrievable again.

    If the pinned version is unnamed, it is automatically promoted to
    a named version to protect it from the retention pruning policy.
    """
    # Verify the document belongs to this org
    doc = (
        db.query(ModelBuilderDocument)
        .filter(
            ModelBuilderDocument.id == body.document_id,
            ModelBuilderDocument.organization_id == org.id,
            ModelBuilderDocument.is_active.is_(True),
        )
        .first()
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Builder document not found",
        )

    # Verify the version belongs to the document
    version = (
        db.query(ModelVersion)
        .filter(
            ModelVersion.id == body.version_id,
            ModelVersion.document_id == body.document_id,
            ModelVersion.organization_id == org.id,
        )
        .first()
    )
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model version not found",
        )

    # Auto-promote unnamed versions to named to protect from pruning
    if not version.is_named:
        version.is_named = True
        version.version_name = f"Pinned for trigger: {body.name}"
        db.flush()

    # Backfill model_json if version was created before the model_json column existed
    if version.model_json is None and doc.model_json is not None:
        version.model_json = doc.model_json
        db.flush()

    plaintext_secret = secrets.token_hex(32)
    secret_hash = _hash_secret(plaintext_secret)

    # Convert HttpUrl to string for storage
    webhook_url_str = str(body.webhook_url)

    now = utcnow()
    override_schema_data = (
        [f.model_dump() for f in body.override_schema] if body.override_schema else None
    )

    trigger = SolveTrigger(
        id=generate_id("trg_"),
        organization_id=org.id,
        created_by=user.id,
        name=body.name,
        description=body.description,
        document_id=body.document_id,
        version_id=body.version_id,
        trigger_secret=secret_hash,
        override_schema=override_schema_data,
        webhook_url=webhook_url_str,
        webhook_secret=body.webhook_secret,
        workspace_id=body.workspace_id,
        is_enabled=True,
        total_runs=0,
        last_fired_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(trigger)
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.TRIGGER_CREATE,
        target_type="trigger",
        target_id=trigger.id,
        target_name=body.name,
    )
    db.commit()
    db.refresh(trigger)

    logger.info("Created trigger %s for org %s", trigger.id, org.id)

    response_data = _trigger_to_response(trigger)
    response_data["trigger_secret"] = plaintext_secret
    return response_data


@router.get(
    "/",
    response_model=list[TriggerResponse],
    summary="List triggers for the current organization",
)
def list_triggers(
    db: DBSession,
    org: CurrentOrg,
    document_id: str | None = Query(default=None, description="Filter by document ID"),
    _ws: OptionalRequireViewer = None,
) -> list[dict[str, Any]]:
    """Return all triggers for the current organization, newest first.

    Optionally filter by document_id.
    """
    query = db.query(SolveTrigger).filter(SolveTrigger.organization_id == org.id)
    if document_id:
        query = query.filter(SolveTrigger.document_id == document_id)

    triggers = query.order_by(desc(SolveTrigger.created_at)).all()
    return [_trigger_to_response(t) for t in triggers]


@router.get(
    "/{trigger_id}",
    response_model=TriggerResponse,
    summary="Get a single trigger",
)
def get_trigger(
    trigger_id: str,
    db: DBSession,
    org: CurrentOrg,
    _ws: OptionalRequireViewer = None,
) -> dict[str, Any]:
    """Return a single trigger by ID (must belong to current organization)."""
    trigger = _get_trigger_or_404(db, trigger_id, org.id)
    return _trigger_to_response(trigger)


@router.patch(
    "/{trigger_id}",
    response_model=TriggerResponse,
    summary="Partially update a trigger",
)
def update_trigger(
    trigger_id: str,
    body: TriggerUpdate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor = None,
) -> dict[str, Any]:
    """Partially update a trigger. version_id is NOT updatable."""
    trigger = _get_trigger_or_404(db, trigger_id, org.id)

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "version_id":
            # Silently skip — version_id is immutable after creation
            continue
        if field == "webhook_url" and value is not None:
            value = str(value)
        if field == "override_schema" and value is not None:
            value = [f.model_dump() if hasattr(f, "model_dump") else f for f in value]
        setattr(trigger, field, value)

    trigger.updated_at = utcnow()
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.TRIGGER_UPDATE,
        target_type="trigger",
        target_id=trigger.id,
        target_name=trigger.name,
    )
    db.commit()
    db.refresh(trigger)
    return _trigger_to_response(trigger)


@router.delete(
    "/{trigger_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a trigger",
)
def delete_trigger(
    trigger_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _ws: OptionalRequireEditor = None,
) -> None:
    """Hard-delete a trigger and all its runs (via CASCADE)."""
    trigger = _get_trigger_or_404(db, trigger_id, org.id)
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.TRIGGER_DELETE,
        target_type="trigger",
        target_id=trigger.id,
        target_name=trigger.name,
    )
    db.delete(trigger)
    db.commit()
    logger.info("Deleted trigger %s", trigger_id)


@router.post(
    "/{trigger_id}/toggle",
    response_model=TriggerResponse,
    summary="Enable or disable a trigger",
)
def toggle_trigger(
    trigger_id: str,
    body: TriggerToggleRequest,
    db: DBSession,
    org: CurrentOrg,
    _ws: OptionalRequireEditor = None,
) -> dict[str, Any]:
    """Set is_enabled for a trigger."""
    trigger = _get_trigger_or_404(db, trigger_id, org.id)
    trigger.is_enabled = body.enabled
    trigger.updated_at = utcnow()
    db.commit()
    db.refresh(trigger)
    logger.info("Trigger %s toggled to enabled=%s", trigger_id, body.enabled)
    return _trigger_to_response(trigger)


@router.post(
    "/{trigger_id}/fire",
    response_model=TriggerFireResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Fire a trigger (per-trigger secret auth)",
)
def fire_trigger(
    trigger_id: str,
    body: TriggerFireRequest,
    request: Request,
    db: DBSession,
) -> dict[str, Any]:
    """Fire a trigger to initiate an async solve run.

    Authentication is via per-trigger secret (NOT an org API key):
    - Preferred: ``Authorization: Bearer <trigger_secret>`` header
    - Alternative: ``trigger_secret`` field in the request body

    Returns 202 with a run_id immediately. The solve is processed
    asynchronously by Celery. Poll GET /triggers/{id}/runs/{run_id} for status.

    Error responses:
    - 401: Missing or invalid trigger secret
    - 404: Trigger not found
    - 409: Trigger is disabled
    - 422: Override validation failed (run still created with validation_failed status)
    """
    # Rate limit before DB lookup to avoid wasting queries on throttled callers
    allowed, rate_info = check_rate_limit(
        f"trigger_fire:{trigger_id}",
        limit_per_minute=10,
        limit_per_day=500,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)

    trigger = _get_trigger_public(db, trigger_id)

    # Extract secret from header or body
    provided_secret = _extract_fire_secret(request, body)

    if not provided_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Trigger secret required. Provide via Authorization: Bearer header"
                " or body.trigger_secret"
            ),
        )

    # Compare using constant-time comparison to prevent timing attacks
    expected_hash = trigger.trigger_secret
    provided_hash = _hash_secret(provided_secret)
    if not secrets.compare_digest(expected_hash, provided_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid trigger secret",
        )

    if not trigger.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Trigger is disabled",
        )

    # Audit log: attribute fire to trigger creator (no user in request context)
    log_action(
        db=db,
        organization_id=trigger.organization_id,
        actor=None,
        action=AuditAction.TRIGGER_FIRE,
        target_type="trigger",
        target_id=trigger.id,
        target_name=trigger.name,
        actor_id_override=trigger.created_by,
        actor_name_override="trigger_system",
    )

    # Fire trigger (validate overrides, create run, queue Celery task)
    run, error = trigger_service.fire_trigger(db, trigger, body.override_data)
    db.commit()

    if error:
        # Validation failure — run was created with status=validation_failed
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": error, "run_id": run.id},
        )

    return {"run_id": run.id, "status": run.status}


@router.get(
    "/{trigger_id}/runs",
    response_model=PaginatedResponse[TriggerRunResponse],
    summary="List run history for a trigger",
)
def list_runs(
    trigger_id: str,
    db: DBSession,
    org: CurrentOrg,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Return paginated run history for a trigger, newest first."""
    _get_trigger_or_404(db, trigger_id, org.id)

    query = (
        db.query(TriggerRun)
        .filter(
            TriggerRun.trigger_id == trigger_id,
            TriggerRun.organization_id == org.id,
        )
        .order_by(desc(TriggerRun.created_at))
    )

    items, total = paginate_query(query, page=page, page_size=page_size)
    return create_paginated_response(items, total, page, page_size)


@router.get(
    "/{trigger_id}/runs/{run_id}",
    response_model=TriggerRunResponse,
    summary="Get a single run with full result and override data",
)
def get_run(
    trigger_id: str,
    run_id: str,
    db: DBSession,
    org: CurrentOrg,
) -> TriggerRun:
    """Return full details for a single run including result_data and override_data."""
    _get_trigger_or_404(db, trigger_id, org.id)

    run = (
        db.query(TriggerRun)
        .filter(
            TriggerRun.id == run_id,
            TriggerRun.trigger_id == trigger_id,
            TriggerRun.organization_id == org.id,
        )
        .first()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    return run


@router.post(
    "/{trigger_id}/runs/{run_id}/rerun",
    response_model=TriggerFireResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-fire a trigger using original run's override data",
)
def rerun(
    trigger_id: str,
    run_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> dict[str, Any]:
    """Queue a new run using the override_data from a previous run.

    Authentication is via org API key (user already authenticated). No trigger
    secret is required since the user is already authenticated via the org.
    """
    trigger = _get_trigger_or_404(db, trigger_id, org.id)

    original_run = (
        db.query(TriggerRun)
        .filter(
            TriggerRun.id == run_id,
            TriggerRun.trigger_id == trigger_id,
            TriggerRun.organization_id == org.id,
        )
        .first()
    )
    if not original_run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if not trigger.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Trigger is disabled",
        )

    # Reuse original override_data (skip trigger_secret validation)
    run, error = trigger_service.fire_trigger(db, trigger, original_run.override_data)

    if error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": error, "run_id": run.id},
        )

    logger.info(
        "Rerun queued for trigger %s by user %s (original run: %s)",
        trigger_id,
        user.id,
        run_id,
    )
    return {"run_id": run.id, "status": run.status}
