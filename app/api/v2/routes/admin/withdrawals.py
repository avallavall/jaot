"""Admin withdrawal processing endpoints (D-26).

List pending withdrawals, approve (triggers Stripe Connect payout), reject.
Manual reconciliation trigger uses ReconciliationService (shared with Celery task).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import Organization, Withdrawal, WithdrawalStatus
from app.services.credits_service import CreditsService
from app.services.stripe_connect_service import StripeConnectService
from app.shared.db.base import get_db
from app.shared.utils.pagination import paginate_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-withdrawals"])


class WithdrawalActionRequest(BaseModel):
    """Request body for withdrawal approve/reject."""

    reason: str | None = None


@router.get("/withdrawals")
async def list_withdrawals(
    status: str | None = Query(
        None,
        description="Filter by status: pending, processing, completed, failed, cancelled",
    ),
    organization_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List withdrawals, optionally filtered by status and organization."""
    query = db.query(Withdrawal)

    if status:
        query = query.filter(Withdrawal.status == status)
    if organization_id:
        query = query.filter(Withdrawal.organization_id == organization_id)

    query = query.order_by(Withdrawal.created_at.desc())
    items, total = paginate_query(query, page, page_size)

    return {
        "items": [
            {
                "id": w.id,
                "organization_id": w.organization_id,
                "withdrawal_type": w.withdrawal_type,
                "credits_amount": w.credits_amount,
                "eur_amount": w.eur_amount,
                "target_currency": w.target_currency,
                "local_amount": w.local_amount,
                "status": w.status,
                "stripe_transfer_id": w.stripe_transfer_id,
                "created_at": w.created_at.isoformat(),
                "processed_at": (w.processed_at.isoformat() if w.processed_at else None),
                "failure_reason": w.failure_reason,
            }
            for w in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("/withdrawals/{withdrawal_id}/approve")
async def approve_withdrawal(
    withdrawal_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve a pending withdrawal and trigger Stripe Connect payout (D-26).

    On approval:
    1. Validate withdrawal is in pending/processing status
    2. Verify org has completed Stripe Connect onboarding
    3. Verify org has accepted Seller ToS
    4. Create Stripe Transfer to seller's Connect account
    5. Update withdrawal status to completed
    """
    withdrawal = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal not found")

    if withdrawal.status not in [
        WithdrawalStatus.PENDING.value,
        WithdrawalStatus.PROCESSING.value,
    ]:
        raise HTTPException(
            status_code=400,
            detail=(f"Cannot approve withdrawal in status: {withdrawal.status}"),
        )

    org = db.query(Organization).filter(Organization.id == withdrawal.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Verify Stripe Connect onboarding
    if not org.stripe_connect_onboarding_complete:
        raise HTTPException(
            status_code=400,
            detail="Seller has not completed Stripe Connect onboarding",
        )

    # Verify Seller ToS acceptance (D-16)
    connect_service = StripeConnectService(db)
    if not connect_service.has_accepted_seller_tos(org.id):
        raise HTTPException(
            status_code=400,
            detail="Seller has not accepted the Seller Terms of Service",
        )

    # Execute Stripe payout
    try:
        transfer_id = connect_service.create_payout(
            org=org,
            amount_eur=withdrawal.eur_amount,
            withdrawal_id=withdrawal.id,
        )
    except Exception as e:
        logger.error(
            "Stripe payout failed for withdrawal %s: %s",
            withdrawal_id,
            e,
        )
        # Mark as failed
        credits_service = CreditsService(db)
        credits_service.process_withdrawal(
            withdrawal_id=withdrawal_id,
            success=False,
            failure_reason=f"Stripe payout failed: {str(e)[:200]}",
        )
        db.commit()
        raise HTTPException(
            status_code=502,
            detail=f"Stripe payout failed: {str(e)[:200]}",
        ) from e

    # Mark as completed
    credits_service = CreditsService(db)
    credits_service.process_withdrawal(
        withdrawal_id=withdrawal_id,
        success=True,
        transaction_reference=transfer_id,
    )
    withdrawal.stripe_transfer_id = transfer_id
    db.commit()

    admin_user = getattr(request.state, "user", None)
    admin_id = admin_user.id if admin_user else "unknown"
    logger.info(
        "Withdrawal %s approved by admin %s, transfer=%s",
        withdrawal_id,
        admin_id,
        transfer_id,
    )

    return {
        "id": withdrawal.id,
        "status": withdrawal.status,
        "stripe_transfer_id": transfer_id,
        "approved_by": admin_id,
    }


@router.post("/withdrawals/{withdrawal_id}/reject")
async def reject_withdrawal(
    withdrawal_id: str,
    body: WithdrawalActionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Reject a pending withdrawal and refund credits."""
    withdrawal = db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal not found")

    if withdrawal.status not in [
        WithdrawalStatus.PENDING.value,
        WithdrawalStatus.PROCESSING.value,
    ]:
        raise HTTPException(
            status_code=400,
            detail=(f"Cannot reject withdrawal in status: {withdrawal.status}"),
        )

    reason = body.reason or "Rejected by admin"

    # process_withdrawal with success=False refunds credits automatically
    credits_service = CreditsService(db)
    credits_service.process_withdrawal(
        withdrawal_id=withdrawal_id,
        success=False,
        failure_reason=reason,
    )
    db.commit()

    admin_user = getattr(request.state, "user", None)
    admin_id = admin_user.id if admin_user else "unknown"
    logger.info(
        "Withdrawal %s rejected by admin %s: %s",
        withdrawal_id,
        admin_id,
        reason,
    )

    return {
        "id": withdrawal.id,
        "status": withdrawal.status,
        "rejected_by": admin_id,
        "reason": reason,
    }


@router.post("/reconciliation/run")
async def trigger_reconciliation(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger balance reconciliation (D-25).

    Runs synchronously and returns results. For async execution,
    use the Celery beat task.
    Uses ReconciliationService -- same logic as the Celery task
    (no duplication).
    """
    from app.services.reconciliation_service import ReconciliationService

    service = ReconciliationService(db)
    return service.run_reconciliation()
