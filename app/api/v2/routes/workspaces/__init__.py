"""Workspaces router — aggregates workspace CRUD, member, invite, audit, and credits routes.

Mounted at /api/v2/workspaces in the main router.

Route layout:
  Workspace CRUD:
    POST   /workspaces/                             Create workspace
    GET    /workspaces/                             List workspaces
    GET    /workspaces/{workspace_id}               Get workspace
    PATCH  /workspaces/{workspace_id}               Update workspace
    DELETE /workspaces/{workspace_id}               Delete workspace

  Member management:
    GET    /workspaces/{workspace_id}/members/      List members
    PATCH  /workspaces/{workspace_id}/members/{uid} Update role
    DELETE /workspaces/{workspace_id}/members/{uid} Remove member

  Invites:
    POST   /workspaces/{workspace_id}/invites/email  Email invite
    POST   /workspaces/{workspace_id}/invites/link   Link invite
    POST   /workspaces/invites/accept                Accept token
    GET    /workspaces/{workspace_id}/invites/       List pending
    DELETE /workspaces/{workspace_id}/invites/{id}   Revoke

  Audit log:
    GET    /workspaces/{workspace_id}/audit/        Workspace audit log
    GET    /workspaces/audit/org                    Org-wide audit log

  Credit pool:
    GET    /workspaces/{workspace_id}/credits/          Pool stats
    POST   /workspaces/{workspace_id}/credits/allocate  Allocate credits
"""

from fastapi import APIRouter

from app.api.v2.routes.workspaces import audit, credits, invites, members, workspaces

router = APIRouter()

# ---- Workspace CRUD (root-level paths) ----
router.include_router(workspaces.router)

# ---- Org-level audit log (must be registered BEFORE the workspace-scoped routes
#      so /audit/org is not swallowed by /{workspace_id}/...) ----
router.include_router(audit.org_router)

# ---- Accept invite (flat path: /invites/accept — no workspace_id in path) ----
# Use accept_router which only exposes the /accept endpoint (not email/link/list/revoke)
router.include_router(invites.accept_router, prefix="/invites")

# ---- Workspace-scoped sub-routes ----
router.include_router(members.router, prefix="/{workspace_id}/members")
router.include_router(invites.router, prefix="/{workspace_id}/invites")
router.include_router(audit.router, prefix="/{workspace_id}/audit")
router.include_router(credits.router, prefix="/{workspace_id}/credits")
