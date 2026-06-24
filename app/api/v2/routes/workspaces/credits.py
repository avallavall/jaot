"""Credit pool endpoints for workspace budget management.

Routes mounted under /{workspace_id}/credits/:
  GET    /            Get credit pool stats (viewer+)
  POST   /allocate    Allocate credits from org balance to pool (admin only)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentOrg, CurrentUser, DBSession, RequireAdmin, RequireViewer
from app.api.v2.routes.workspaces._common import get_workspace_or_404
from app.models.workspace_credits import WorkspaceCreditPool
from app.schemas.workspace import CreditPoolAllocate, CreditPoolResponse
from app.services import workspace_credits_service
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_or_create_pool(db: Any, workspace_id: str, org_id: str) -> WorkspaceCreditPool:
    """Fetch or create a credit pool for the workspace.

    Idempotent under concurrent first-GETs. ``workspace_id`` is UNIQUE
    (WorkspaceCreditPool model), so two requests that both find no pool and
    both INSERT will collide: the loser's ``commit`` raises IntegrityError. We
    roll back and re-fetch the row the winner committed instead of letting the
    uncaught error surface as a 500.
    """
    pool: WorkspaceCreditPool | None = (
        db.query(WorkspaceCreditPool)
        .filter(
            WorkspaceCreditPool.workspace_id == workspace_id,
            WorkspaceCreditPool.organization_id == org_id,
        )
        .first()
    )
    if pool is not None:
        return pool

    now = utcnow()
    pool = WorkspaceCreditPool(
        id=generate_id("wcp_"),
        workspace_id=workspace_id,
        organization_id=org_id,
        allocated_credits=0,
        used_credits=0,
        last_alert_threshold=None,
        created_at=now,
        updated_at=now,
    )
    db.add(pool)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent first-GET won the unique(workspace_id) race — re-fetch
        # its committed row so get-or-create stays idempotent.
        db.rollback()
        pool = (
            db.query(WorkspaceCreditPool)
            .filter(
                WorkspaceCreditPool.workspace_id == workspace_id,
                WorkspaceCreditPool.organization_id == org_id,
            )
            .first()
        )
        if pool is None:
            # Not the duplicate-insert we expected — surface the original error.
            raise
        return pool
    db.refresh(pool)
    return pool


@router.get(
    "/",
    response_model=CreditPoolResponse,
    summary="Get workspace credit pool stats (viewer+)",
)
def get_credit_pool(
    workspace_id: str,
    db: DBSession,
    org: CurrentOrg,
    _viewer: RequireViewer,
) -> CreditPoolResponse:
    """Return credit pool statistics for the workspace. Requires viewer role.

    Read-only, so it intentionally allows soft-deleted (is_active=False)
    workspaces (``require_active=False``): soft-delete does not reclaim a
    workspace's allocated pool credits, so the pool must stay viewable for
    reconciliation. The org_id scope is still enforced, so cross-tenant access
    remains a 404 (the IDOR guard is unaffected). Allocation stays strict.
    """
    # Tenancy guard (cross-tenant IDOR): RequireViewer's owner-shortcut does
    # not check the workspace's org — resolve it against org.id first.
    get_workspace_or_404(db, workspace_id, org.id, require_active=False)
    pool = _get_or_create_pool(db, workspace_id, org.id)
    return CreditPoolResponse.from_pool(pool)


@router.post(
    "/allocate",
    response_model=CreditPoolResponse,
    summary="Allocate credits from org balance to workspace pool (admin only)",
)
def allocate_credits(
    workspace_id: str,
    body: CreditPoolAllocate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _admin: RequireAdmin,
) -> CreditPoolResponse:
    """Transfer credits from the organization's balance into the workspace credit pool.

    Requires admin role. Raises 400 if org has insufficient balance.
    """
    # Tenancy guard (cross-tenant IDOR): RequireAdmin's owner-shortcut does
    # not check the workspace's org — resolve it against org.id first.
    get_workspace_or_404(db, workspace_id, org.id)
    try:
        pool = workspace_credits_service.allocate_credits_to_pool(
            db=db,
            org=org,
            workspace_id=workspace_id,
            amount=body.amount,
            actor=user,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(pool)
    logger.info(
        "Allocated %d credits to workspace %s (org %s) by user %s",
        body.amount,
        workspace_id,
        org.id,
        user.id,
    )
    return CreditPoolResponse.from_pool(pool)
