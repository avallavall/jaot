"""Common API dependencies.

Centralized dependency injection for FastAPI endpoints.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.v2.auth import get_current_user
from app.models import Organization, User
from app.models.workspace import WorkspaceMember, WorkspaceRole
from app.shared.db.base import get_db

# Type aliases for cleaner endpoint signatures
DBSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency that requires the current user to be an admin.

    Raises:
        HTTPException: 403 if user is not admin

    Returns:
        User: The current admin user
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def get_current_organization(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    """Get the current user's organization.

    Raises:
        HTTPException: 404 if organization not found

    Returns:
        Organization: The user's organization
    """
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()

    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return org


# Type aliases for admin endpoints
AdminUser = Annotated[User, Depends(get_current_admin_user)]
CurrentOrg = Annotated[Organization, Depends(get_current_organization)]


def require_org_owner(
    current_user: User = Depends(get_current_user),
    org: Organization = Depends(get_current_organization),
) -> User:
    """Dependency that requires the current user to be the ORG OWNER (Phase 7 / D-27).

    Stricter than ``AdminUser`` (platform-admin) and stricter than
    workspace ``role=admin`` — only the organization's
    ``owner_user_id`` can manage BYOL solver licenses.

    Raises:
        HTTPException: 403 when ``organization.owner_user_id != user.id``.

    Returns:
        User: The current user, confirmed as the org owner.
    """
    if org.owner_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization owner access required",
        )
    return current_user


OrgOwnerUser = Annotated[User, Depends(require_org_owner)]


# Optional auth dependencies (Phase 9 / D-06)
#
# Used by endpoints in PUBLIC_PATHS that still want to tag rows with
# user_id/organization_id when a session happens to be present. The
# underlying mechanic is `request.state.user` populated by the
# `ASGIAuthMiddleware` opportunistic-auth branch (Phase 9 Task 1b).
#
# These helpers NEVER raise 401 — they return None for true anonymous
# requests. If you need an endpoint to be authenticated-or-fail, use the
# `CurrentUser` / `CurrentOrg` aliases instead.


def get_optional_current_user(request: Request) -> User | None:
    """Return ``request.state.user`` if present, else ``None``.

    JWT/API-key-optional variant of :func:`get_current_user`. Returns a
    populated ``User`` only when ``ASGIAuthMiddleware`` (Phase 9 Task 1b
    non-fatal auth on PUBLIC_PATHS) attached one to the request state.

    On any other code path — true anonymous, expired JWT, deleted user,
    forged token — returns ``None`` and lets the caller decide what to do
    (typically: leave ``user_id`` NULL on the persisted row).
    """
    return getattr(request.state, "user", None)


def get_optional_current_organization(request: Request) -> Organization | None:
    """Return ``request.state.organization`` if present, else ``None``.

    Companion of :func:`get_optional_current_user`. Same opportunistic-auth
    contract — returns the user's organization when the middleware was able
    to authenticate the request on a public path, ``None`` otherwise.
    """
    return getattr(request.state, "organization", None)


OptionalCurrentUser = Annotated[User | None, Depends(get_optional_current_user)]
OptionalCurrentOrg = Annotated[Organization | None, Depends(get_optional_current_organization)]


# Role hierarchy: lowest to highest. Index position is used for comparison.
_ROLE_ORDER = [
    WorkspaceRole.VIEWER.value,
    WorkspaceRole.SOLVER.value,
    WorkspaceRole.EDITOR.value,
    WorkspaceRole.ADMIN.value,
]


def require_workspace_role(minimum_role: WorkspaceRole) -> Callable[..., WorkspaceMember]:
    """Factory that returns a FastAPI dependency enforcing a minimum workspace role.

    Usage:
        @router.get("/{workspace_id}/members")
        def list_members(
            workspace_id: str,
            member: RequireViewer,
        ):
            ...

    Owner bypass:
        If org.owner_user_id == user.id, a virtual WorkspaceMember with
        role="admin" is synthesized and returned without a DB lookup.
        The org owner always has all permissions in every workspace without
        needing an explicit WorkspaceMember row.

    Args:
        minimum_role: Minimum WorkspaceRole required to proceed.

    Returns:
        A callable FastAPI dependency that resolves to WorkspaceMember.
    """

    def _dep(
        workspace_id: str,
        user: Annotated[User, Depends(get_current_user)],
        org: Annotated[Organization, Depends(get_current_organization)],
        db: Annotated[Session, Depends(get_db)],
    ) -> WorkspaceMember:
        # Owner bypass: org owner has admin-equivalent permissions everywhere.
        # They do not require a WorkspaceMember row.
        if getattr(org, "owner_user_id", None) == user.id:
            return WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user.id,
                organization_id=org.id,
                role=WorkspaceRole.ADMIN.value,
            )

        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.organization_id == org.id,
            )
            .first()
        )

        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this workspace",
            )

        member_role_idx = _ROLE_ORDER.index(member.role) if member.role in _ROLE_ORDER else -1
        min_role_idx = _ROLE_ORDER.index(minimum_role.value)

        if member_role_idx < min_role_idx:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You need {minimum_role.value} role to perform this action",
            )

        return member

    return _dep


# Pre-built Annotated aliases for the four workspace roles.
# Use these directly as type annotations in route function parameters.
#
# Example:
#   @router.delete("/{workspace_id}/members/{user_id}")
#   def remove_member(workspace_id: str, member: RequireAdmin): ...
RequireAdmin = Annotated[WorkspaceMember, Depends(require_workspace_role(WorkspaceRole.ADMIN))]
RequireEditor = Annotated[WorkspaceMember, Depends(require_workspace_role(WorkspaceRole.EDITOR))]
RequireSolver = Annotated[WorkspaceMember, Depends(require_workspace_role(WorkspaceRole.SOLVER))]
RequireViewer = Annotated[WorkspaceMember, Depends(require_workspace_role(WorkspaceRole.VIEWER))]


# Optional workspace role dependencies (for solve and builder endpoints)


def optional_workspace_role(minimum_role: WorkspaceRole) -> Callable[..., WorkspaceMember | None]:
    """Factory that returns a dependency enforcing workspace role ONLY when workspace_id is given.

    When workspace_id query param is absent (None), returns None — org-level access applies.
    When workspace_id is present, enforces the minimum role just like require_workspace_role().

    Usage:
        @router.post("/solve")
        def solve(
            problem: OptimizationProblem,
            workspace_member: OptionalRequireSolver,
        ):
            workspace_id = workspace_member.workspace_id if workspace_member else None

    Owner bypass:
        If org.owner_user_id == user.id and workspace_id is provided, a virtual
        WorkspaceMember with role=admin is synthesized (owner bypass).

    Args:
        minimum_role: Minimum WorkspaceRole required when a workspace_id is provided.

    Returns:
        A callable FastAPI dependency that resolves to Optional[WorkspaceMember].
    """

    def _dep(
        workspace_id: str | None = Query(None),
        user: Annotated[User, Depends(get_current_user)] = None,  # type: ignore[assignment]
        org: Annotated[Organization, Depends(get_current_organization)] = None,  # type: ignore[assignment]
        db: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
    ) -> WorkspaceMember | None:
        if workspace_id is None:
            # No workspace context — org-level access, no workspace role check.
            return None

        # Owner bypass — synthesize a virtual admin member.
        if getattr(org, "owner_user_id", None) == user.id:
            return WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user.id,
                organization_id=org.id,
                role=WorkspaceRole.ADMIN.value,
            )

        # DB membership lookup
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.organization_id == org.id,
            )
            .first()
        )

        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this workspace",
            )

        member_role_idx = _ROLE_ORDER.index(member.role) if member.role in _ROLE_ORDER else -1
        min_role_idx = _ROLE_ORDER.index(minimum_role.value)

        if member_role_idx < min_role_idx:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You need {minimum_role.value} role to perform this action",
            )

        return member

    return _dep


# Pre-built optional aliases — use in solve/builder endpoints that accept an
# optional workspace_id query parameter for workspace-scoped operations.
#
# When workspace_id is absent: resolves to None (org-level, no role check).
# When workspace_id is present: enforces the minimum role or raises 403.
OptionalRequireSolver = Annotated[
    WorkspaceMember | None,
    Depends(optional_workspace_role(WorkspaceRole.SOLVER)),
]
OptionalRequireEditor = Annotated[
    WorkspaceMember | None,
    Depends(optional_workspace_role(WorkspaceRole.EDITOR)),
]
OptionalRequireViewer = Annotated[
    WorkspaceMember | None,
    Depends(optional_workspace_role(WorkspaceRole.VIEWER)),
]
