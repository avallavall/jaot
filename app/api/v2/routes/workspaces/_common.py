"""Shared guards for workspace-scoped routes.

Single source of truth for the tenancy check used by every endpoint that
takes a ``{workspace_id}`` path parameter.

Why this exists
---------------
``RequireAdmin`` / ``RequireViewer`` (``require_workspace_role`` in
``app/api/deps.py``) grant the org owner an admin-equivalent virtual
membership in EVERY workspace via the owner-shortcut — it only proves the
caller owns THEIR org, never that the workspace belongs to that org. An
endpoint that trusts the role dependency alone and then mutates a row keyed
on the path ``workspace_id`` is therefore vulnerable to a cross-tenant IDOR
(an org-B owner acting on an org-A workspace). Routing every such endpoint
through :func:`get_workspace_or_404` closes that class of bug.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


def get_workspace_or_404(
    db: Session, workspace_id: str, org_id: str, *, require_active: bool = True
) -> Workspace:
    """Fetch a workspace belonging to ``org_id`` or raise 404.

    By default only ACTIVE workspaces match (``require_active=True``) — the safe
    default for every mutating or role-gated route. Read-only callers that must
    still see a soft-deleted workspace (e.g. reconciling a deleted workspace's
    stranded credit pool — soft-delete does not reclaim allocated pool credits)
    pass ``require_active=False``. The ``organization_id`` scope is ALWAYS
    enforced, so relaxing the active filter never widens the cross-tenant IDOR
    surface: another org still gets a 404 for this workspace.

    The 404 ``detail`` is intentionally identical for the "exists in another
    org" and "does not exist anywhere" cases so the response cannot be used
    as a cross-tenant existence oracle (OWASP A01 — IDOR).
    """
    query = db.query(Workspace).filter(
        Workspace.id == workspace_id,
        Workspace.organization_id == org_id,
    )
    if require_active:
        query = query.filter(Workspace.is_active.is_(True))
    ws = query.first()
    if not ws:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return ws
