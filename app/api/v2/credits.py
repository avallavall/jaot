"""Credits and withdrawals API endpoints."""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_monetization_enabled
from app.api.v2.auth import get_current_user
from app.models import (
    CREDITS_PER_EUR,
    Organization,
    ScheduleAmountType,
    ScheduleFrequency,
    User,
)
from app.services.credits_service import CreditsService
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credits", tags=["credits"])


# SCHEMAS (endpoint-specific with currency conversion fields)


class ExchangeRateResponse(BaseModel):
    currency: str
    rate: float
    rate_date: str
    credits_per_eur: int = CREDITS_PER_EUR


class AllRatesResponse(BaseModel):
    rates: dict[str, Any]
    rate_date: str
    credits_per_eur: int = CREDITS_PER_EUR


class CreditBalanceResponse(BaseModel):
    credits_balance: int
    credits_subscription: int = 0
    credits_purchased: int = 0
    credits_earned: int = 0
    currency: str
    local_balance: float
    local_earned: float
    exchange_rate: float
    credits_per_eur: int = CREDITS_PER_EUR


class TransactionResponse(BaseModel):
    id: str
    transaction_type: str | None = None
    credits_amount: int | None = None
    balance_after: int | None = None
    earned_balance_after: int | None = 0
    description: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    amount_eur: float | None = None
    created_at: str

    # Legacy fields for old transactions
    package_name: str | None = None
    total_credits: int | None = None


class WithdrawalRequest(BaseModel):
    credits_amount: int = Field(..., gt=0, description="Amount of credits to withdraw")


class WithdrawalResponse(BaseModel):
    id: str
    withdrawal_type: str
    credits_amount: int
    eur_amount: float
    target_currency: str
    exchange_rate: float
    local_amount: float
    status: str
    created_at: str
    processed_at: str | None
    failure_reason: str | None
    transaction_reference: str | None


class ScheduleRequest(BaseModel):
    frequency: str = Field(..., description="weekly, biweekly, monthly, quarterly")
    amount_type: str = Field(..., description="fixed, percentage, all")
    amount_value: float | None = Field(None, description="Credits if fixed, % if percentage")
    min_threshold: int = Field(100, ge=0, description="Minimum credits to trigger withdrawal")


class ScheduleResponse(BaseModel):
    id: str
    frequency: str
    amount_type: str
    amount_value: float | None
    min_threshold: int
    next_execution: str
    is_active: bool
    created_at: str


class CurrencyRequest(BaseModel):
    currency: str = Field(..., pattern="^(EUR|USD|GBP|CHF)$")


@router.get("/rates", response_model=AllRatesResponse)
async def get_exchange_rates(
    rate_date: str | None = Query(None, description="Date in YYYY-MM-DD format"),
    db: Session = Depends(get_db),
) -> AllRatesResponse:
    """Get all exchange rates for a date."""
    service = CreditsService(db)

    parsed_date = None
    if rate_date:
        try:
            parsed_date = date.fromisoformat(rate_date)
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
            ) from e

    rates = service.get_all_rates(parsed_date)

    return AllRatesResponse(
        rates=rates,
        rate_date=(parsed_date or date.today()).isoformat(),
        credits_per_eur=CREDITS_PER_EUR,
    )


@router.get("/rates/{currency}", response_model=ExchangeRateResponse)
async def get_exchange_rate(
    currency: str,
    rate_date: str | None = Query(None),
    db: Session = Depends(get_db),
) -> ExchangeRateResponse:
    """Get exchange rate for a specific currency."""
    if currency not in ["EUR", "USD", "GBP", "CHF"]:
        raise HTTPException(status_code=400, detail="Unsupported currency")

    service = CreditsService(db)

    parsed_date = None
    if rate_date:
        try:
            parsed_date = date.fromisoformat(rate_date)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Invalid date format") from e

    rate = service.get_exchange_rate(currency, parsed_date)

    return ExchangeRateResponse(
        currency=currency,
        rate=rate,
        rate_date=(parsed_date or date.today()).isoformat(),
    )


@router.get("/balance", response_model=CreditBalanceResponse, operation_id="get_credit_balance")
async def get_credit_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditBalanceResponse:
    """Get current credit balance for the organization."""
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    service = CreditsService(db)

    local_balance, rate = service.credits_to_currency(org.credits_balance, org.currency)
    local_earned, _ = service.credits_to_currency(org.credits_earned, org.currency)

    return CreditBalanceResponse(
        credits_balance=org.credits_balance,
        credits_subscription=getattr(org, "credits_subscription", 0) or 0,
        credits_purchased=getattr(org, "credits_purchased", 0) or 0,
        credits_earned=org.credits_earned,
        currency=org.currency,
        local_balance=local_balance,
        local_earned=local_earned,
        exchange_rate=rate,
    )


