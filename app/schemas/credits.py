"""Credits and transactions schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExchangeRateResponse(BaseModel):
    """Exchange rate response."""

    currency: str
    credits_per_unit: float
    min_purchase: int
    max_purchase: int


class AllRatesResponse(BaseModel):
    """All exchange rates response."""

    rates: list[ExchangeRateResponse]
    default_currency: str = "EUR"


class CreditBalanceResponse(BaseModel):
    """Credit balance response."""

    credits_balance: int
    credits_earned: int
    credits_used_month: int
    plan: str
    monthly_limit: int | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionResponse(BaseModel):
    """Credit transaction response."""

    id: str
    transaction_type: str
    credits_amount: int
    balance_after: int
    description: str
    reference_type: str | None = None
    reference_id: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransactionListResponse(BaseModel):
    """Paginated transaction list."""

    items: list[TransactionResponse]
    total: int
    page: int
    page_size: int


class WithdrawalRequest(BaseModel):
    """Withdrawal request schema."""

    credits_amount: int = Field(..., gt=0)
    currency: str = "EUR"


class WithdrawalResponse(BaseModel):
    """Withdrawal response schema."""

    id: str
    credits_amount: int
    currency: str
    amount_fiat: float
    status: str
    created_at: datetime
    processed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ScheduleRequest(BaseModel):
    """Withdrawal schedule request."""

    frequency: str = Field(..., pattern="^(weekly|monthly)$")
    amount_type: str = Field(..., pattern="^(fixed|percentage|all)$")
    amount_value: int | None = None


class ScheduleResponse(BaseModel):
    """Withdrawal schedule response."""

    id: str
    frequency: str
    amount_type: str
    amount_value: int | None = None
    is_active: bool
    next_execution: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CurrencyRequest(BaseModel):
    """Currency preference request."""

    currency: str = Field(..., pattern="^(EUR|USD|GBP)$")


class CreditAdjustment(BaseModel):
    """Admin credit adjustment request."""

    credits_amount: int
    description: str = "Admin adjustment"
