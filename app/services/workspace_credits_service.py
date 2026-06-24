"""Workspace credit pool service.

Manages credit budget allocation to workspace pools and atomic credit
deduction during solve operations.

Design:
- One pool per workspace (WorkspaceCreditPool, unique on workspace_id).
- Credits flow one-way: org.credits_balance → pool.allocated_credits.
- Deduction order: pool first (if available), fall back to org balance.
- Atomic deduction uses SQLAlchemy UPDATE WHERE to avoid race conditions
  (Pitfall #5 in the Phase 4 research document).
- Threshold alerts notify workspace admins at 70%, 75%, 80%, 85%, 90%, 95%, 100%.
- No function commits — callers commit atomically.
"""

import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.audit_log import AuditAction
from app.models.notification import NotificationChannel, NotificationType
from app.models.organization import Organization
from app.models.workspace import WorkspaceMember, WorkspaceRole
from app.models.workspace_credits import WorkspaceCreditPool
from app.services.audit_service import log_action
from app.services.notification_service import NotificationService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# Usage percentage thresholds at which workspace admins are notified.
ALERT_THRESHOLDS = [70, 75, 80, 85, 90, 95, 100]


def allocate_credits_to_pool(
    db: Session,
    org: Organization,
    workspace_id: str,
    amount: int,
    actor: Any = None,
) -> WorkspaceCreditPool:
    """Transfer credits from org.credits_balance into a workspace pool.

    Creates the pool if it does not yet exist for the workspace.

    Args:
        db: SQLAlchemy session. Does NOT commit — caller commits.
        org: Organization to deduct from.
        workspace_id: Target workspace ID.
        amount: Number of credits to allocate. Must be > 0.
        actor: User performing the allocation (for audit log). Optional.

    Returns:
        The updated WorkspaceCreditPool instance.

    Raises:
        ValueError: If amount <= 0 or org has insufficient credits.
    """
    if amount <= 0:
        raise ValueError("Allocation amount must be greater than zero")

    if org.credits_balance < amount:
        raise ValueError(
            f"Insufficient organization credits: need {amount}, have {org.credits_balance}"
        )

    pool = (
        db.query(WorkspaceCreditPool)
        .filter(
            WorkspaceCreditPool.workspace_id == workspace_id,
            WorkspaceCreditPool.organization_id == org.id,
        )
        .first()
    )

    if pool is None:
        pool = WorkspaceCreditPool(
            id=generate_id("wcp_"),
            workspace_id=workspace_id,
            organization_id=org.id,
            allocated_credits=0,
            used_credits=0,
            last_alert_threshold=None,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(pool)

    # Use record_transaction for audit trail (FIN-02) instead of direct mutation.
    # record_transaction handles the balance update internally with SELECT FOR UPDATE.
    from app.models import TransactionType
    from app.services.credits_service import CreditsService

    cs = CreditsService(db)
    cs.record_transaction(
        organization_id=org.id,
        transaction_type=TransactionType.ADJUSTMENT,
        credits_amount=-amount,
        description=(f"Workspace pool allocation: {amount} credits to workspace {workspace_id}"),
        reference_type="workspace_pool",
        reference_id=workspace_id,
        created_by=actor.id if actor and hasattr(actor, "id") else "system",
    )
    pool.allocated_credits += amount
    # Reset alert threshold — pool was topped up
    pool.last_alert_threshold = None

    if actor is not None:
        log_action(
            db=db,
            organization_id=org.id,
            actor=actor,
            action=AuditAction.POOL_ALLOCATE,
            workspace_id=workspace_id,
            target_type="credits",
            target_id=pool.id,
            metadata={
                "amount": amount,
                "new_allocated": pool.allocated_credits,
                "org_balance_after": org.credits_balance,
            },
        )

    logger.info(
        "Allocated %d credits to workspace pool %s (org %s)",
        amount,
        workspace_id,
        org.id,
    )
    return pool


def deduct_credits_for_solve(
    db: Session,
    org: Organization,
    workspace_id: str | None,
    credits_needed: int,
) -> str:
    """Deduct credits for a solve operation.

    Priority:
    1. Workspace pool (if workspace_id provided and pool has sufficient credits).
    2. Org balance fallback (if pool is exhausted, missing, or workspace_id is None).

    Uses an atomic SQL UPDATE WHERE to prevent concurrent over-deduction
    (race-condition-safe for the pool path).

    Args:
        db: SQLAlchemy session. Does NOT commit — caller commits.
        org: Organization whose balance may be used as fallback.
        workspace_id: Workspace context for the solve. None = org-level solve.
        credits_needed: Credits to deduct. Must be > 0.

    Returns:
        "pool" if the workspace pool was charged.
        "org_balance" if the org balance was charged.

    Raises:
        ValueError: If neither pool nor org balance has sufficient credits.
    """
    if workspace_id is not None:
        # Attempt atomic pool deduction using UPDATE WHERE (avoids race conditions)
        result = db.execute(
            update(WorkspaceCreditPool)
            .where(
                WorkspaceCreditPool.workspace_id == workspace_id,
                (WorkspaceCreditPool.allocated_credits - WorkspaceCreditPool.used_credits)
                >= credits_needed,
            )
            .values(used_credits=WorkspaceCreditPool.used_credits + credits_needed)
        )

        if result.rowcount > 0:  # type: ignore[attr-defined]
            # Pool deduction succeeded — check thresholds and return
            _check_pool_threshold(db, workspace_id, org.id)
            logger.debug(
                "Deducted %d credits from pool for workspace %s",
                credits_needed,
                workspace_id,
            )
            return "pool"

        # Pool exhausted or no pool exists — fall through to org balance
        logger.debug(
            "Pool exhausted for workspace %s — falling back to org balance",
            workspace_id,
        )

    # Org balance fallback — use record_transaction for audit trail (FIN-02)
    from app.models import TransactionType
    from app.services.credits_service import CreditsService, InsufficientCreditsError

    cs = CreditsService(db)
    try:
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-credits_needed,
            description="Workspace pool fallback: org balance deduction for solve",
            reference_type="workspace_solve",
            reference_id=workspace_id if workspace_id else None,
            created_by="system",
        )
    except InsufficientCreditsError as e:
        raise ValueError(
            f"Insufficient credits: need {credits_needed}, org balance {org.credits_balance}"
        ) from e
    logger.debug(
        "Deducted %d credits from org balance for org %s",
        credits_needed,
        org.id,
    )
    return "org_balance"


