"""Withdrawal models for credit cashout system."""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class WithdrawalStatus(str, Enum):
    """Status of a withdrawal request."""

    PENDING = "pending"  # Waiting to be processed
    PROCESSING = "processing"  # Being processed
    COMPLETED = "completed"  # Successfully transferred
    FAILED = "failed"  # Transfer failed
    CANCELLED = "cancelled"  # Cancelled by user or admin


class WithdrawalType(str, Enum):
    """Type of withdrawal."""

    MANUAL = "manual"  # One-time manual withdrawal
    SCHEDULED = "scheduled"  # From a scheduled withdrawal


class ScheduleFrequency(str, Enum):
    """Frequency for scheduled withdrawals."""

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class ScheduleAmountType(str, Enum):
    """How to calculate the withdrawal amount."""

    FIXED = "fixed"  # Fixed amount of credits
    PERCENTAGE = "percentage"  # Percentage of available credits
    ALL = "all"  # All available credits


class WithdrawalSchedule(Base):
    """Scheduled automatic withdrawals for an organization."""

    __tablename__ = "withdrawal_schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    # Schedule configuration
    frequency: Mapped[str] = mapped_column(
        String, nullable=False
    )  # weekly, biweekly, monthly, quarterly
    amount_type: Mapped[str] = mapped_column(String, nullable=False)  # fixed, percentage, all
    amount_value: Mapped[float] = mapped_column(
        Float, nullable=True
    )  # credits if fixed, % if percentage

    # Minimum threshold (only withdraw if credits_earned >= this)
    min_threshold: Mapped[int] = mapped_column(Integer, default=100)

    # Next scheduled execution
    next_execution: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:
        return f"<WithdrawalSchedule(org={self.organization_id}, freq={self.frequency}, active={self.is_active})>"


class Withdrawal(Base):
    """Record of a credit withdrawal (conversion to fiat currency)."""

    __tablename__ = "withdrawals"

    id: Mapped[str] = mapped_column(String, primary_key=True)

    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    # Optional link to schedule (if scheduled withdrawal)
    schedule_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("withdrawal_schedules.id"),
        nullable=True,
    )

    # Type
    withdrawal_type: Mapped[str] = mapped_column(String, nullable=False)  # manual, scheduled

    # Credits withdrawn
    credits_amount: Mapped[int] = mapped_column(Integer, nullable=False)

    # Conversion details (at time of withdrawal)
    credits_per_eur: Mapped[int] = mapped_column(Integer, default=10)  # Fixed: 10 credits = 1 EUR
    eur_amount: Mapped[float] = mapped_column(Float, nullable=False)  # credits / credits_per_eur

    # Target currency conversion
    target_currency: Mapped[str] = mapped_column(String(3), nullable=False)  # EUR, USD, GBP, CHF
    exchange_rate: Mapped[float] = mapped_column(Float, nullable=False)  # EUR -> target rate used
    local_amount: Mapped[float] = mapped_column(
        Float, nullable=False
    )  # Final amount in target currency

    # Status
    status: Mapped[str] = mapped_column(
        String, default="pending"
    )  # pending, processing, completed, failed, cancelled

    # Processing details
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_reference: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Bank reference

    # Stripe Connect payout reference
    stripe_transfer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def __repr__(self) -> str:
        return f"<Withdrawal(id={self.id}, credits={self.credits_amount}, status={self.status})>"