@router.get("/transactions", response_model=list[TransactionResponse])
async def get_transactions(
    transaction_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TransactionResponse]:
    """Get credit transaction history."""
    service = CreditsService(db)

    transactions = service.get_transaction_history(
        organization_id=current_user.organization_id,
        transaction_type=transaction_type,
        limit=limit,
        offset=offset,
    )

    result = []
    for tx in transactions:
        # Handle legacy transactions that may have old schema
        tx_type = getattr(tx, "transaction_type", None)
        credits_amt = getattr(tx, "credits_amount", None)

        # For legacy transactions, try to get from old fields
        if credits_amt is None:
            credits_amt = getattr(tx, "total_credits", None)
        if tx_type is None:
            tx_type = "purchase"  # Legacy transactions were purchases

        result.append(
            TransactionResponse(
                id=tx.id,
                transaction_type=tx_type,
                credits_amount=credits_amt,
                balance_after=getattr(tx, "balance_after", None),
                earned_balance_after=getattr(tx, "earned_balance_after", 0) or 0,
                description=getattr(tx, "description", None)
                or getattr(tx, "package_name", "Credit transaction"),
                reference_type=getattr(tx, "reference_type", None),
                reference_id=getattr(tx, "reference_id", None),
                amount_eur=getattr(tx, "amount_eur", None) or getattr(tx, "amount_eur", None),
                created_at=tx.created_at.isoformat(),
                package_name=getattr(tx, "package_name", None),
                total_credits=getattr(tx, "total_credits", None),
            )
        )
    return result