def _check_pool_threshold(db: Session, workspace_id: str, org_id: str) -> None:
    """Check if usage has crossed an alert threshold and notify workspace admins.

    Loads the pool, calculates used percentage, and fires an in-app
    notification to all workspace admins (and the org owner if distinct)
    for the first uncrossed threshold found.

    Does NOT commit — operates within the caller's transaction.

    Args:
        db: SQLAlchemy session.
        workspace_id: Workspace whose pool to check.
        org_id: Organization ID (for notification scoping).
    """
    pool = (
        db.query(WorkspaceCreditPool)
        .filter(WorkspaceCreditPool.workspace_id == workspace_id)
        .first()
    )

    if pool is None or pool.allocated_credits == 0:
        return

    used_pct = int((pool.used_credits / pool.allocated_credits) * 100)
    last_alerted = pool.last_alert_threshold or 0

    threshold_to_alert: int | None = None
    for threshold in ALERT_THRESHOLDS:
        if used_pct >= threshold and last_alerted < threshold:
            threshold_to_alert = threshold
            break  # Only alert the next threshold, not all at once

    if threshold_to_alert is None:
        return

    pool.last_alert_threshold = threshold_to_alert

    # Notify workspace admins via in-app notification
    admin_members = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.ADMIN.value,
        )
        .all()
    )

    notification_svc = NotificationService(db)
    available = pool.allocated_credits - pool.used_credits

    for member in admin_members:
        try:
            notification_svc.create_notification(
                user_id=member.user_id,
                organization_id=org_id,
                notification_type=NotificationType.CREDITS_LOW,
                title=f"Workspace credit pool at {threshold_to_alert}%",
                message=(
                    f"The credit pool for workspace has reached {threshold_to_alert}% usage. "
                    f"{available} credits remaining out of {pool.allocated_credits} allocated."
                ),
                data={
                    "workspace_id": workspace_id,
                    "threshold": threshold_to_alert,
                    "used_credits": pool.used_credits,
                    "allocated_credits": pool.allocated_credits,
                    "available_credits": available,
                },
                channel=NotificationChannel.IN_APP,
            )
        except Exception as exc:
            # Notification failure should not block the solve
            logger.warning(
                "Failed to send pool threshold notification to user %s: %s",
                member.user_id,
                exc,
            )

    logger.info(
        "Pool threshold alert sent: workspace=%s threshold=%d%% used=%d allocated=%d",
        workspace_id,
        threshold_to_alert,
        pool.used_credits,
        pool.allocated_credits,
    )
