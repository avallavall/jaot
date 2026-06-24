"""Audit log endpoints for workspace and org-level audit trails.

Routes:
  GET /{workspace_id}/audit/   List audit logs for a workspace (admin only)
  GET /audit/org               List audit logs across all org workspaces (owner only)

Supports query filters: action, actor_id, target_type, target_id, date_from, date_to.
Returns paginated, newest-first audit log entries.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc

from app.api.deps import CurrentOrg, CurrentUser, DBSession, RequireAdmin
from app.models.audit_log import AuditLog
from app.schemas.workspace import AuditLogResponse
from app.shared.utils.pagination import PaginatedResponse, create_paginated_response, paginate_query

logger = logging.getLogger(__name__)

# Workspace-scoped router (mounted at /{workspace_id}/audit)
router = APIRouter()

# Org-level router (mounted at root level — /audit/org)
org_router = APIRouter()


def _apply_audit_filters(
    query: Any,
    action: str | None,
    actor_id: str | None,
    target_type: str | None,
    target_id: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Any:
    """Apply optional filter parameters to an audit log query."""
    if action:
        query = query.filter(AuditLog.action == action)
    if actor_id:
        query = query.filter(AuditLog.actor_id == actor_id)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    if target_id:
        query = query.filter(AuditLog.target_id == target_id)
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)
    return query


def _log_to_response(log: AuditLog) -> AuditLogResponse:
    """Convert ORM AuditLog to response schema (mapping log_metadata -> metadata)."""
    return AuditLogResponse.from_orm_log(log)


@router.get(
    "/",
    response_model=PaginatedResponse[AuditLogResponse],
    summary="List audit logs for a workspace (admin only)",
)
def list_audit_logs(
    workspace_id: str,
    db: DBSession,
    org: CurrentOrg,
    _admin: RequireAdmin,
    action: str | None = Query(default=None, description="Filter by action type"),
    actor_id: str | None = Query(default=None, description="Filter by actor user ID"),
    target_type: str | None = Query(default=None, description="Filter by target type"),
    target_id: str | None = Query(default=None, description="Filter by target entity ID"),
    date_from: datetime | None = Query(
        default=None, description="Filter entries from this datetime"
    ),
    date_to: datetime | None = Query(
        default=None, description="Filter entries up to this datetime"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Return paginated audit log entries for a specific workspace.

    Only workspace admins (and the org owner, who bypasses role checks) can
    view the audit log. Entries are ordered newest first.
    """
    query = (
        db.query(AuditLog)
        .filter(
            AuditLog.organization_id == org.id,
            AuditLog.workspace_id == workspace_id,
        )
        .order_by(desc(AuditLog.created_at))
    )
    query = _apply_audit_filters(
        query, action, actor_id, target_type, target_id, date_from, date_to
    )

    logs, total = paginate_query(query, page=page, page_size=page_size)
    items = [_log_to_response(log) for log in logs]
    return create_paginated_response(items, total, page, page_size)


# GET /audit/org — Org-wide audit log (org owner only)


@org_router.get(
    "/audit/org",
    response_model=PaginatedResponse[AuditLogResponse],
    summary="List audit logs across all workspaces in the org (owner only)",
)
def list_org_audit_logs(
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    workspace_id: str | None = Query(default=None, description="Filter by workspace ID"),
    action: str | None = Query(default=None, description="Filter by action type"),
    actor_id: str | None = Query(default=None, description="Filter by actor user ID"),
    target_type: str | None = Query(default=None, description="Filter by target type"),
    target_id: str | None = Query(default=None, description="Filter by target entity ID"),
    date_from: datetime | None = Query(
        default=None, description="Filter entries from this datetime"
    ),
    date_to: datetime | None = Query(
        default=None, description="Filter entries up to this datetime"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Return paginated audit log entries across all workspaces in the org.

    Restricted to the organization owner.
    """
    if getattr(org, "owner_user_id", None) != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organization owner can view the org-wide audit log",
        )

    query = (
        db.query(AuditLog)
        .filter(AuditLog.organization_id == org.id)
        .order_by(desc(AuditLog.created_at))
    )

    if workspace_id:
        query = query.filter(AuditLog.workspace_id == workspace_id)

    query = _apply_audit_filters(
        query, action, actor_id, target_type, target_id, date_from, date_to
    )

    logs, total = paginate_query(query, page=page, page_size=page_size)
    items = [_log_to_response(log) for log in logs]
    return create_paginated_response(items, total, page, page_size)
