"""Workspace invite endpoints.

Routes:
  POST   /{workspace_id}/invites/email   Create email invite (admin only)
  POST   /{workspace_id}/invites/link    Create shareable link invite (admin only)
  POST   /invites/accept                 Accept invite via token (authenticated user)
  GET    /{workspace_id}/invites         List pending invites (admin only)
  DELETE /{workspace_id}/invites/{id}   Revoke invite (admin only)

Token security:
  - secrets.token_urlsafe(32) generates the plaintext token
  - SHA-256 hash is stored in token_hash
  - Accept endpoint re-hashes provided token for comparison
  - Email invites are single-use (accepted_at checked)
  - Link invites are multi-use but idempotent per user
"""

import hashlib
import logging
import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentOrg, CurrentUser, DBSession, RequireAdmin
from app.api.v2.routes.workspaces._common import get_workspace_or_404
from app.models.audit_log import AuditAction
from app.models.workspace import InviteMethod, WorkspaceInvite, WorkspaceMember
from app.schemas.workspace import (
    EmailInviteCreate,
    InviteAccept,
    InviteResponse,
    LinkInviteCreate,
    LinkInviteResponse,
)
from app.services.audit_service import log_action
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# Main router: workspace-scoped invite endpoints (mounted at /{workspace_id}/invites/)
router = APIRouter()

# Accept-only router: flat accept endpoint (mounted at /invites/ for /invites/accept)
accept_router = APIRouter()

_INVITE_EXPIRY_DAYS = 7