@router.post(
    "/withdrawals",
    response_model=WithdrawalResponse,
    dependencies=[Depends(require_monetization_enabled)],
)
async def create_withdrawal(
    body: WithdrawalRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WithdrawalResponse:
    """Create a manual withdrawal request."""
    # D-16: Seller ToS must be accepted before first withdrawal
    from app.services.stripe_connect_service import StripeConnectService

    tos_service = StripeConnectService(db)
    if not tos_service.has_accepted_seller_tos(current_user.organization_id):
        raise HTTPException(
            status_code=403,
            detail="You must accept the Seller Terms of Service before withdrawing",
        )

    service = CreditsService(db)

    try:
        withdrawal = service.create_withdrawal(
            organization_id=current_user.organization_id,
            credits_amount=body.credits_amount,
            created_by=current_user.id,
        )
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Fire-and-forget: log credit.withdrawal analytics event
    try:
        from app.services.analytics_service import AnalyticsService
        from app.shared.constants import event_types as evt

        analytics = AnalyticsService(db)
        analytics.log_event(
            user_id=current_user.id,
            org_id=current_user.organization_id,
            event_type=evt.CREDIT_WITHDRAWAL,
            ip_address=request.client.host if request.client else None,
            metadata={
                "credits_amount": withdrawal.credits_amount,
                "eur_amount": withdrawal.eur_amount,
            },
        )
    except Exception:
        logger.debug("Failed to log analytics event", exc_info=True)

    return WithdrawalResponse(
        id=withdrawal.id,
        withdrawal_type=withdrawal.withdrawal_type,
        credits_amount=withdrawal.credits_amount,
        eur_amount=withdrawal.eur_amount,
        target_currency=withdrawal.target_currency,
        exchange_rate=withdrawal.exchange_rate,
        local_amount=withdrawal.local_amount,
        status=withdrawal.status,
        created_at=withdrawal.created_at.isoformat(),
        processed_at=withdrawal.processed_at.isoformat() if withdrawal.processed_at else None,
        failure_reason=withdrawal.failure_reason,
        transaction_reference=withdrawal.transaction_reference,
    )


@router.get(
    "/withdrawals",
    response_model=list[WithdrawalResponse],
    dependencies=[Depends(require_monetization_enabled)],
)
async def get_withdrawals(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WithdrawalResponse]:
    """Get withdrawal history."""
    service = CreditsService(db)

    withdrawals = service.get_withdrawals(
        organization_id=current_user.organization_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    return [
        WithdrawalResponse(
            id=w.id,
            withdrawal_type=w.withdrawal_type,
            credits_amount=w.credits_amount,
            eur_amount=w.eur_amount,
            target_currency=w.target_currency,
            exchange_rate=w.exchange_rate,
            local_amount=w.local_amount,
            status=w.status,
            created_at=w.created_at.isoformat(),
            processed_at=w.processed_at.isoformat() if w.processed_at else None,
            failure_reason=w.failure_reason,
            transaction_reference=w.transaction_reference,
        )
        for w in withdrawals
    ]


@router.post(
    "/schedules",
    response_model=ScheduleResponse,
    dependencies=[Depends(require_monetization_enabled)],
)
async def create_withdrawal_schedule(
    request: ScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScheduleResponse:
    """Create a scheduled withdrawal."""
    service = CreditsService(db)

    try:
        frequency = ScheduleFrequency(request.frequency)
        amount_type = ScheduleAmountType(request.amount_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid frequency or amount_type") from e

    try:
        schedule = service.create_withdrawal_schedule(
            organization_id=current_user.organization_id,
            frequency=frequency,
            amount_type=amount_type,
            amount_value=request.amount_value,
            min_threshold=request.min_threshold,
        )
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return ScheduleResponse(
        id=schedule.id,
        frequency=schedule.frequency,
        amount_type=schedule.amount_type,
        amount_value=schedule.amount_value,
        min_threshold=schedule.min_threshold,
        next_execution=schedule.next_execution.isoformat(),
        is_active=schedule.is_active,
        created_at=schedule.created_at.isoformat(),
    )


@router.get(
    "/schedules",
    response_model=list[ScheduleResponse],
    dependencies=[Depends(require_monetization_enabled)],
)
async def get_withdrawal_schedules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ScheduleResponse]:
    """Get all withdrawal schedules for the organization."""
    from app.models import WithdrawalSchedule

    schedules = (
        db.query(WithdrawalSchedule)
        .filter(WithdrawalSchedule.organization_id == current_user.organization_id)
        .all()
    )

    return [
        ScheduleResponse(
            id=s.id,
            frequency=s.frequency,
            amount_type=s.amount_type,
            amount_value=s.amount_value,
            min_threshold=s.min_threshold,
            next_execution=s.next_execution.isoformat(),
            is_active=s.is_active,
            created_at=s.created_at.isoformat(),
        )
        for s in schedules
    ]


@router.delete(
    "/schedules/{schedule_id}",
    dependencies=[Depends(require_monetization_enabled)],
)
async def delete_withdrawal_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Delete (deactivate) a withdrawal schedule."""
    from app.models import WithdrawalSchedule

    schedule = (
        db.query(WithdrawalSchedule)
        .filter(
            WithdrawalSchedule.id == schedule_id,
            WithdrawalSchedule.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    schedule.is_active = False
    db.commit()

    return {"status": "deleted"}


@router.put("/settings/currency")
async def update_currency(
    request: CurrencyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update organization's preferred currency."""
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.currency = request.currency
    db.commit()

    return {"status": "updated", "currency": org.currency}


class CreditCalculatorRequest(BaseModel):
    num_variables: int = Field(ge=0, le=10_000_000, description="Number of decision variables")
    num_integer_vars: int = Field(default=0, ge=0, description="Number of integer variables")
    num_binary_vars: int = Field(default=0, ge=0, description="Number of binary variables")
    num_constraints: int = Field(
        default=0, ge=0, le=10_000_000, description="Number of constraints"
    )
    time_limit_seconds: float = Field(
        default=60, ge=1, le=3600, description="Time limit in seconds"
    )


class CreditCalculatorResponse(BaseModel):
    credits_required: int
    breakdown: dict[str, Any]
    cost_eur: float
    cost_by_plan: dict[str, Any]


@router.post("/calculator")
async def calculate_credits_endpoint(body: CreditCalculatorRequest) -> CreditCalculatorResponse:
    """Public credit calculator. Estimate credits without authentication.

    Uses the same ``compute_credits`` formula as the solve endpoint
    (sqrt scaling + per-solve cap) to guarantee consistent estimates.
    """
    from app.api.v2.solve import compute_credits

    num_integer_binary = body.num_integer_vars + body.num_binary_vars
    total, breakdown = compute_credits(
        num_variables=body.num_variables,
        num_integer_binary=num_integer_binary,
        num_constraints=body.num_constraints,
        time_limit_seconds=body.time_limit_seconds,
    )

    # Cost per credit by plan
    cost_per_credit = {
        "free": 0,
        "starter": 0.019,
        "pro": 0.016,
        "topup_500": 0.028,
        "topup_2000": 0.024,
        "topup_5000": 0.020,
        "topup_20000": 0.016,
    }

    return CreditCalculatorResponse(
        credits_required=total,
        breakdown=breakdown,
        cost_eur=round(total * 0.016, 4),
        cost_by_plan={
            plan: round(total * rate, 4) if rate > 0 else 0
            for plan, rate in cost_per_credit.items()
        },
    )


@router.get("/settings")
async def get_credit_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get organization's credit settings."""
    org = db.query(Organization).filter(Organization.id == current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    return {
        "currency": org.currency,
        "billing_email": org.billing_email,
    }
