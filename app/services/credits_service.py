"""Credits and exchange rate service.

Handles all credit operations, currency conversions, and withdrawals.

Base currency: EUR
Fixed rate: 1 EUR = 10 credits
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CREDITS_PER_EUR,
    CreditTransaction,
    ExchangeRate,
    Organization,
    ScheduleAmountType,
    ScheduleFrequency,
    TransactionType,
    Withdrawal,
    WithdrawalSchedule,
    WithdrawalStatus,
    WithdrawalType,
)
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)

# Default exchange rates (EUR base) - used when no rate in DB
DEFAULT_RATES = {
    "EUR": 1.0,
    "USD": 1.08,  # 1 EUR = 1.08 USD
    "GBP": 0.86,  # 1 EUR = 0.86 GBP
    "CHF": 0.94,  # 1 EUR = 0.94 CHF
}


class InsufficientCreditsError(Exception):
    """Raised when an organization does not have enough credits for an operation."""

    def __init__(self, credits_needed: int, credits_available: int):
        self.credits_needed = credits_needed
        self.credits_available = credits_available
        super().__init__(f"Insufficient credits: need {credits_needed}, have {credits_available}")


class CreditsService:
    """Service for managing credits, conversions, and withdrawals."""

    def __init__(self, db: Session):
        self.db = db

    def get_exchange_rate(self, currency: str, rate_date: date | None = None) -> float:
        """Get exchange rate for a currency on a specific date.

        Returns EUR -> currency rate (e.g., 1.08 for USD means 1 EUR = 1.08 USD)
        """
        if currency == "EUR":
            return 1.0

        if rate_date is None:
            rate_date = date.today()

        # Try to get from database
        rate = (
            self.db.query(ExchangeRate)
            .filter(ExchangeRate.currency == currency, ExchangeRate.rate_date == rate_date)
            .first()
        )

        if rate:
            return rate.rate

        # Try to get most recent rate before this date
        rate = (
            self.db.query(ExchangeRate)
            .filter(ExchangeRate.currency == currency, ExchangeRate.rate_date <= rate_date)
            .order_by(desc(ExchangeRate.rate_date))
            .first()
        )

        if rate:
            return rate.rate

        # Fall back to default
        return DEFAULT_RATES.get(currency, 1.0)

    def set_exchange_rate(
        self, currency: str, rate: float, rate_date: date | None = None, source: str = "manual"
    ) -> ExchangeRate:
        """Set exchange rate for a currency on a specific date."""
        if rate_date is None:
            rate_date = date.today()

        existing = (
            self.db.query(ExchangeRate)
            .filter(ExchangeRate.currency == currency, ExchangeRate.rate_date == rate_date)
            .first()
        )

        if existing:
            existing.rate = rate
            existing.source = source
            return existing

        exchange_rate = ExchangeRate(
            currency=currency,
            rate_date=rate_date,
            rate=rate,
            source=source,
        )
        self.db.add(exchange_rate)
        return exchange_rate

    def get_all_rates(self, rate_date: date | None = None) -> dict[str, Any]:
        """Get all exchange rates for a date."""
        if rate_date is None:
            rate_date = date.today()

        rates = {"EUR": 1.0}
        for currency in ["USD", "GBP", "CHF"]:
            rates[currency] = self.get_exchange_rate(currency, rate_date)

        return rates

    def credits_to_eur(self, credits: int) -> float:
        """Convert credits to EUR."""
        return credits / CREDITS_PER_EUR

    def eur_to_credits(self, eur: float) -> int:
        """Convert EUR to credits."""
        return int(eur * CREDITS_PER_EUR)

    def credits_to_currency(
        self, credits: int, currency: str, rate_date: date | None = None
    ) -> tuple[float, float]:
        """Convert credits to a specific currency.

        Returns: (local_amount, exchange_rate_used)
        """
        eur_amount = self.credits_to_eur(credits)
        rate = self.get_exchange_rate(currency, rate_date)
        local_amount = eur_amount * rate
        return (round(local_amount, 2), rate)

    def currency_to_credits(
        self, amount: float, currency: str, rate_date: date | None = None
    ) -> tuple[int, float]:
        """Convert a currency amount to credits.

        Returns: (credits, exchange_rate_used)
        """
        rate = self.get_exchange_rate(currency, rate_date)
        eur_amount = amount / rate
        credits = self.eur_to_credits(eur_amount)
        return (credits, rate)

    def record_transaction(
        self,
        organization_id: str,
        transaction_type: TransactionType,
        credits_amount: int,
        description: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        amount_eur: float | None = None,
        payment_method: str | None = None,
        buyer_organization_id: str | None = None,
        created_by: str | None = None,
        allow_negative: bool = False,
    ) -> CreditTransaction:
        """Record a credit transaction and update organization balance.

        Uses SELECT FOR UPDATE on the organization row to prevent race conditions.
        Checks for existing transaction with the same reference for idempotency.

        Args:
            allow_negative: If False (default), deductions that would produce a
                negative balance raise InsufficientCreditsError. Set True for
                admin-driven clawbacks and chargeback reversals.
        """
        # Idempotency check: if reference provided, return existing transaction
        # Scoped to (organization_id, transaction_type) to allow legitimate
        # multi-party transactions (e.g., marketplace sales with buyer+seller)
        if reference_type and reference_id:
            existing = (
                self.db.query(CreditTransaction)
                .filter(
                    CreditTransaction.organization_id == organization_id,
                    CreditTransaction.transaction_type == transaction_type.value,
                    CreditTransaction.reference_type == reference_type,
                    CreditTransaction.reference_id == reference_id,
                )
                .first()
            )
            if existing:
                return existing  # Idempotent -- already recorded

        # Row-level lock on org to prevent concurrent balance modifications
        org = (
            self.db.query(Organization)
            .filter(Organization.id == organization_id)
            .with_for_update()
            .first()
        )
        if not org:
            raise ValueError(f"Organization {organization_id} not found")

        # Frozen org check (D-09): frozen orgs cannot perform operations
        # (except allow_negative transactions like clawbacks, which are admin-driven)
        if org.is_frozen and not allow_negative:
            raise ValueError(
                f"Organization {organization_id} is frozen due to chargeback. Contact admin."
            )

        # Balance guard (D-17): prevent negative unless explicitly allowed
        # (refund clawbacks and chargeback reversals set allow_negative=True)
        if not allow_negative and credits_amount < 0:
            if (org.credits_balance + credits_amount) < 0:
                raise InsufficientCreditsError(
                    credits_needed=abs(credits_amount),
                    credits_available=org.credits_balance,
                )

        org.credits_balance += credits_amount

        # Track credit pools: subscription, purchased, earned
        if transaction_type == TransactionType.SALE_EARNING:
            org.credits_earned += credits_amount
        elif transaction_type == TransactionType.WITHDRAWAL:
            org.credits_earned += credits_amount  # negative for withdrawals
        elif transaction_type == TransactionType.PURCHASE:
            # Distinguish subscription grants from top-up purchases by description
            if "top-up" in (description or "").lower() or "topup" in (description or "").lower():
                org.credits_purchased += credits_amount
            else:
                # Subscription grant (initial activation or renewal)
                org.credits_subscription += credits_amount
        elif transaction_type == TransactionType.EXECUTION:
            # Deductions consume from subscription first, then purchased, then earned
            remaining = abs(credits_amount)
            # Drain subscription credits first
            sub_drain = min(remaining, max(0, org.credits_subscription))
            org.credits_subscription -= sub_drain
            remaining -= sub_drain
            # Then purchased credits
            if remaining > 0:
                pur_drain = min(remaining, max(0, org.credits_purchased))
                org.credits_purchased -= pur_drain
                remaining -= pur_drain
            # Then earned credits
            if remaining > 0:
                org.credits_earned -= remaining

        # Reset low-credits notification flag on positive credit transactions (grants)
        if credits_amount > 0:
            org.low_credits_notified = False

        transaction = CreditTransaction(
            id=generate_id("ctx_"),
            organization_id=organization_id,
            transaction_type=transaction_type.value,
            credits_amount=credits_amount,
            balance_after=org.credits_balance,
            earned_balance_after=org.credits_earned,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            amount_eur=amount_eur,
            payment_method=payment_method,
            buyer_organization_id=buyer_organization_id,
            created_by=created_by,
        )

        # Holding period for marketplace earnings (D-10)
        if transaction_type == TransactionType.SALE_EARNING:
            holding_days = PSS.get_int(self.db, "HOLDING_PERIOD_DAYS")
            transaction.available_at = utcnow() + timedelta(days=holding_days)

        try:
            self.db.add(transaction)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            # Race condition: another thread inserted the same reference
            existing = (
                self.db.query(CreditTransaction)
                .filter(
                    CreditTransaction.organization_id == organization_id,
                    CreditTransaction.transaction_type == transaction_type.value,
                    CreditTransaction.reference_type == reference_type,
                    CreditTransaction.reference_id == reference_id,
                )
                .first()
            )
            if existing:
                return existing
            raise  # Re-raise if not a duplicate constraint violation

        if credits_amount < 0:
            self._check_low_credits(org)

        return transaction

    def refund_credits(
        self,
        organization_id: str,
        credits: int,
        description: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
    ) -> CreditTransaction:
        """Refund credits to an organization. Creates a REFUND transaction."""
        return self.record_transaction(
            organization_id=organization_id,
            transaction_type=TransactionType.REFUND,
            credits_amount=credits,  # positive
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by="system",
        )

    def _check_low_credits(self, org: Organization) -> None:
        """Check if balance dropped below threshold and notify once.

        Fires a low-credits notification when the balance drops below the
        configured threshold percentage of monthly_quota. Only fires once
        per crossing -- resets when a positive credit transaction arrives.
        """
        if org.low_credits_notified:
            return
        threshold_pct = PSS.get_int(self.db, "LOW_CREDITS_THRESHOLD_PCT")
        threshold = max(1, int(org.monthly_quota * threshold_pct / 100))
        if org.credits_balance <= threshold:
            org.low_credits_notified = True
            try:
                from app.services.notification_service import NotificationService

                ns = NotificationService(self.db)
                # Notify org owner
                if hasattr(org, "owner_user_id") and org.owner_user_id:
                    ns.notify_credits_low(
                        user_id=org.owner_user_id,
                        organization_id=org.id,
                        current_balance=org.credits_balance,
                        threshold=threshold,
                    )
            except Exception as e:
                logger.warning("Failed to send low-credits notification: %s", e)

    def get_transaction_history(
        self,
        organization_id: str,
        transaction_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CreditTransaction]:
        """Get transaction history for an organization."""
        query = self.db.query(CreditTransaction).filter(
            CreditTransaction.organization_id == organization_id
        )

        if transaction_type:
            query = query.filter(CreditTransaction.transaction_type == transaction_type)

        return query.order_by(desc(CreditTransaction.created_at)).offset(offset).limit(limit).all()

    def create_withdrawal(
        self,
        organization_id: str,
        credits_amount: int,
        created_by: str | None = None,
    ) -> Withdrawal:
        """Create a manual withdrawal request."""
        MIN_WITHDRAWAL_CREDITS = 500

        # Lock the org row up front (same pattern as deduct_credits). Concurrent
        # withdrawals must serialize here: otherwise the child Withdrawal INSERT
        # below autoflushes and takes an FK ShareLock on this org row, and the
        # later record_transaction SELECT ... FOR UPDATE then tries to upgrade
        # share -> exclusive, deadlocking concurrent callers. Acquiring the
        # exclusive lock first turns that race into a clean serial queue.
        org = (
            self.db.query(Organization)
            .filter(Organization.id == organization_id)
            .with_for_update()
            .first()
        )
        if not org:
            raise ValueError(f"Organization {organization_id} not found")

        # Validate
        if credits_amount <= 0:
            raise ValueError("Withdrawal amount must be positive")

        if credits_amount < MIN_WITHDRAWAL_CREDITS:
            raise ValueError(f"Minimum withdrawal is {MIN_WITHDRAWAL_CREDITS} credits (50 EUR)")

        withdrawable = self.get_withdrawable_balance(organization_id)
        if credits_amount > withdrawable:
            raise ValueError(f"Insufficient withdrawable credits. Available: {withdrawable}")

        if not org.stripe_connect_onboarding_complete:
            raise ValueError(
                "Stripe Connect onboarding not complete. Configure payment account first."
            )

        eur_amount = self.credits_to_eur(credits_amount)
        local_amount, exchange_rate = self.credits_to_currency(credits_amount, org.currency)

        withdrawal = Withdrawal(
            id=generate_id("wdr_"),
            organization_id=organization_id,
            withdrawal_type=WithdrawalType.MANUAL.value,
            credits_amount=credits_amount,
            credits_per_eur=CREDITS_PER_EUR,
            eur_amount=eur_amount,
            target_currency=org.currency,
            exchange_rate=exchange_rate,
            local_amount=local_amount,
            status=WithdrawalStatus.PENDING.value,
        )

        self.db.add(withdrawal)

        # Record transaction (deduct from earned credits)
        self.record_transaction(
            organization_id=organization_id,
            transaction_type=TransactionType.WITHDRAWAL,
            credits_amount=-credits_amount,
            description=(
                f"Withdrawal request: {credits_amount} credits "
                f"\u2192 {local_amount:.2f} {org.currency}"
            ),
            reference_type="withdrawal",
            reference_id=withdrawal.id,
            amount_eur=eur_amount,
            created_by=created_by,
        )

        return withdrawal

    def process_withdrawal(
        self,
        withdrawal_id: str,
        success: bool,
        transaction_reference: str | None = None,
        failure_reason: str | None = None,
    ) -> Withdrawal:
        """Process a withdrawal (admin action)."""
        withdrawal = self.db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).first()
        if not withdrawal:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")

        if withdrawal.status not in [
            WithdrawalStatus.PENDING.value,
            WithdrawalStatus.PROCESSING.value,
        ]:
            raise ValueError(f"Withdrawal cannot be processed in status: {withdrawal.status}")

        if success:
            withdrawal.status = WithdrawalStatus.COMPLETED.value
            withdrawal.transaction_reference = transaction_reference
        else:
            withdrawal.status = WithdrawalStatus.FAILED.value
            withdrawal.failure_reason = failure_reason

            # Refund credits
            self.record_transaction(
                organization_id=withdrawal.organization_id,
                transaction_type=TransactionType.REFUND,
                credits_amount=withdrawal.credits_amount,
                description=f"Withdrawal failed: {failure_reason}",
                reference_type="withdrawal",
                reference_id=withdrawal.id,
                created_by="system",
            )

        withdrawal.processed_at = utcnow()

        return withdrawal

    def get_withdrawals(
        self,
        organization_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Withdrawal]:
        """Get withdrawals, optionally filtered."""
        query = self.db.query(Withdrawal)

        if organization_id:
            query = query.filter(Withdrawal.organization_id == organization_id)

        if status:
            query = query.filter(Withdrawal.status == status)

        return query.order_by(desc(Withdrawal.created_at)).offset(offset).limit(limit).all()

    def create_withdrawal_schedule(
        self,
        organization_id: str,
        frequency: ScheduleFrequency,
        amount_type: ScheduleAmountType,
        amount_value: float | None = None,
        min_threshold: int = 100,
    ) -> WithdrawalSchedule:
        """Create a scheduled withdrawal."""
        org = self.db.query(Organization).filter(Organization.id == organization_id).first()
        if not org:
            raise ValueError(f"Organization {organization_id} not found")

        if not org.stripe_connect_onboarding_complete:
            raise ValueError("Stripe Connect onboarding not complete")

        if amount_type == ScheduleAmountType.FIXED and not amount_value:
            raise ValueError("Fixed amount required for fixed withdrawals")

        if amount_type == ScheduleAmountType.PERCENTAGE:
            if not amount_value or amount_value <= 0 or amount_value > 100:
                raise ValueError("Percentage must be between 1 and 100")

        next_execution = self._calculate_next_execution(frequency)

        schedule = WithdrawalSchedule(
            id=generate_id("wds_"),
            organization_id=organization_id,
            frequency=frequency.value,
            amount_type=amount_type.value,
            amount_value=amount_value,
            min_threshold=min_threshold,
            next_execution=next_execution,
            is_active=True,
        )

        self.db.add(schedule)

        return schedule

    def _calculate_next_execution(self, frequency: ScheduleFrequency) -> datetime:
        """Calculate next execution date based on frequency."""
        now = utcnow()

        if frequency == ScheduleFrequency.WEEKLY:
            # Next Monday
            days_ahead = 7 - now.weekday()
            if days_ahead == 0:
                days_ahead = 7
            return now + timedelta(days=days_ahead)

        if frequency == ScheduleFrequency.BIWEEKLY:
            # Two weeks from now (fixed interval, not weekday-relative)
            return now + timedelta(days=14)

        if frequency == ScheduleFrequency.MONTHLY:
            # First of next month
            if now.month == 12:
                return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
            return datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)

        if frequency == ScheduleFrequency.QUARTERLY:
            # First of next quarter
            quarter_month = ((now.month - 1) // 3 + 1) * 3 + 1
            if quarter_month > 12:
                return datetime(now.year + 1, quarter_month - 12, 1, tzinfo=timezone.utc)
            return datetime(now.year, quarter_month, 1, tzinfo=timezone.utc)

        return now + timedelta(days=7)

    def process_scheduled_withdrawals(self) -> list[Withdrawal]:
        """Process all due scheduled withdrawals. Called by cron job."""
        now = utcnow()

        schedules = (
            self.db.query(WithdrawalSchedule)
            .filter(
                WithdrawalSchedule.is_active == True,  # noqa: E712
                WithdrawalSchedule.next_execution <= now,
            )
            .all()
        )

        withdrawals = []

        for schedule in schedules:
            try:
                withdrawal = self._execute_scheduled_withdrawal(schedule)
                if withdrawal:
                    withdrawals.append(withdrawal)
            except Exception as e:
                # Log error but continue with other schedules
                logger.error("Error processing schedule %s: %s", schedule.id, e)

            schedule.next_execution = self._calculate_next_execution(
                ScheduleFrequency(schedule.frequency)
            )

        return withdrawals

    def _execute_scheduled_withdrawal(self, schedule: WithdrawalSchedule) -> Withdrawal | None:
        """Execute a single scheduled withdrawal."""
        MIN_WITHDRAWAL_CREDITS = 500

        # Lock the org row up front (W3 — exact mirror of the create_withdrawal
        # fix above). Without the exclusive lock here, this method repeats the
        # share→exclusive deadlock: the child Withdrawal INSERT below
        # autoflushes and takes an FK ShareLock on the org row, then
        # record_transaction's SELECT ... FOR UPDATE tries to upgrade
        # share → exclusive — deadlocking against a concurrent manual
        # create_withdrawal doing the same dance. It also computed
        # `withdrawable` unlocked, opening a double-withdrawal window.
        # Acquiring the exclusive lock first serializes scheduled and manual
        # withdrawals into a clean queue and makes the balance read atomic
        # with the deduction.
        org = (
            self.db.query(Organization)
            .filter(Organization.id == schedule.organization_id)
            .with_for_update()
            .first()
        )

        if not org or not org.stripe_connect_onboarding_complete:
            return None

        # Calculate withdrawable balance (matured earnings minus past
        # withdrawals) UNDER the org lock — concurrent withdrawals serialize
        # on the lock above, so this read cannot race a parallel deduction.
        withdrawable = self.get_withdrawable_balance(schedule.organization_id)

        if withdrawable < schedule.min_threshold:
            return None

        if schedule.amount_type == ScheduleAmountType.ALL.value:
            credits_amount = withdrawable
        elif schedule.amount_type == ScheduleAmountType.PERCENTAGE.value:
            credits_amount = int(withdrawable * schedule.amount_value / 100)
        else:  # FIXED
            credits_amount = min(int(schedule.amount_value), withdrawable)

        if credits_amount <= 0:
            return None

        # Enforce minimum withdrawal threshold (D-15)
        if credits_amount < MIN_WITHDRAWAL_CREDITS:
            return None

        eur_amount = self.credits_to_eur(credits_amount)
        local_amount, exchange_rate = self.credits_to_currency(credits_amount, org.currency)

        withdrawal = Withdrawal(
            id=generate_id("wdr_"),
            organization_id=org.id,
            schedule_id=schedule.id,
            withdrawal_type=WithdrawalType.SCHEDULED.value,
            credits_amount=credits_amount,
            credits_per_eur=CREDITS_PER_EUR,
            eur_amount=eur_amount,
            target_currency=org.currency,
            exchange_rate=exchange_rate,
            local_amount=local_amount,
            status=WithdrawalStatus.PENDING.value,
        )

        self.db.add(withdrawal)

        # Record transaction
        self.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.WITHDRAWAL,
            credits_amount=-credits_amount,
            description=(f"Scheduled withdrawal ({schedule.frequency}): {credits_amount} credits"),
            reference_type="withdrawal",
            reference_id=withdrawal.id,
            amount_eur=eur_amount,
            created_by="system",
        )

        return withdrawal

    def record_marketplace_sale(
        self,
        seller_organization_id: str,
        buyer_organization_id: str,
        model_id: str,
        credits_price: int,
        commission_rate: float = 0.10,
    ) -> tuple[CreditTransaction, CreditTransaction, CreditTransaction]:
        """Record a marketplace sale between two organizations with commission.

        Creates three transactions:
        1. Buyer deduction (full price)
        2. Commission audit record (on seller org, credits_amount=0)
        3. Seller earning (price minus commission)

        Args:
            seller_organization_id: Organization receiving payment.
            buyer_organization_id: Organization paying.
            model_id: Catalog model being purchased.
            credits_price: Full price in credits.
            commission_rate: Platform commission fraction (default 0.10 = 10%).

        Returns:
            Tuple of (buyer_tx, commission_tx, seller_tx).
        """
        commission_credits = round(credits_price * commission_rate)
        seller_credits = credits_price - commission_credits

        # W6: acquire BOTH org row locks in deterministic sorted-ID order
        # BEFORE any mutation. record_transaction locks one org at a time as
        # the three transactions below run (buyer, then seller twice); with
        # that implicit buyer→seller order, two concurrent opposite-direction
        # sales (A buys from B while B buys from A) acquire locks in ABBA
        # order and Postgres aborts one with a deadlock error. Pre-locking in
        # sorted order gives every sale the same global acquisition order;
        # the FOR UPDATE inside record_transaction then re-locks rows this
        # transaction already holds (a no-op).
        for org_id in sorted({buyer_organization_id, seller_organization_id}):
            locked_org = (
                self.db.query(Organization)
                .filter(Organization.id == org_id)
                .with_for_update()
                .first()
            )
            if locked_org is None:
                raise ValueError(f"Organization {org_id} not found")

        # 1. Deduct full price from buyer
        buyer_tx = self.record_transaction(
            organization_id=buyer_organization_id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-credits_price,
            description=f"Model activation: {credits_price} credits",
            reference_type="model",
            reference_id=model_id,
            created_by="system",
        )

        # 2. Commission audit record (credits_amount=0, amount_eur stores commission for aggregation)
        commission_tx = self.record_transaction(
            organization_id=seller_organization_id,
            transaction_type=TransactionType.COMMISSION,
            credits_amount=0,
            description=f"Platform commission ({commission_rate * 100:.0f}%): {commission_credits} credits on sale of {credits_price}",
            reference_type="model",
            reference_id=model_id,
            amount_eur=float(commission_credits),
            buyer_organization_id=buyer_organization_id,
            created_by="system",
        )

        # 3. Credit seller (price minus commission, as earned credits)
        seller_tx = self.record_transaction(
            organization_id=seller_organization_id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=seller_credits,
            description=f"Marketplace sale: {credits_price} credits (after {commission_rate * 100:.0f}% commission: -{commission_credits})",
            reference_type="model",
            reference_id=model_id,
            buyer_organization_id=buyer_organization_id,
            created_by="system",
        )

        commission_tx.commission_rate = commission_rate
        seller_tx.commission_rate = commission_rate
        self.db.flush()

        return (buyer_tx, commission_tx, seller_tx)

    def get_withdrawable_balance(self, organization_id: str) -> int:
        """Calculate withdrawable balance from matured SALE_EARNING minus completed WITHDRAWAL.

        Per D-11: Withdrawable = SUM(SALE_EARNING where available_at <= now())
        + SUM(WITHDRAWAL credits).
        Note: WITHDRAWAL credits_amount is negative, so addition effectively subtracts.
        """
        now = utcnow()

        matured_earnings = (
            self.db.query(func.coalesce(func.sum(CreditTransaction.credits_amount), 0))
            .filter(
                CreditTransaction.organization_id == organization_id,
                CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
                CreditTransaction.available_at <= now,
            )
            .scalar()
        )

        completed_withdrawals = (
            self.db.query(func.coalesce(func.sum(CreditTransaction.credits_amount), 0))
            .filter(
                CreditTransaction.organization_id == organization_id,
                CreditTransaction.transaction_type == TransactionType.WITHDRAWAL.value,
            )
            .scalar()
        )

        # withdrawals are negative, so adding them subtracts from earnings
        return max(0, matured_earnings + completed_withdrawals)

    @staticmethod
    def deduct_credits(
        db: Session,
        organization_id: str,
        credits: int,
        description: str = "Solver execution",
        reference_type: str | None = None,
        reference_id: str | None = None,
    ) -> None:
        """Static method to deduct credits from an organization.

        Convenience method for backward compatibility with solve endpoints.
        Pre-checks balance and raises InsufficientCreditsError if insufficient.
        Uses row-level locking via record_transaction.
        """
        # Pre-check: lock row and verify balance before deduction
        org = (
            db.query(Organization)
            .filter(Organization.id == organization_id)
            .with_for_update()
            .first()
        )
        if not org:
            raise ValueError(f"Organization {organization_id} not found")
        if org.credits_balance < credits:
            raise InsufficientCreditsError(
                credits_needed=credits, credits_available=org.credits_balance
            )

        service = CreditsService(db)
        service.record_transaction(
            organization_id=organization_id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-credits,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by="system",
        )
