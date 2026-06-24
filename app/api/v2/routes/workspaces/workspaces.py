"""Workspace CRUD endpoints.

Routes mounted at the root of the workspaces router (/workspaces/):
  POST   /               Create workspace (org owner only)
  GET    /               List workspaces (owner sees all; others see their memberships)
  GET    /{workspace_id} Get workspace detail (RequireViewer)
  PATCH  /{workspace_id} Update workspace (RequireAdmin)
  DELETE /{workspace_id} Delete workspace (org owner only, soft-delete)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, func

from app.api.deps import CurrentOrg, CurrentUser, DBSession, RequireAdmin, RequireViewer
from app.api.v2.routes.workspaces._common import get_workspace_or_404
from app.models.audit_log import AuditAction
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole
from app.models.workspace_credits import WorkspaceCreditPool
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services.audit_service import log_action
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.shared.utils.pagination import PaginatedResponse, create_paginated_response, paginate_query

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_workspace_response(db: DBSession, ws: Workspace) -> WorkspaceResponse:
    """Build a WorkspaceResponse with member_count and pool stats."""
    member_count = (
        db.query(func.count(WorkspaceMember.id))
        .filter(WorkspaceMember.workspace_id == ws.id)
        .scalar()
        or 0
    )
    pool = db.query(WorkspaceCreditPool).filter(WorkspaceCreditPool.workspace_id == ws.id).first()
    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        description=ws.description,
        is_active=ws.is_active,
        created_by=ws.created_by,
        created_at=ws.created_at,
        updated_at=ws.updated_at,
        member_count=member_count,
        pool_allocated=pool.allocated_credits if pool else None,
        pool_used=pool.used_credits if pool else None,
    )


@router.post(
    "/",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workspace (org owner only)",
)
def create_workspace(
    body: WorkspaceCreate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> WorkspaceResponse:
    """Create a workspace. Only the org owner can create workspaces.

    The creator is automatically added as an admin member.
    A WorkspaceCreditPool with 0 credits is created automatically.
    """
    if getattr(org, "owner_user_id", None) != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organization owner can create workspaces",
        )

    now = utcnow()
    ws = Workspace(
        id=generate_id("wks_"),
        organization_id=org.id,
        name=body.name,
        description=body.description,
        is_active=True,
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(ws)
    db.flush()  # get ws.id before creating members/pool

    # Auto-add creator as admin member
    member = WorkspaceMember(
        id=generate_id("wkm_"),
        workspace_id=ws.id,
        user_id=user.id,
        organization_id=org.id,
        role=WorkspaceRole.ADMIN.value,
        invited_by=None,
        joined_at=now,
    )
    db.add(member)

    pool = WorkspaceCreditPool(
        id=generate_id("wcp_"),
        workspace_id=ws.id,
        organization_id=org.id,
        allocated_credits=0,
        used_credits=0,
        last_alert_threshold=None,
        created_at=now,
        updated_at=now,
    )
    db.add(pool)

    # Audit log
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.WORKSPACE_CREATE,
        workspace_id=ws.id,
        target_type="workspace",
        target_id=ws.id,
        target_name=ws.name,
    )

    db.commit()
    db.refresh(ws)
    logger.info("Created workspace %s for org %s by user %s", ws.id, org.id, user.id)
    return _build_workspace_response(db, ws)


@router.get(
    "/",
    response_model=PaginatedResponse[WorkspaceResponse],
    summary="List workspaces",
)
def list_workspaces(
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """List workspaces.

    Org owner sees all workspaces in the org.
    Other users see only workspaces where they have a WorkspaceMember row.
    """
    base_query = db.query(Workspace).filter(
        Workspace.organization_id == org.id,
        Workspace.is_active.is_(True),
    )

    is_owner = getattr(org, "owner_user_id", None) == user.id
    if not is_owner:
        # Filter to workspaces the user is a member of
        member_ws_ids = (
            db.query(WorkspaceMember.workspace_id)
            .filter(
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.organization_id == org.id,
            )
            .scalar_subquery()
        )
        base_query = base_query.filter(Workspace.id.in_(member_ws_ids))

    base_query = base_query.order_by(desc(Workspace.created_at))
    workspaces, total = paginate_query(base_query, page=page, page_size=page_size)

    items = [_build_workspace_response(db, ws) for ws in workspaces]
    return create_paginated_response(items, total, page, page_size)


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Get workspace detail (viewer+)",
)
def get_workspace(
    workspace_id: str,
    db: DBSession,
    org: CurrentOrg,
    _member: RequireViewer,
) -> WorkspaceResponse:
    """Return workspace detail with member count and pool stats. Requires viewer role."""
    ws = get_workspace_or_404(db, workspace_id, org.id)
    return _build_workspace_response(db, ws)


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Update workspace (admin only)",
)
def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _member: RequireAdmin,
) -> WorkspaceResponse:
    """Update a workspace's name or description. Requires admin role."""
    ws = get_workspace_or_404(db, workspace_id, org.id)

    before_state = {"name": ws.name, "description": ws.description}
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(ws, field, value)
    ws.updated_at = utcnow()

    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.WORKSPACE_UPDATE,
        workspace_id=ws.id,
        target_type="workspace",
        target_id=ws.id,
        target_name=ws.name,
        before_state=before_state,
        after_state=body.model_dump(exclude_unset=True),
    )

    db.commit()
    db.refresh(ws)
    return _build_workspace_response(db, ws)


# DELETE /{workspace_id} — Delete workspace (org owner only)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete workspace (org owner only, soft-delete)",
)
def delete_workspace(
    workspace_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> None:
    """Soft-delete a workspace by setting is_active=False. Org owner only."""
    if getattr(org, "owner_user_id", None) != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organization owner can delete workspaces",
        )

    ws = get_workspace_or_404(db, workspace_id, org.id)
    ws.is_active = False
    ws.updated_at = utcnow()
    db.commit()
    logger.info("Soft-deleted workspace %s by owner %s", workspace_id, user.id)
