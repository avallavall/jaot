"""Admin credit management endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.models import CreditTransaction, Organization, TransactionType
from app.schemas.admin import CreditAdjustment
from app.services.credits_service import CreditsService
from app.shared.db.base import get_db
from app.shared.utils.pagination import paginate_query

router = APIRouter(tags=["admin-credits"])


@router.post("/credits/adjust")
async def adjust_credits(
    data: CreditAdjustment,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually adjust organization credits."""
    org = db.query(Organization).filter(Organization.id == data.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    old_balance = org.credits_balance
    new_balance = old_balance + data.amount
    if new_balance < 0:
        raise HTTPException(status_code=400, detail="Cannot set negative balance")

    # Get admin user from request context (set by auth middleware)
    admin_user = getattr(request.state, "user", None)
    admin_user_id = admin_user.id if admin_user else "unknown_admin"

    service = CreditsService(db)
    transaction = service.record_transaction(
        organization_id=data.organization_id,
        transaction_type=TransactionType.ADJUSTMENT,
        credits_amount=data.amount,
        description=f"Admin adjustment: {data.reason}",
        created_by=admin_user_id,
    )
    db.commit()

    return {
        "id": transaction.id,
        "organization_id": transaction.organization_id,
        "amount": data.amount,
        "balance_after": transaction.balance_after,
        "transaction_type": "adjustment",
        "description": data.reason,
        "created_at": transaction.created_at.isoformat(),
    }


@router.get("/credits/transactions")
async def list_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    organization_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List credit transactions."""
    query = db.query(CreditTransaction)

    if organization_id:
        query = query.filter(CreditTransaction.organization_id == organization_id)

    query = query.order_by(CreditTransaction.created_at.desc())

    items, total = paginate_query(query, page, page_size)

    transformed_items = []
    for t in items:
        transformed_items.append(
            {
                "id": t.id,
                "organization_id": t.organization_id,
                "amount": t.credits_amount,
                "balance_after": t.balance_after,
                "transaction_type": t.transaction_type,
                "description": t.description,
                "created_at": t.created_at.isoformat(),
            }
        )

    return {
        "items": transformed_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }
