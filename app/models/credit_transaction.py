"""Credit transaction model for all credit movements."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class TransactionType(str, Enum):
    """Types of credit transactions."""

    # Inflows (positive)
    PURCHASE = "purchase"  # Bought credits with money
    SALE_EARNING = "sale_earning"  # Earned from marketplace sale
    BONUS = "bonus"  # Promotional bonus
    REFUND = "refund"  # Refund from failed execution
    TRANSFER_IN = "transfer_in"  # Transfer from another org

    # Outflows (negative)
    EXECUTION = "execution"  # Used for running a model
    WITHDRAWAL = "withdrawal"  # Converted to fiat currency
    TRANSFER_OUT = "transfer_out"  # Transfer to another org
    ADJUSTMENT = "adjustment"  # Admin adjustment
    COMMISSION = "commission"  # Platform commission from marketplace sale
    FEATURED_PLACEMENT = "featured_placement"  # Purchased featured placement
    REFUND_CLAWBACK = "refund_clawback"  # Credits clawed back on Stripe refund
    CHARGEBACK_REVERSAL = "chargeback_reversal"  # Credits reversed on chargeback


class CreditTransaction(Base):
    """Record of all credit movements for organizations.

    This is the complete audit trail of all credit changes.
    """

    __tablename__ = "credit_transactions"
    __table_args__ = (
        Index("ix_credit_txn_org_created", "organization_id", "created_at"),
        Index(
            "uq_credit_txn_reference",
            "organization_id",
            "transaction_type",
            "reference_type",
            "reference_id",
            unique=True,
            postgresql_where=text("reference_type IS NOT NULL AND reference_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Organization
    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    # Transaction type
    transaction_type: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Credits (positive for inflows, negative for outflows)
    credits_amount: Mapped[int] = mapped_column(Integer, nullable=False)

    # Balance after transaction (for easy auditing)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    earned_balance_after: Mapped[int] = mapped_column(
        Integer, default=0
    )  # For earned credits tracking

    # Description
    description: Mapped[str] = mapped_column(String, nullable=False)

    # Reference to related entity (model_id, withdrawal_id, etc.)
    reference_type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # model, withdrawal, purchase, etc.
    reference_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # For purchases: payment details
    amount_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String, nullable=True)

    # For marketplace sales: who bought it
    buyer_organization_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        nullable=False,
        index=True,
    )
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)  # user_id or "system"

    # Holding period: when SALE_EARNING becomes withdrawable (per D-10)
    available_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # Commission rate snapshot at time of sale (for audit, per success criterion 14)
    commission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    def __repr__(self) -> str:
        return f"<CreditTransaction(id={self.id}, type={self.transaction_type}, amount={self.credits_amount})>"
