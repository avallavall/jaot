"""Workspace member management endpoints.

Routes mounted under /{workspace_id}/members/:
  GET    /                         List members (viewer+)
  PATCH  /{user_id}                Update member role (admin only)
  DELETE /{user_id}                Remove member (admin only)
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentOrg, CurrentUser, DBSession, RequireAdmin, RequireViewer
from app.models.audit_log import AuditAction
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.schemas.workspace import MemberRoleUpdate, WorkspaceMemberResponse
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_member_or_404(
    db: DBSession, workspace_id: str, user_id: str, org_id: str
) -> WorkspaceMember:
    """Fetch a WorkspaceMember or raise 404."""
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.organization_id == org_id,
        )
        .first()
    )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this workspace",
        )
    return member


def _member_to_response(db: DBSession, member: WorkspaceMember) -> WorkspaceMemberResponse:
    """Build WorkspaceMemberResponse with denormalized user_name and user_email."""
    user = db.query(User).filter(User.id == member.user_id).first()
    return WorkspaceMemberResponse(
        id=member.id,
        user_id=member.user_id,
        user_name=user.name if user else member.user_id,
        user_email=user.email if user else "",
        role=member.role,
        joined_at=member.joined_at,
        invited_by=member.invited_by,
    )


@router.get(
    "/",
    response_model=list[WorkspaceMemberResponse],
    summary="List workspace members (viewer+)",
)
def list_members(
    workspace_id: str,
    db: DBSession,
    org: CurrentOrg,
    _member: RequireViewer,
) -> list[WorkspaceMemberResponse]:
    """Return all members of the workspace. Requires viewer role."""
    members = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.organization_id == org.id,
        )
        .all()
    )
    return [_member_to_response(db, m) for m in members]


@router.patch(
    "/{user_id}",
    response_model=WorkspaceMemberResponse,
    summary="Update a member's role (admin only)",
)
def update_member_role(
    workspace_id: str,
    user_id: str,
    body: MemberRoleUpdate,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _admin: RequireAdmin,
) -> WorkspaceMemberResponse:
    """Update a workspace member's role. Requires admin role.

    Restrictions:
    - Cannot change own role (admin must have another admin do it).
    - Cannot target the org owner (owner's access is managed at org level).
    """
    if user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role. Ask another admin.",
        )
    if getattr(org, "owner_user_id", None) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change the organization owner's workspace role",
        )

    member = _get_member_or_404(db, workspace_id, user_id, org.id)
    before_role = member.role
    member.role = body.role

    target_user = db.query(User).filter(User.id == user_id).first()

    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.ROLE_CHANGE,
        workspace_id=workspace_id,
        target_type="user",
        target_id=user_id,
        target_name=target_user.name if target_user else user_id,
        before_state={"role": before_role},
        after_state={"role": body.role},
    )

    db.commit()
    db.refresh(member)
    logger.info(
        "Role updated for user %s in workspace %s: %s -> %s",
        user_id,
        workspace_id,
        before_role,
        body.role,
    )
    return _member_to_response(db, member)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from the workspace (admin only)",
)
def remove_member(
    workspace_id: str,
    user_id: str,
    db: DBSession,
    user: CurrentUser,
    org: CurrentOrg,
    _admin: RequireAdmin,
) -> None:
    """Remove a member from the workspace. Requires admin role.

    Restrictions:
    - Cannot remove the org owner.
    - Cannot remove yourself (admin must transfer admin role first).
    """
    if getattr(org, "owner_user_id", None) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the organization owner from a workspace",
        )
    if user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove yourself. Transfer admin role first.",
        )

    member = _get_member_or_404(db, workspace_id, user_id, org.id)
    target_user = db.query(User).filter(User.id == user_id).first()

    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MEMBER_REMOVE,
        workspace_id=workspace_id,
        target_type="user",
        target_id=user_id,
        target_name=target_user.name if target_user else user_id,
        metadata={"removed_role": member.role},
    )

    db.delete(member)
    db.commit()
    logger.info("Removed user %s from workspace %s", user_id, workspace_id)
