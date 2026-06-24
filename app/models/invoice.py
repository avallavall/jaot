"""Invoice model for billing records."""

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    VOID = "void"


class InvoiceType(str, Enum):
    SUBSCRIPTION = "subscription"
    TOPUP = "topup"
    ADJUSTMENT = "adjustment"


class Invoice(Base):
    """Invoice record for credit purchases and subscriptions."""

    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Type & status
    invoice_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="issued", nullable=False)

    # Dates
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Organization details (snapshot at time of invoice)
    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    org_plan: Mapped[str] = mapped_column(String(30), nullable=False)

    # Line items (JSON array)
    line_items: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Totals
    subtotal_eur: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tax_amount_eur: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_eur: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Currency conversion
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    exchange_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    total_local: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Credits
    credits_granted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Payment reference
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Notes
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, number={self.invoice_number}, total={self.total_eur}€)>"
