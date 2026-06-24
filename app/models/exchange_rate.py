"""Exchange rate model for currency conversions.

Base currency is EUR. All rates are stored as EUR -> target currency.
Example: rate=1.16 for USD means 1 EUR = 1.16 USD
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base
from app.shared.utils.datetime_helpers import utcnow


class ExchangeRate(Base):
    """Daily exchange rates with EUR as base currency.

    The platform uses credits internally:
    - 1 EUR = 10 credits (fixed rate)
    - Exchange rates convert EUR to local currencies for display/withdrawal
    """

    __tablename__ = "exchange_rates"
    __table_args__ = (UniqueConstraint("currency", "rate_date", name="uq_currency_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Currency code (USD, GBP, CHF)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)

    # Rate date (one rate per currency per day)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Exchange rate: 1 EUR = X currency
    rate: Mapped[float] = mapped_column(Float, nullable=False)

    # Source of the rate (for auditing)
    source: Mapped[str] = mapped_column(String, default="manual")  # manual, ecb, api

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def __repr__(self) -> str:
        return f"<ExchangeRate(EUR/{self.currency}={self.rate} on {self.rate_date})>"


# Fixed rate: 1 EUR = 10 credits
CREDITS_PER_EUR = 10