def _hash_token(plaintext: str) -> str:
    """Return SHA-256 hex digest of plaintext invite token."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _invite_to_response(invite: WorkspaceInvite) -> InviteResponse:
    """Build InviteResponse from ORM object."""
    return InviteResponse(
        id=invite.id,
        workspace_id=invite.workspace_id,
        role=invite.role,
        method=invite.method,
        invitee_email=invite.invitee_email,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        is_revoked=invite.is_revoked,
    )


# POST /{workspace_id}/invites/email — Create email invite


@router.post(
    "/email",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an email invite (admin only)",
)
def create_email_invite(
    workspace_id: str,
    body: EmailInviteCreate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _admin: RequireAdmin,
) -> InviteResponse:
    """Create a single-use email invite for the specified address.

    A 7-day expiry is set. The token is hashed and stored; the plaintext
    is (conceptually) sent via email. For now email delivery is best-effort
    and logged — configure EMAIL_BACKEND to send real emails.
    """
    # Tenancy guard (cross-tenant IDOR): RequireAdmin's owner-shortcut does
    # not check the workspace's org — resolve it against org.id first.
    get_workspace_or_404(db, workspace_id, org.id)

    plaintext = secrets.token_urlsafe(32)
    token_hash = _hash_token(plaintext)
    now = utcnow()
    expires_at = now + timedelta(days=_INVITE_EXPIRY_DAYS)

    invite = WorkspaceInvite(
        id=generate_id("inv_"),
        workspace_id=workspace_id,
        organization_id=org.id,
        role=body.role,
        method=InviteMethod.EMAIL.value,
        invitee_email=str(body.email),
        token_hash=token_hash,
        created_by=user.id,
        created_at=now,
        expires_at=expires_at,
        accepted_at=None,
        accepted_by=None,
        is_revoked=False,
    )
    db.add(invite)

    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MEMBER_INVITE,
        workspace_id=workspace_id,
        target_type="user",
        target_id=None,
        target_name=str(body.email),
        metadata={"method": "email", "role": body.role, "invite_id": invite.id},
    )

    db.commit()
    db.refresh(invite)

    # Best-effort email send — log plaintext token for now
    logger.info(
        "Email invite created: workspace=%s email=%s role=%s token=%s",
        workspace_id,
        body.email,
        body.role,
        plaintext,
    )

    return _invite_to_response(invite)


# POST /{workspace_id}/invites/link — Create shareable link invite


@router.post(
    "/link",
    response_model=LinkInviteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shareable link invite (admin only)",
)
def create_link_invite(
    workspace_id: str,
    body: LinkInviteCreate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _admin: RequireAdmin,
) -> LinkInviteResponse:
    """Create a shareable link invite.

    The plaintext token is embedded in the returned invite_url (path: /join/{token}).
    Multiple users can accept the same link; each acceptance is idempotent per user.
    """
    # Tenancy guard (cross-tenant IDOR): RequireAdmin's owner-shortcut does
    # not check the workspace's org — resolve it against org.id first.
    get_workspace_or_404(db, workspace_id, org.id)

    plaintext = secrets.token_urlsafe(32)
    token_hash = _hash_token(plaintext)
    now = utcnow()
    expires_at = now + timedelta(days=_INVITE_EXPIRY_DAYS)

    invite = WorkspaceInvite(
        id=generate_id("inv_"),
        workspace_id=workspace_id,
        organization_id=org.id,
        role=body.role,
        method=InviteMethod.LINK.value,
        invitee_email=None,
        token_hash=token_hash,
        created_by=user.id,
        created_at=now,
        expires_at=expires_at,
        accepted_at=None,
        accepted_by=None,
        is_revoked=False,
    )
    db.add(invite)

    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MEMBER_INVITE,
        workspace_id=workspace_id,
        target_type="invite",
        target_id=invite.id,
        target_name=f"link:{body.role}",
        metadata={"method": "link", "role": body.role, "invite_id": invite.id},
    )

    db.commit()
    db.refresh(invite)
    logger.info(
        "Link invite created: workspace=%s role=%s invite_id=%s",
        workspace_id,
        body.role,
        invite.id,
    )

    return LinkInviteResponse(
        invite_url=f"/join/{plaintext}",
        expires_at=expires_at,
    )


# POST /invites/accept — Accept invite (authenticated user required)
# Registered on BOTH router (for /{workspace_id}/invites/accept) and
# accept_router (for flat /invites/accept). accept_router is mounted at
# /invites/ so the full path becomes /workspaces/invites/accept.


@router.post(
    "/accept",
    status_code=status.HTTP_200_OK,
    summary="Accept a workspace invite token",
)
@accept_router.post(
    "/accept",
    status_code=status.HTTP_200_OK,
    summary="Accept a workspace invite token",
    include_in_schema=False,  # avoid duplicate in OpenAPI docs
)
def accept_invite(
    body: InviteAccept,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
) -> dict[str, Any]:
    """Accept an invite token and join the workspace.

    The token is hashed and compared against stored token_hash entries.
    Email invites are single-use; link invites are multi-use but idempotent
    (second call by the same user is a no-op).

    The user must already be authenticated (signed up and logged in).
    """
    token_hash = _hash_token(body.token)

    invite = db.query(WorkspaceInvite).filter(WorkspaceInvite.token_hash == token_hash).first()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found or invalid token",
        )

    if invite.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invite has been revoked",
        )

    now = utcnow()
    # Handle timezone-aware vs naive datetime comparison
    expires_at = invite.expires_at
    if hasattr(expires_at, "tzinfo") and expires_at.tzinfo is not None:
        from datetime import timezone

        now_cmp = now.replace(tzinfo=timezone.utc)
    else:
        now_cmp = now.replace(tzinfo=None)
        if hasattr(expires_at, "tzinfo"):
            expires_at = expires_at.replace(tzinfo=None)

    if expires_at < now_cmp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invite has expired",
        )

    # Email invite: single-use check
    if invite.method == InviteMethod.EMAIL.value:
        if invite.accepted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This email invite has already been accepted",
            )

    # Link invite: idempotent — check if user is already a member
    existing = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == invite.workspace_id,
            WorkspaceMember.user_id == user.id,
        )
        .first()
    )
    if existing:
        return {
            "message": "You are already a member of this workspace",
            "workspace_id": invite.workspace_id,
            "role": existing.role,
        }

    member = WorkspaceMember(
        id=generate_id("wkm_"),
        workspace_id=invite.workspace_id,
        user_id=user.id,
        organization_id=invite.organization_id,
        role=invite.role,
        invited_by=invite.created_by,
        joined_at=now,
    )
    db.add(member)

    # For email invites: mark as used
    if invite.method == InviteMethod.EMAIL.value:
        invite.accepted_at = now
        invite.accepted_by = user.id

    log_action(
        db=db,
        organization_id=invite.organization_id,
        actor=user,
        action=AuditAction.MEMBER_INVITE,
        workspace_id=invite.workspace_id,
        target_type="user",
        target_id=user.id,
        target_name=user.name,
        metadata={"action": "accepted", "method": invite.method, "role": invite.role},
    )

    db.commit()
    logger.info(
        "Invite accepted: user=%s workspace=%s role=%s method=%s",
        user.id,
        invite.workspace_id,
        invite.role,
        invite.method,
    )

    return {
        "message": "Successfully joined workspace",
        "workspace_id": invite.workspace_id,
        "role": invite.role,
    }


# GET /{workspace_id}/invites — List pending invites


@router.get(
    "/",
    response_model=list[InviteResponse],
    summary="List pending invites for workspace (admin only)",
)
def list_invites(
    workspace_id: str,
    db: DBSession,
    org: CurrentOrg,
    _admin: RequireAdmin,
) -> list[InviteResponse]:
    """Return all non-revoked, non-expired invites for the workspace."""
    now = utcnow()
    invites = (
        db.query(WorkspaceInvite)
        .filter(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.organization_id == org.id,
            WorkspaceInvite.is_revoked.is_(False),
        )
        .all()
    )
    # Filter out expired in Python (avoids datetime comparison issues across DB backends)
    pending = [
        inv
        for inv in invites
        if inv.expires_at.replace(tzinfo=None) > now.replace(tzinfo=None)
        and (inv.method == InviteMethod.LINK.value or inv.accepted_at is None)
    ]
    return [_invite_to_response(inv) for inv in pending]


@router.delete(
    "/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an invite (admin only)",
)
def revoke_invite(
    workspace_id: str,
    invite_id: str,
    db: DBSession,
    org: CurrentOrg,
    _admin: RequireAdmin,
) -> None:
    """Mark an invite as revoked. Prevents future acceptance."""
    invite = (
        db.query(WorkspaceInvite)
        .filter(
            WorkspaceInvite.id == invite_id,
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.organization_id == org.id,
        )
        .first()
    )
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found",
        )
    invite.is_revoked = True
    db.commit()
    logger.info("Revoked invite %s in workspace %s", invite_id, workspace_id)
