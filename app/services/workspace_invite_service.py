"""Redeeming a workspace invite.

Two routes redeem an invite: ``POST /workspaces/invites/accept`` for a person
who already has an account, and ``POST /auth/signup/email`` with an
``invite_token`` for a person who creates one from the invite link. Both must
refuse the same invites for the same reasons, so the checks live here.

``log_action`` rules apply: nothing here commits. The caller commits the
membership and its audit entry together.
"""

import hashlib

from fastapi import status
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction
from app.models.user import User
from app.models.workspace import (
    InviteMethod,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceRemoval,
)
from app.services.audit_service import log_action
from app.shared.core.http_errors import CodedHTTPException
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def hash_invite_token(plaintext: str) -> str:
    """Return the SHA-256 hex digest stored in ``WorkspaceInvite.token_hash``."""
    return hashlib.sha256(plaintext.encode()).hexdigest()


def find_redeemable_invite(db: Session, token: str) -> WorkspaceInvite:
    """Return the invite for ``token``, or raise the reason it cannot be used.

    Checks what does not depend on who is redeeming it: the token exists, the
    workspace is still there, the invite is not revoked, not expired, and an
    email invite has not been used already.
    """
    invite = (
        db.query(WorkspaceInvite)
        .filter(WorkspaceInvite.token_hash == hash_invite_token(token))
        .first()
    )
    workspace = (
        db.query(Workspace.id)
        .filter(
            Workspace.id == invite.workspace_id,
            Workspace.organization_id == invite.organization_id,
            Workspace.is_active.is_(True),
        )
        .first()
        if invite
        else None
    )
    # A deleted workspace is soft-deleted: its invites still resolved, and
    # accepting one wrote a membership of a workspace nobody can open.
    if invite is None or workspace is None:
        raise CodedHTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found or invalid token",
            code="invite.not_found",
        )

    if invite.is_revoked:
        raise CodedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invite has been revoked",
            code="invite.revoked",
        )

    if invite.expires_at < utcnow():
        raise CodedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invite has expired",
            code="invite.expired",
        )

    if invite.method == InviteMethod.EMAIL.value and invite.accepted_at is not None:
        raise CodedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This email invite has already been accepted",
            code="invite.already_accepted",
        )

    return invite


def refuse_other_email(invite: WorkspaceInvite, email: str | None) -> None:
    """An email invite is for the address it was sent to, and no other.

    Otherwise anyone who got hold of the token joined with the invite's role.
    """
    if (
        invite.method == InviteMethod.EMAIL.value
        and (invite.invitee_email or "").strip().lower() != (email or "").strip().lower()
    ):
        raise CodedHTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This invite was sent to another email address. Sign in with that "
                "address to accept it."
            ),
            code="invite.other_email",
        )


def refuse_if_removed_since(db: Session, invite: WorkspaceInvite, user_id: str) -> None:
    """Refuse an invite that was created before this user was last removed.

    Removing a member deleted their membership and nothing else, so the link
    they had joined with let them straight back in. An invite created after the
    removal is a new decision by an admin and still works.
    """
    removal = (
        db.query(WorkspaceRemoval.removed_at)
        .filter(
            WorkspaceRemoval.workspace_id == invite.workspace_id,
            WorkspaceRemoval.organization_id == invite.organization_id,
            WorkspaceRemoval.user_id == user_id,
        )
        .first()
    )
    if removal is not None and removal.removed_at >= invite.created_at:
        raise CodedHTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You were removed from this workspace after this invite was created. "
                "Ask a workspace admin for a new invite."
            ),
            code="invite.removed_member",
        )


def add_member_from_invite(db: Session, invite: WorkspaceInvite, user: User) -> WorkspaceMember:
    """Write the membership the invite grants, and its audit entry. No commit."""
    now = utcnow()
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

    # An email invite is single-use.
    if invite.method == InviteMethod.EMAIL.value:
        invite.accepted_at = now
        invite.accepted_by = user.id

    log_action(
        db=db,
        organization_id=invite.organization_id,
        actor=user,
        action=AuditAction.MEMBER_JOIN,
        workspace_id=invite.workspace_id,
        target_type="user",
        target_id=user.id,
        target_name=user.name,
        metadata={"method": invite.method, "role": invite.role, "invite_id": invite.id},
    )
    return member
