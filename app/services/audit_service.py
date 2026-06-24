"""Audit logging service.

Provides log_action() for recording user actions in the audit log.

Design contract:
- log_action() calls db.add() but NEVER db.commit().
- The calling route handler is responsible for committing the transaction.
- This ensures the audit entry and the action it records are atomic:
  if the main transaction rolls back, the audit entry is also discarded.
  (Pitfall #4 in the Phase 4 research document.)

Usage:
    from app.services.audit_service import log_action
    from app.models.audit_log import AuditAction

    # Inside a route handler:
    log_action(
        db=db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.MEMBER_REMOVE,
        workspace_id=workspace_id,
        target_type="user",
        target_id=target_user_id,
        target_name=target_user.name,
        metadata={"removed_role": member.role},
    )
    db.delete(member)
    db.commit()  # commits both the deletion and the audit log entry atomically
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction, AuditLog
from app.models.user import User
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)


def log_action(
    db: Session,
    organization_id: str,
    actor: User | None,
    action: AuditAction,
    workspace_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    actor_id_override: str | None = None,
    actor_name_override: str | None = None,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> AuditLog:
    """Create an audit log entry within the caller's transaction.

    Args:
        db: SQLAlchemy session. The entry is added via db.add() only —
            commit is the caller's responsibility.
        organization_id: ID of the organization in which the action occurred.
        actor: User who performed the action. actor_name is captured as a
            denormalized snapshot so the log remains readable even if the
            user account is later deleted. May be None for system-initiated
            actions (e.g., trigger fire) — use actor_id_override and
            actor_name_override instead.
        action: AuditAction enum value describing what happened.
        workspace_id: ID of the workspace in which the action occurred.
            None for org-level actions (e.g., org settings changes).
        target_type: Human-readable category of the target entity
            (e.g., "model", "user", "workspace", "credits").
        target_id: ID of the target entity.
        target_name: Denormalized display name of the target entity.
        before_state: JSON snapshot of the entity's state before the action.
            Used for edit/delete actions to enable diff display.
        after_state: JSON snapshot of the entity's state after the action.
        metadata: Additional context (e.g., credit amount for POOL_ALLOCATE,
            error message for failed solves, input params, etc.).
        actor_id_override: Explicit actor ID when no User object is available
            (e.g., trigger fire uses trigger.created_by).
        actor_name_override: Explicit actor name when no User object is
            available (e.g., "trigger_system").

    Returns:
        The AuditLog instance added to the session (not yet committed).
    """
    resolved_actor_id = actor_id_override or (actor.id if actor else "system")
    resolved_actor_name = actor_name_override or (
        getattr(actor, "name", actor.id) if actor else "system"
    )

    # Truncate to column widths to prevent StringDataRightTruncation errors
    safe_target_id = target_id[:64] if target_id and len(target_id) > 64 else target_id
    safe_target_name = target_name[:255] if target_name and len(target_name) > 255 else target_name

    # Truncate reference_id to column width (same defensive pattern as target_id).
    safe_reference_id = (
        reference_id[:64] if reference_id and len(reference_id) > 64 else reference_id
    )

    entry = AuditLog(
        id=generate_id("aud_"),
        organization_id=organization_id,
        workspace_id=workspace_id,
        actor_id=resolved_actor_id,
        actor_name=resolved_actor_name,
        action=action.value,
        target_type=target_type,
        target_id=safe_target_id,
        target_name=safe_target_name,
        before_state=before_state,
        after_state=after_state,
        log_metadata=metadata,
        reference_type=reference_type,
        reference_id=safe_reference_id,
        created_at=utcnow(),
    )

    db.add(entry)
    logger.debug(
        "Audit entry queued: action=%s actor=%s org=%s workspace=%s",
        action.value,
        resolved_actor_id,
        organization_id,
        workspace_id,
    )
    return entry
