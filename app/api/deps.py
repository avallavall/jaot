"""Common API dependencies.

Centralized dependency injection for FastAPI endpoints.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.v2.auth import get_current_user
from app.models import Organization, User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole
from app.shared.db.base import get_db

# Re-exported so route modules take it from here with everything else, per the
# project rule. Defined in a leaf module because this one cannot own it — see
# app/shared/db/dependencies.py. The redundant alias is PEP 484's explicit
# re-export form: it marks the name public without an __all__ that would have to
# enumerate (and keep enumerating) every other dependency this module exposes.
from app.shared.db.dependencies import DBSession as DBSession

# Type aliases for cleaner endpoint signatures
CurrentUser = Annotated[User, Depends(get_current_user)]


def enforce_org_rate_limit(db: Session, org: Organization) -> None:
    """Raise 429 when the organization is over the instance's request limits.

    D-23: the two request limits used to be read from columns on
    ``organizations``, copied at signup — so an operator editing them in the
    admin panel changed what NEW organizations would get and nothing about the
    ones already there. One set of limits per instance is the same decision that
    retired the four plan tiers: the value is read from settings on each request
    and there is nothing left to keep in sync.

    Lives here because a bounded context's routes may consume ``app.api.deps``
    and nothing else of the API layer (import contract 7) — ``file_io`` is one
    of the callers.

    Args:
        db: Database session.
        org: The organization the request is billed to.

    Raises:
        HTTPException 429: with the limiter's ``retry_after`` detail.
    """
    from app.services.platform_settings_service import (  # noqa: PLC0415
        PlatformSettingsService as PSS,
    )
    from app.shared.core.rate_limiter import check_rate_limit  # noqa: PLC0415

    limits = PSS.get_instance_limits(db)
    allowed, rate_info = check_rate_limit(
        org.id, limits["rate_limit_per_minute"], limits["rate_limit_per_day"]
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=rate_info)


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


def _assert_workspace_in_org(db: Session, workspace_id: str, org_id: str) -> None:
    """Raise 404 unless the workspace belongs to this organization.

    Both role dependencies below let the owner of an organization through
    without a ``WorkspaceMember`` row. That shortcut only proves the caller owns
    THEIR organization, so without this check the owner of organization B passed
    the role gate for a workspace of organization A. Every route under
    ``/{workspace_id}/`` whose own query filters by ``organization_id`` returned
    an empty answer instead of a 404 (the members, audit and invite lists), and
    any route added later that filtered by ``workspace_id`` alone would have
    served another tenant's rows.

    The 404 ``detail`` matches the one ``get_workspace_or_404`` uses, so the
    answer for "belongs to another organization" and "does not exist" is the
    same and cannot be used to find out which ids are real.
    """
    exists = (
        db.query(Workspace.id)
        .filter(Workspace.id == workspace_id, Workspace.organization_id == org_id)
        .first()
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )


def check_workspace_role(
    db: Session,
    user: User,
    org: Organization,
    workspace_id: str,
    minimum_role: WorkspaceRole,
) -> WorkspaceMember:
    """Resolve the caller's membership of a workspace, or raise.

    Raises 404 when the workspace is not this organization's, 403 when the
    caller is not a member of it or holds a role below ``minimum_role``.

    Both role dependencies below are thin wrappers over this. Call it directly
    from a route that reads a ``workspace_id`` the dependencies cannot see —
    one that arrives in the request body rather than in the path or the query
    string.
    """
    _assert_workspace_in_org(db, workspace_id, org.id)

    # Owner bypass: the owner of the organization has admin-equivalent
    # permissions in every workspace of it, without a WorkspaceMember row.
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
        role="admin" is synthesized. The org owner always has all permissions in
        every workspace OF ITS OWN ORGANIZATION without needing an explicit
        WorkspaceMember row. A workspace of another organization answers 404.

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
        return check_workspace_role(db, user, org, workspace_id, minimum_role)

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
        WorkspaceMember with role=admin is synthesized (owner bypass). A
        workspace of another organization answers 404.

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
        return check_workspace_role(db, user, org, workspace_id, minimum_role)

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


def get_request_locale(
    x_jaot_locale: Annotated[str | None, Header()] = None,
) -> str:
    """The locale the caller is reading the app in, for anything we GENERATE.

    Sent by the web client on every request (``X-JAOT-Locale``). Only affects
    generated prose — assistant replies and explanations — never stored data,
    which has no language. Unknown or absent values normalise to the default, so
    an API client that never sends it keeps today's behaviour.
    """
    from app.services.llm.language import normalize_locale

    return normalize_locale(x_jaot_locale)


# The user's reading language. Inject where an endpoint makes the model WRITE.
RequestLocale = Annotated[str, Depends(get_request_locale)]
