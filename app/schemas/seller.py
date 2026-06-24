"""Pydantic schemas for seller earnings and notification preference API responses."""

from datetime import datetime

from pydantic import BaseModel


class EarningsSummaryResponse(BaseModel):
    """Summary of seller earnings."""

    total_sales: int  # Count of sales
    total_earned: int  # Sum of SALE_EARNING credits (all-time)
    total_commission: int  # Sum of commission credits (from amount_eur on COMMISSION txns)
    withdrawable_balance: int  # Matured earnings minus completed withdrawals
    pending_maturation: int = 0  # Earnings still in holding period
    pending_withdrawals: int  # Sum of pending withdrawal credits
    commission_rate: float  # Current platform commission rate


class SaleRecord(BaseModel):
    """Individual sale record with commission breakdown."""

    sale_id: str  # Transaction ID
    model_id: str | None
    model_name: str | None
    buyer_organization_name: str | None
    credits_price: int  # Full price buyer paid
    commission_amount: int  # Commission taken
    seller_earning: int  # What seller received
    created_at: datetime


class SalesHistoryResponse(BaseModel):
    """Paginated sales history."""

    items: list[SaleRecord]
    total: int
    page: int
    page_size: int


# --- Notification Preferences ---


class NotificationPreferenceEntry(BaseModel):
    """Single notification preference entry."""

    event_type: str  # "sale", "review", "payout", "promotion_expiring"
    channel: str  # "in_app" or "email"
    enabled: bool


class NotificationPreferencesResponse(BaseModel):
    """All notification preferences for a user (4 events x 2 channels = 8 entries)."""

    preferences: list[NotificationPreferenceEntry]


class UpdatePreferenceRequest(BaseModel):
    """Request to update a single notification preference."""

    event_type: str
    channel: str
    enabled: bool


# --- Onboarding ---


class OnboardingStep(BaseModel):
    """A single onboarding checklist step."""

    key: str
    completed: bool
    link: str


class OnboardingStatusResponse(BaseModel):
    """Onboarding checklist status for a seller."""

    steps: list[OnboardingStep]
    all_complete: bool
