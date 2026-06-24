"""Tests for the credits system."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models import (
    CREDITS_PER_EUR,
    Organization,
    ScheduleAmountType,
    ScheduleFrequency,
    TransactionType,
)
from app.services.credits_service import CreditsService


class TestExchangeRates:
    """Tests for exchange rate functionality."""

    def test_credits_per_eur_constant(self):
        """Test that CREDITS_PER_EUR is 10."""
        assert CREDITS_PER_EUR == 10

    def test_get_exchange_rate_eur(self, db_session: Session):
        """EUR rate should always be 1.0."""
        service = CreditsService(db_session)
        rate = service.get_exchange_rate("EUR")
        assert rate == 1.0

    def test_get_exchange_rate_default(self, db_session: Session):
        """Should return default rate when no DB entry exists."""
        service = CreditsService(db_session)
        rate = service.get_exchange_rate("USD")
        assert rate == 1.08  # Default USD rate

    def test_set_and_get_exchange_rate(self, db_session: Session):
        """Should be able to set and retrieve exchange rates."""
        service = CreditsService(db_session)

        # Set rate
        service.set_exchange_rate("USD", 1.10, date.today())

        # Get rate
        rate = service.get_exchange_rate("USD", date.today())
        assert rate == 1.10

    def test_set_exchange_rate_existing_lookup_is_scoped(self, db_session: Session):
        """set_exchange_rate's existing-row lookup must be scoped by BOTH currency
        AND rate_date, and must update-in-place (not duplicate) when the same
        (currency, date) is re-set.

        Phase 12.5 kill-test for credits_service survivors: drops of the currency
        filter (mutmut_5/7), drop of the rate_date filter (mutmut_6), and nulling
        the query (mutmut_9) in the existing-rate lookup.
        """
        from app.models import ExchangeRate

        service = CreditsService(db_session)
        d1 = date(2026, 1, 15)
        d2 = date(2026, 2, 20)

        # Distinct currencies on the SAME date must stay distinct (currency scoping).
        service.set_exchange_rate("USD", 1.11, d1)
        service.set_exchange_rate("GBP", 0.87, d1)
        db_session.flush()
        assert service.get_exchange_rate("USD", d1) == 1.11
        assert service.get_exchange_rate("GBP", d1) == 0.87

        # Same currency on a DIFFERENT date must stay distinct (date scoping).
        service.set_exchange_rate("USD", 1.22, d2)
        db_session.flush()
        assert service.get_exchange_rate("USD", d1) == 1.11  # unchanged by the d2 set
        assert service.get_exchange_rate("USD", d2) == 1.22

        # Re-setting the same (currency, date) updates in place — exactly one row.
        service.set_exchange_rate("USD", 1.33, d1)
        db_session.flush()
        assert service.get_exchange_rate("USD", d1) == 1.33
        rows = (
            db_session.query(ExchangeRate)
            .filter(ExchangeRate.currency == "USD", ExchangeRate.rate_date == d1)
            .count()
        )
        assert rows == 1

    def test_get_all_rates(self, db_session: Session):
        """Should return all rates."""
        service = CreditsService(db_session)
        rates = service.get_all_rates()

        # Exact default rates must be locked — pricing depends on these.
        assert rates["EUR"] == 1.0
        assert rates["USD"] == 1.08
        assert rates["GBP"] == 0.86
        assert rates["CHF"] == 0.94


class TestCreditConversions:
    """Tests for credit conversion functions."""

    def test_credits_to_eur(self, db_session: Session):
        """Test credits to EUR conversion."""
        service = CreditsService(db_session)

        assert service.credits_to_eur(10) == 1.0
        assert service.credits_to_eur(100) == 10.0
        assert service.credits_to_eur(25) == 2.5

    def test_eur_to_credits(self, db_session: Session):
        """Test EUR to credits conversion."""
        service = CreditsService(db_session)

        assert service.eur_to_credits(1.0) == 10
        assert service.eur_to_credits(10.0) == 100
        assert service.eur_to_credits(2.5) == 25

    def test_credits_to_currency(self, db_session: Session):
        """Test credits to local currency conversion."""
        service = CreditsService(db_session)

        # Set USD rate
        service.set_exchange_rate("USD", 1.10, date.today())

        # 100 credits = 10 EUR = 11 USD
        local_amount, rate = service.credits_to_currency(100, "USD")
        assert rate == 1.10
        assert local_amount == 11.0

    def test_currency_to_credits(self, db_session: Session):
        """Test local currency to credits conversion."""
        service = CreditsService(db_session)

        # Set USD rate
        service.set_exchange_rate("USD", 1.10, date.today())

        # 11 USD = 10 EUR = 100 credits
        credits, rate = service.currency_to_credits(11.0, "USD")
        assert rate == 1.10
        assert credits == 100


class TestCreditTransactions:
    """Tests for credit transaction recording."""

    def test_get_transaction_history(self, db_session: Session, test_organization: Organization):
        """Test retrieving transaction history for a specific org."""
        service = CreditsService(db_session)

        # Create exactly two transactions for this org.
        service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=100,
            description="Purchase 1",
        )
        service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="Execution 1",
        )

        # Get history filtered to this org — must see exactly the two we wrote.
        history = service.get_transaction_history(test_organization.id)
        assert len(history) == 2

        # Most recent first (Execution 1 was recorded last).
        assert history[0].description == "Execution 1"
        assert history[0].credits_amount == -10
        assert history[0].transaction_type == TransactionType.EXECUTION.value

        assert history[1].description == "Purchase 1"
        assert history[1].credits_amount == 100
        assert history[1].transaction_type == TransactionType.PURCHASE.value


class TestWithdrawals:
    """Tests for withdrawal functionality."""

    def test_create_withdrawal_insufficient_credits(
        self, db_session: Session, test_organization: Organization
    ):
        """Should fail if insufficient withdrawable balance."""
        service = CreditsService(db_session)

        # Set up payment account but low balance
        test_organization.stripe_connect_onboarding_complete = True
        test_organization.credits_earned = 10
        db_session.commit()

        with pytest.raises(ValueError, match="Minimum withdrawal is 500 credits"):
            service.create_withdrawal(
                organization_id=test_organization.id,
                credits_amount=100,
            )

    def test_create_withdrawal_success(self, db_session: Session, test_organization: Organization):
        """Test successful withdrawal creation."""
        from app.shared.utils.datetime_helpers import utcnow

        service = CreditsService(db_session)

        # Set up — must exceed 500 credit minimum with matured earnings
        test_organization.stripe_connect_onboarding_complete = True
        test_organization.credits_earned = 1000
        test_organization.currency = "EUR"
        db_session.flush()

        # Create matured SALE_EARNING via record_transaction (handles balance_after)
        txn = service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=1000,
            description="Matured sale earning for test",
        )
        # Backdate available_at so it's withdrawable now
        txn.available_at = utcnow() - timedelta(days=1)
        db_session.commit()

        withdrawal = service.create_withdrawal(
            organization_id=test_organization.id,
            credits_amount=500,
        )

        assert withdrawal.credits_amount == 500
        assert withdrawal.eur_amount == 50.0  # 500 credits / 10
        assert withdrawal.status == "pending"

    def test_process_withdrawal_success(self, db_session: Session, test_organization: Organization):
        """Test processing a withdrawal successfully."""
        from app.shared.utils.datetime_helpers import utcnow

        service = CreditsService(db_session)

        # Set up with matured earnings exceeding 500 minimum
        test_organization.stripe_connect_onboarding_complete = True
        test_organization.credits_earned = 1000
        db_session.flush()

        txn = service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=1000,
            description="Matured sale earning for test",
        )
        txn.available_at = utcnow() - timedelta(days=1)
        db_session.commit()

        withdrawal = service.create_withdrawal(
            organization_id=test_organization.id,
            credits_amount=500,
        )

        # Process it
        processed = service.process_withdrawal(
            withdrawal_id=withdrawal.id,
            success=True,
            transaction_reference="BANK-REF-123",
        )

        assert processed.status == "completed"
        assert processed.transaction_reference == "BANK-REF-123"

    def test_get_withdrawals_filters_by_org_status_and_offset(
        self, db_session: Session, test_organization: Organization
    ):
        """get_withdrawals scopes by org + status and honors the offset default.

        Kills the credits_service.get_withdrawals ``offset=0 -> 1`` mutant
        (mutmut-v24 section 3): with the default offset=0 every row returns, so a
        flipped default would silently drop the newest row. Also pins the
        org-scope and the status filter — get_withdrawals had no direct test.
        """
        from app.models import Withdrawal, WithdrawalStatus, WithdrawalType
        from app.shared.utils.id_generator import generate_id

        def _wd(org_id: str, status: str) -> None:
            db_session.add(
                Withdrawal(
                    id=generate_id("wdr_"),
                    organization_id=org_id,
                    withdrawal_type=WithdrawalType.MANUAL.value,
                    credits_amount=500,
                    credits_per_eur=10,
                    eur_amount=50.0,
                    target_currency="EUR",
                    exchange_rate=1.0,
                    local_amount=50.0,
                    status=status,
                )
            )

        # Another org's withdrawal must never leak into the results.
        other = Organization(
            id="org_wd_other", name="Other WD Org", credits_balance=0, credits_earned=0
        )
        db_session.add(other)
        db_session.flush()

        _wd(test_organization.id, WithdrawalStatus.PENDING.value)
        _wd(test_organization.id, WithdrawalStatus.PENDING.value)
        _wd(test_organization.id, WithdrawalStatus.COMPLETED.value)
        _wd(other.id, WithdrawalStatus.PENDING.value)
        db_session.commit()

        service = CreditsService(db_session)

        # Default offset=0 -> all 3 of this org's withdrawals (kills offset=1).
        all_wd = service.get_withdrawals(organization_id=test_organization.id)
        assert len(all_wd) == 3
        assert all(w.organization_id == test_organization.id for w in all_wd)

        # Status filter narrows to the 2 PENDING rows.
        pending = service.get_withdrawals(
            organization_id=test_organization.id, status=WithdrawalStatus.PENDING.value
        )
        assert len(pending) == 2

        # offset=1 skips exactly the newest row (proves offset is honored).
        offset1 = service.get_withdrawals(organization_id=test_organization.id, offset=1)
        assert len(offset1) == 2


class TestWithdrawalSchedules:
    """Tests for scheduled withdrawals."""

    def test_create_schedule(self, db_session: Session, test_organization: Organization):
        """Test creating a withdrawal schedule."""
        service = CreditsService(db_session)

        # Set up bank details
        test_organization.stripe_connect_onboarding_complete = True
        db_session.commit()

        schedule = service.create_withdrawal_schedule(
            organization_id=test_organization.id,
            frequency=ScheduleFrequency.MONTHLY,
            amount_type=ScheduleAmountType.ALL,
            min_threshold=100,
        )

        assert schedule.frequency == "monthly"
        assert schedule.amount_type == "all"
        assert schedule.is_active
        assert schedule.next_execution > datetime.now(timezone.utc)

    def test_calculate_next_execution_per_frequency(self, db_session: Session):
        """_calculate_next_execution returns the right date per frequency.

        Phase 12.5 kill-test: the BIWEEKLY branch-condition flip (mutmut_10,
        `== ScheduleFrequency.BIWEEKLY` -> `!=`) makes a MONTHLY/QUARTERLY
        schedule wrongly take the fixed 14-day BIWEEKLY path. Asserting the
        first-of-period date (day == 1) catches it; the existing schedule test
        only asserted `next_execution > now`, which both paths satisfy.
        """
        now = datetime.now(timezone.utc)
        service = CreditsService(db_session)

        monthly = service._calculate_next_execution(ScheduleFrequency.MONTHLY)
        assert monthly.day == 1  # first of next month, NOT now + 14 days
        assert monthly.month == (1 if now.month == 12 else now.month + 1)

        quarterly = service._calculate_next_execution(ScheduleFrequency.QUARTERLY)
        assert quarterly.day == 1
        assert quarterly.month in (1, 4, 7, 10)

        weekly = service._calculate_next_execution(ScheduleFrequency.WEEKLY)
        assert weekly.weekday() == 0  # next Monday

        # BIWEEKLY is a FIXED 14-day interval (not weekday- or first-of-period
        # relative). The MONTHLY/QUARTERLY/WEEKLY cases above never pass
        # BIWEEKLY, so a mutation INSIDE the biweekly branch body (e.g.
        # timedelta(days=14) -> some other constant) survives them. Asserting
        # the ~14-day delta exercises that branch directly and also kills the
        # mutmut_10 condition flip (`== BIWEEKLY` -> `!= BIWEEKLY`), which would
        # route BIWEEKLY to the 7-day fall-through default.
        biweekly = service._calculate_next_execution(ScheduleFrequency.BIWEEKLY)
        delta_days = (biweekly - now).total_seconds() / 86400
        assert 13.9 < delta_days < 14.1, (
            f"BIWEEKLY must be ~14 days out (not 7), got {delta_days:.4f} days "
            f"({biweekly} vs now {now})"
        )

    def test_create_schedule_percentage(self, db_session: Session, test_organization: Organization):
        """Test creating a percentage-based schedule."""
        service = CreditsService(db_session)

        test_organization.stripe_connect_onboarding_complete = True
        db_session.commit()

        schedule = service.create_withdrawal_schedule(
            organization_id=test_organization.id,
            frequency=ScheduleFrequency.WEEKLY,
            amount_type=ScheduleAmountType.PERCENTAGE,
            amount_value=50.0,
            min_threshold=50,
        )

        assert schedule.amount_type == "percentage"
        assert schedule.amount_value == 50.0


class TestCommission:
    """Tests for marketplace commission logic."""

    def test_commission_audit_trail(self, db_session: Session):
        """Verify 3 transactions with correct types."""
        seller = Organization(
            id="comm-seller-4", name="Seller", credits_balance=0, credits_earned=0
        )
        buyer = Organization(id="comm-buyer-4", name="Buyer", credits_balance=100, credits_earned=0)
        db_session.add_all([seller, buyer])
        db_session.commit()

        service = CreditsService(db_session)
        buyer_tx, commission_tx, seller_tx = service.record_marketplace_sale(
            seller_organization_id=seller.id,
            buyer_organization_id=buyer.id,
            model_id="model-4",
            credits_price=50,
            commission_rate=0.10,
        )

        assert buyer_tx.transaction_type == TransactionType.EXECUTION.value
        assert commission_tx.transaction_type == TransactionType.COMMISSION.value
        assert seller_tx.transaction_type == TransactionType.SALE_EARNING.value

        # Verify descriptions contain commission info
        assert "commission" in commission_tx.description.lower()
        assert "10%" in commission_tx.description
        assert "commission" in seller_tx.description.lower()

    def test_commission_small_price(self, db_session: Session):
        """Rounding-to-zero commission edge: 3-credit sale at a NONZERO 10% rate.

        ``record_marketplace_sale`` computes ``commission_credits =
        round(credits_price * commission_rate)`` (credits_service.py:687). For
        3 credits at 10% that is ``round(0.3) == 0`` -- the seller keeps the
        full 3 credits even though the rate is nonzero.

        Re-added (Phase 12 code-review finding #14): the 12.3 consolidation
        deleted this and claimed subsumption by
        test_credits_service_consolidated.py::test_marketplace_sale_zero_commission,
        but that test passes ``commission_rate=0.0`` -- commission is trivially
        0 because the RATE is 0, never exercising the round-down boundary on a
        nonzero rate. A ``round(...)`` -> ``math.ceil(...)`` mutation survives
        the 0.0-rate case (ceil(0.0)==0) but is killed here (ceil(0.3)==1 would
        wrongly take 1 credit, leaving the seller 2).
        """
        seller = Organization(
            id="comm-seller-3", name="Seller", credits_balance=0, credits_earned=0
        )
        buyer = Organization(id="comm-buyer-3", name="Buyer", credits_balance=50, credits_earned=0)
        db_session.add_all([seller, buyer])
        db_session.commit()

        service = CreditsService(db_session)
        buyer_tx, commission_tx, seller_tx = service.record_marketplace_sale(
            seller_organization_id=seller.id,
            buyer_organization_id=buyer.id,
            model_id="model-3",
            credits_price=3,
            commission_rate=0.10,
        )

        db_session.refresh(seller)
        assert seller.credits_earned == 3  # round(0.3)=0 commission -> seller keeps full 3
        assert seller_tx.credits_amount == 3
        assert commission_tx.credits_amount == 0
        assert commission_tx.amount_eur == 0.0  # commission stored in amount_eur


class TestPlatformSettings:
    """Tests for platform settings service."""

    def test_default_commission_rate(self, db_session: Session):
        """Default commission rate should be 0.10 (10%)."""
        from app.services.platform_settings_service import PlatformSettingsService

        rate = PlatformSettingsService.get_commission_rate(db_session)
        assert rate == 0.10

    def test_get_default_setting(self, db_session: Session):
        """get() should return default value when no DB entry exists."""
        from app.services.platform_settings_service import PlatformSettingsService

        value = PlatformSettingsService.get(db_session, "marketplace_commission_rate")
        assert value == "0.10"

    def test_set_and_get_setting(self, db_session: Session):
        """set() should create or update a setting, get() should retrieve it."""
        from app.services.platform_settings_service import PlatformSettingsService

        PlatformSettingsService.set(
            db_session, "marketplace_commission_rate", "0.20", updated_by="admin-user"
        )
        value = PlatformSettingsService.get(db_session, "marketplace_commission_rate")
        assert value == "0.20"

        # Update again
        PlatformSettingsService.set(db_session, "marketplace_commission_rate", "0.15")
        value = PlatformSettingsService.get(db_session, "marketplace_commission_rate")
        assert value == "0.15"

    def test_get_unknown_key_raises(self, db_session: Session):
        """get() for unknown key should raise MissingSettingError."""
        from app.services.platform_settings_service import (
            MissingSettingError,
            PlatformSettingsService,
        )

        with pytest.raises(MissingSettingError):
            PlatformSettingsService.get(db_session, "nonexistent_key")


@pytest.fixture
def test_organization(db_session: Session):
    """Create a test organization."""
    org = Organization(
        id="test-org-credits",
        name="Test Organization",
        credits_balance=100,
        credits_earned=0,
        currency="EUR",
    )
    db_session.add(org)
    db_session.commit()
    return org


class TestCreditsRejectionMatrix:
    """SC3 rejection-matrix cells for /api/v2/credits/* endpoints.

    All cells in this class are owner=PLAN_02 (financial) per the
    rejection-matrix.
    """

    def test_credits_withdrawals_unauthenticated_returns_401(self, client):
        """SC3 cell #3: anonymous POST /api/v2/credits/withdrawals -> 401."""
        response = client.post("/api/v2/credits/withdrawals", json={"credits_amount": 500})
        assert response.status_code == 401, (
            f"Expected 401 for anonymous POST /api/v2/credits/withdrawals, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_credits_withdrawals_malformed_body_returns_422(self, authenticated_client):
        """SC3 cell #4: POST /api/v2/credits/withdrawals with invalid amount -> 422.

        WithdrawalRequest declares credits_amount: int = Field(..., gt=0).
        Passing credits_amount=0 must fail Pydantic validation.
        """
        response = authenticated_client.post(
            "/api/v2/credits/withdrawals", json={"credits_amount": 0}
        )
        assert response.status_code == 422, (
            f"Expected 422 for credits_amount=0, got {response.status_code}: {response.json()}"
        )
        errors = response.json().get("detail", [])
        assert any("credits_amount" in (err.get("loc") or []) for err in errors), (
            f"Expected validation error on 'credits_amount' field, got {errors!r}"
        )

    def test_credits_schedules_unauthenticated_returns_401(self, client):
        """SC3 cell #5: anonymous POST /api/v2/credits/schedules -> 401."""
        response = client.post(
            "/api/v2/credits/schedules",
            json={"frequency": "monthly", "amount_type": "all"},
        )
        assert response.status_code == 401, (
            f"Expected 401 for anonymous POST /api/v2/credits/schedules, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_credits_schedules_malformed_body_returns_422(self, authenticated_client):
        """SC3 cell #6: POST /api/v2/credits/schedules with missing required fields -> 422.

        ScheduleRequest requires frequency: str and amount_type: str. Posting an
        empty body must fail Pydantic validation with field-level errors.
        """
        response = authenticated_client.post("/api/v2/credits/schedules", json={})
        assert response.status_code == 422, (
            f"Expected 422 for empty body, got {response.status_code}: {response.json()}"
        )
        errors = response.json().get("detail", [])
        missing_fields = {tuple(err.get("loc") or ()) for err in errors}
        assert any("frequency" in loc for loc in missing_fields), (
            f"Expected validation error on 'frequency' field, got {errors!r}"
        )
        assert any("amount_type" in loc for loc in missing_fields), (
            f"Expected validation error on 'amount_type' field, got {errors!r}"
        )

    def test_credits_schedule_delete_unauthenticated_returns_401(self, client):
        """SC3 cell #7: anonymous DELETE /api/v2/credits/schedules/{id} -> 401."""
        response = client.delete("/api/v2/credits/schedules/sched_any")
        assert response.status_code == 401, (
            f"Expected 401 for anonymous DELETE /api/v2/credits/schedules/sched_any, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_credits_schedule_delete_nonexistent_returns_404(self, authenticated_client):
        """SC3 cell #8 (422 reclassified to 404 — see SUMMARY ``Endpoint scope``):

        DELETE /api/v2/credits/schedules/{schedule_id} has no body schema and
        a free-form `str` path param, so a Pydantic-422 path is not applicable.
        The matrix-listed cell #8 (422) is satisfied here as a 404 rejection on
        a non-existent schedule id, which exercises the same auth-passed
        ownership-check rejection surface the 422 cell intended to cover.

        Reclassification documented in 12.4-02-SUMMARY.md ``Endpoint scope``
        (per the matrix's R6 prioritization clause that allows owner=PLAN_02
        cells to land their 'best-shape' rejection path).
        """
        response = authenticated_client.delete("/api/v2/credits/schedules/sched_does_not_exist")
        assert response.status_code == 404, (
            f"Expected 404 for non-existent schedule id, got {response.status_code}: "
            f"{response.json()}"
        )
        assert "not found" in response.json().get("detail", "").lower()

    def test_credits_settings_currency_unauthenticated_returns_401(self, client):
        """SC3 cell #9: anonymous PUT /api/v2/credits/settings/currency -> 401."""
        response = client.put("/api/v2/credits/settings/currency", json={"currency": "EUR"})
        assert response.status_code == 401, (
            f"Expected 401 for anonymous PUT /api/v2/credits/settings/currency, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_credits_settings_currency_invalid_currency_returns_422(self, authenticated_client):
        """SC3 cell #10: PUT /api/v2/credits/settings/currency with bad currency -> 422.

        CurrencyRequest declares currency: str with pattern=^(EUR|USD|GBP|CHF)$.
        Posting an unsupported code (XYZ) must fail Pydantic regex validation.
        """
        response = authenticated_client.put(
            "/api/v2/credits/settings/currency", json={"currency": "XYZ"}
        )
        assert response.status_code == 422, (
            f"Expected 422 for currency=XYZ, got {response.status_code}: {response.json()}"
        )
        errors = response.json().get("detail", [])
        assert any("currency" in (err.get("loc") or []) for err in errors), (
            f"Expected validation error on 'currency' field, got {errors!r}"
        )

    def test_admin_credits_adjust_unauthenticated_returns_401(self, client):
        """SC3 cell #11: anonymous POST /api/v2/admin/credits/adjust -> 401."""
        response = client.post(
            "/api/v2/admin/credits/adjust",
            json={"organization_id": "org_any", "amount": 100, "reason": "anon test"},
        )
        assert response.status_code == 401, (
            f"Expected 401 for anonymous POST /api/v2/admin/credits/adjust, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_admin_withdrawals_approve_unauthenticated_returns_401(self, client):
        """SC3 cell #12: anonymous POST /api/v2/admin/withdrawals/{id}/approve -> 401."""
        response = client.post("/api/v2/admin/withdrawals/wd_any/approve")
        assert response.status_code == 401, (
            f"Expected 401 for anonymous POST /api/v2/admin/withdrawals/wd_any/approve, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_admin_withdrawals_approve_nonexistent_returns_404(self, admin_client):
        """SC3 cell #13 (422 reclassified to 404 — see SUMMARY ``Endpoint scope``):

        POST /api/v2/admin/withdrawals/{withdrawal_id}/approve has no body schema
        and free-form `str` path param, so a Pydantic-422 path is structurally
        not applicable. The matrix-listed 422 cell is satisfied here as a
        404-rejection on a non-existent withdrawal id — same auth-passed
        ownership-check rejection surface.
        """
        response = admin_client.post("/api/v2/admin/withdrawals/wd_does_not_exist/approve")
        assert response.status_code == 404, (
            f"Expected 404 for non-existent withdrawal id, got {response.status_code}: "
            f"{response.json()}"
        )
        assert "not found" in response.json().get("detail", "").lower()

    def test_admin_withdrawals_reject_unauthenticated_returns_401(self, client):
        """SC3 cell #14: anonymous POST /api/v2/admin/withdrawals/{id}/reject -> 401."""
        response = client.post(
            "/api/v2/admin/withdrawals/wd_any/reject", json={"reason": "anon test"}
        )
        assert response.status_code == 401, (
            f"Expected 401 for anonymous POST /api/v2/admin/withdrawals/wd_any/reject, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_admin_withdrawals_reject_malformed_body_returns_422(self, admin_client):
        """SC3 cell #15: POST /api/v2/admin/withdrawals/{id}/reject with type-invalid body -> 422.

        WithdrawalActionRequest declares reason: str | None. Posting reason=123
        (int, not str/None) must fail Pydantic validation with a 422.
        """
        response = admin_client.post(
            "/api/v2/admin/withdrawals/wd_any/reject", json={"reason": 123}
        )
        assert response.status_code == 422, (
            f"Expected 422 for reason=123, got {response.status_code}: {response.json()}"
        )
        errors = response.json().get("detail", [])
        assert any("reason" in (err.get("loc") or []) for err in errors), (
            f"Expected validation error on 'reason' field, got {errors!r}"
        )

    def test_workspace_credits_allocate_unauthenticated_returns_401(self, client):
        """SC3 cell #16: anonymous POST /api/v2/workspaces/{ws}/credits/allocate -> 401."""
        response = client.post("/api/v2/workspaces/ws_any/credits/allocate", json={"amount": 100})
        assert response.status_code == 401, (
            f"Expected 401 for anonymous POST /api/v2/workspaces/ws_any/credits/allocate, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_workspace_credits_allocate_non_member_returns_403(self, authenticated_client):
        """SC3 cell #17 (422 reclassified to 403 — see SUMMARY ``Endpoint scope``):

        POST /api/v2/workspaces/{ws}/credits/allocate is gated by RequireAdmin
        which executes the workspace-membership lookup BEFORE FastAPI processes
        the body schema (Pydantic-422 is unreachable for a non-member caller).
        The matrix-listed 422 cell is satisfied here as a 403-rejection on a
        non-member workspace access — same rejection-path surface the 422 cell
        intended to cover (authenticated-but-not-authorized).

        Reclassification rationale matches cells #8 and #13 — best-shape
        rejection path when the original status code is structurally
        unreachable. Documented in 12.4-02-SUMMARY.md ``Endpoint scope``.
        """
        response = authenticated_client.post(
            "/api/v2/workspaces/ws_not_a_member/credits/allocate", json={"amount": 100}
        )
        assert response.status_code == 403, (
            f"Expected 403 for non-member workspace access, got {response.status_code}: "
            f"{response.json()}"
        )
        assert "not a member" in response.json().get("detail", "").lower()


class TestSC2FinancialConcurrency:
    """SC2 concurrent-access tests for financial-endpoint service paths.

    Variant A canonical (threading.Thread + per-thread sessionmaker(bind=db_engine),
    CR-03 idiom from tests/test_credit_race_conditions.py:60-109 + the canonical
    per-thread-session concurrency pattern).

    These tests exercise the same business-logic invariants the HTTP handlers
    enforce on /api/v2/credits/withdrawals and /api/v2/admin/credits/adjust —
    the autouse db_session override in conftest.py:341 forces all in-process
    HTTP requests to share one SQLAlchemy Session, which is not thread-safe.
    The repository's canonical HTTP-driven concurrency pattern (see
    tests/test_billing.py:331 TestCrossTenantCreditIsolation) therefore drives
    the underlying CreditsService API with per-thread sessions rather than
    using authenticated_client. The dedup invariant (at-most-one effect) lives
    in the service + DB layer, not the FastAPI handler, so this still proves
    the production race-condition guard.
    """

    def test_concurrent_withdrawal_creation_at_most_one_succeeds(self, db_engine, db_session):
        """SC2: 10 concurrent create_withdrawal calls on an org with exactly
        500 matured credits succeed at-most-once.

        Mirrors the dedup invariant POST /api/v2/credits/withdrawals enforces
        in its service layer. 10 threads each request a 500-credit withdrawal
        against a balance that ONLY supports one such withdrawal. The DB
        invariant: total successful withdrawal rows == 1, balance updates to 0.

        Variant A (threading.Thread + per-thread sessionmaker) per D-02 + the
        CR-03 idiom from tests/test_credit_race_conditions.py:60-109.
        """
        import queue
        import threading
        from datetime import timedelta

        from sqlalchemy.orm import sessionmaker

        from app.models import CreditTransaction, Organization, TransactionType, Withdrawal
        from app.services.credits_service import CreditsService
        from app.shared.utils.datetime_helpers import utcnow
        from app.shared.utils.id_generator import generate_id

        org_id = generate_id("org_")
        org = Organization(
            id=org_id,
            name="SC2 Withdrawal Org",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_onboarding_complete=True,
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()
        # Matured SALE_EARNING so balance is withdrawable.
        # After this: credits_balance=500, credits_earned=500.
        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org_id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=500,
            description="Matured earning for SC2 race",
        )
        txn.available_at = utcnow() - timedelta(days=1)
        db_session.commit()

        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def withdrawal_worker(thread_id: int) -> None:
            session = Session()
            try:
                w = CreditsService(session).create_withdrawal(
                    organization_id=org_id,
                    credits_amount=500,
                )
                session.commit()
                results.put(("success", thread_id, w.id))
            except ValueError as exc:
                # Race-loss: once the single 500-credit slot is taken, later
                # callers fail create_withdrawal's withdrawable pre-check. With
                # create_withdrawal locking the org row FOR UPDATE up front,
                # threads serialize cleanly (no deadlock, no balance-guard
                # InsufficientCreditsError leak), so a non-ValueError below is a
                # genuine failure — `assert not errors` is the regression guard
                # for the lock-order fix (credits_service.create_withdrawal).
                session.rollback()
                results.put(("rejected", thread_id, str(exc)))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=withdrawal_worker, args=(i,), name=f"sc2-wd-{i}")
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        alive = [t.name for t in threads if t.is_alive()]
        assert not alive, f"Threads still alive after 30s: {alive}"

        successes = 0
        rejections = 0
        errors = []
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            elif r[0] == "rejected":
                rejections += 1
            else:
                errors.append(r)

        assert not errors, (
            f"Unexpected errors during concurrent withdrawals: {errors}. "
            f"Stop-the-line — escalate if production trace shows real race."
        )

        # DB side-effect via fresh session: exactly one withdrawal row.
        fresh = Session()
        try:
            wd_rows = fresh.query(Withdrawal).filter(Withdrawal.organization_id == org_id).all()
            assert len(wd_rows) == 1, (
                f"SC2 violation: concurrent create_withdrawal produced {len(wd_rows)} "
                f"rows on a 500-credit balance with 10 concurrent 500-credit requests; "
                f"endpoint lacks at-most-one-effect guard. Stop-the-line — escalate."
            )
            assert successes == 1, (
                f"Expected exactly 1 successful withdrawal, got {successes} "
                f"(rejections={rejections})"
            )
            # Aggregate side-effect: credits_balance drops by exactly 500
            # (single 500-credit WITHDRAWAL applied, no over-deduction).
            org_fresh = fresh.query(Organization).filter(Organization.id == org_id).first()
            assert org_fresh.credits_balance == 0, (
                f"Expected credits_balance=0 after single 500-credit withdrawal, "
                f"got {org_fresh.credits_balance}. Multiple withdrawals fired."
            )
            # Audit-trail check: exactly one matching CreditTransaction of type
            # WITHDRAWAL was written (in addition to the seeded SALE_EARNING).
            wd_txns = (
                fresh.query(CreditTransaction)
                .filter(
                    CreditTransaction.organization_id == org_id,
                    CreditTransaction.transaction_type == TransactionType.WITHDRAWAL.value,
                )
                .all()
            )
            assert len(wd_txns) == 1, f"Expected 1 WITHDRAWAL transaction, got {len(wd_txns)}"
        finally:
            fresh.close()

    def test_concurrent_admin_credit_adjust_same_reference_at_most_one_effect(
        self, db_engine, db_session
    ):
        """SC2: 10 concurrent admin credit adjustments with the SAME
        (reference_type, reference_id) tuple commit at-most-one transaction.

        Mirrors the dedup invariant POST /api/v2/admin/credits/adjust enforces
        via record_transaction's reference-id idempotency check + the partial
        unique index `uq_credit_txn_reference` on credit_transactions. 10
        threads each post an ADJUSTMENT for +100 credits with the same
        reference key — only ONE row may land; the rest must return the
        existing transaction (idempotent) or fail with IntegrityError caught
        by record_transaction's idempotency retry.

        Variant A (threading.Thread + per-thread sessionmaker) per D-02 + the
        CR-03 idiom from tests/test_credit_race_conditions.py:60-109.
        """
        import queue
        import threading

        from sqlalchemy.orm import sessionmaker

        from app.models import CreditTransaction, Organization, TransactionType
        from app.services.credits_service import CreditsService
        from app.shared.utils.id_generator import generate_id

        org_id = generate_id("org_")
        org = Organization(
            id=org_id,
            name="SC2 Admin Adjust Org",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()

        ref_id = "sc2_admin_adjust_dedup_001"
        ref_type = "admin_adjustment"
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def adjust_worker(thread_id: int) -> None:
            session = Session()
            try:
                txn = CreditsService(session).record_transaction(
                    organization_id=org_id,
                    transaction_type=TransactionType.ADJUSTMENT,
                    credits_amount=100,
                    description=f"SC2 dedup adjust {thread_id}",
                    reference_type=ref_type,
                    reference_id=ref_id,
                )
                session.commit()
                results.put(("ok", thread_id, txn.id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=adjust_worker, args=(i,), name=f"sc2-adj-{i}")
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        alive = [t.name for t in threads if t.is_alive()]
        assert not alive, f"Threads still alive after 30s: {alive}"

        outcomes = []
        while not results.empty():
            outcomes.append(results.get())
        assert len(outcomes) == 10

        # Per-thread should succeed (the service is idempotent: returns
        # existing row on duplicate). Tolerate IntegrityError-wrapping in
        # the race-loser path — those threads must NOT have created a new row.
        successes = [o for o in outcomes if o[0] == "ok"]
        assert successes, f"All threads failed: {outcomes}"

        # DB invariant via fresh session: exactly ONE adjustment row.
        fresh = Session()
        try:
            adj_rows = (
                fresh.query(CreditTransaction)
                .filter(
                    CreditTransaction.organization_id == org_id,
                    CreditTransaction.transaction_type == TransactionType.ADJUSTMENT.value,
                    CreditTransaction.reference_type == ref_type,
                    CreditTransaction.reference_id == ref_id,
                )
                .all()
            )
            assert len(adj_rows) == 1, (
                f"SC2 violation: 10 concurrent ADJUSTMENT calls with the same "
                f"reference_id produced {len(adj_rows)} rows; uq_credit_txn_reference "
                f"partial unique index is NOT preventing duplicates. "
                f"Stop-the-line — escalate."
            )
            # Response-body identity: every successful caller saw the same
            # transaction id (idempotent service contract).
            seen_ids = {o[2] for o in successes}
            assert seen_ids == {adj_rows[0].id}, (
                f"Idempotency drift: successful threads returned different txn ids: "
                f"{seen_ids} (expected {{ {adj_rows[0].id} }})"
            )
            # Aggregate: balance went up by exactly 100, not 100 * N.
            org_fresh = fresh.query(Organization).filter(Organization.id == org_id).first()
            assert org_fresh.credits_balance == 1100, (
                f"Expected credits_balance=1100 (1000 + single +100 adjust), "
                f"got {org_fresh.credits_balance}"
            )
        finally:
            fresh.close()


class TestSC5FinancialIdempotency:
    """SC5 sequential idempotency-duplicate tests for financial-endpoint
    service paths backed by record_transaction's reference_id dedup.

    Mirrors tests/test_cancel_refund_idempotency.py:46 (CR-01) sequential
    variant — 2-3 duplicate calls with the same (reference_type, reference_id)
    must commit exactly ONE row + return the SAME transaction id +
    aggregate-state matches a single-effect.
    """

    def test_duplicate_admin_adjust_with_same_reference_creates_one_row(
        self, db_session, test_organization
    ):
        """SC5: 3 sequential admin ADJUSTMENT calls with the same reference_id
        commit exactly 1 row + the org balance increases by exactly the credit
        amount once (not 3x).

        Pattern adapted from tests/test_cancel_refund_idempotency.py:46-193
        (CR-01 sequential variant).
        """
        from app.models import CreditTransaction, TransactionType

        ref_id = "sc5_admin_adjust_dup_001"
        ref_type = "admin_adjustment"
        amount = 250

        starting_balance = test_organization.credits_balance
        service = CreditsService(db_session)

        first = service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.ADJUSTMENT,
            credits_amount=amount,
            description="First adjust (SC5)",
            reference_type=ref_type,
            reference_id=ref_id,
        )
        db_session.commit()

        second = service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.ADJUSTMENT,
            credits_amount=amount,
            description="Second adjust (SC5, should be no-op)",
            reference_type=ref_type,
            reference_id=ref_id,
        )
        db_session.commit()

        third = service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.ADJUSTMENT,
            credits_amount=amount,
            description="Third adjust (SC5, should be no-op)",
            reference_type=ref_type,
            reference_id=ref_id,
        )
        db_session.commit()

        # All three calls return the SAME transaction row (idempotent).
        assert first.id == second.id == third.id, (
            f"Idempotency violation: expected same transaction id across 3 calls, "
            f"got first={first.id} second={second.id} third={third.id}"
        )

        # Exactly 1 ADJUSTMENT row for this reference.
        count = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == test_organization.id,
                CreditTransaction.transaction_type == TransactionType.ADJUSTMENT.value,
                CreditTransaction.reference_type == ref_type,
                CreditTransaction.reference_id == ref_id,
            )
            .count()
        )
        assert count == 1, f"SC5 violation: expected 1 row, got {count}"

        # Aggregate balance: starting + single +amount, not + 3*amount.
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == starting_balance + amount, (
            f"Expected credits_balance={starting_balance + amount} (single effect), "
            f"got {test_organization.credits_balance}. Duplicate adjustments fired."
        )

    def test_duplicate_workspace_pool_allocation_with_same_workspace_creates_one_row(
        self, db_session, test_organization
    ):
        """SC5: 2 sequential workspace-pool allocations with the same
        (workspace_id) reference commit exactly 1 ADJUSTMENT row + org balance
        deducts by exactly the credit amount once (not 2x).

        Backs POST /api/v2/workspaces/{ws}/credits/allocate's idempotency
        contract: workspace_id functions as the dedup reference_id for the
        underlying ADJUSTMENT bookkeeping transaction (reference_type=
        'workspace_pool').

        Pattern adapted from tests/test_cancel_refund_idempotency.py:46-193
        (CR-01 sequential variant).
        """
        from app.models import CreditTransaction
        from app.models.workspace import Workspace
        from app.services import workspace_credits_service
        from app.shared.utils.datetime_helpers import utcnow

        ws_id = "wsp_sc5_dup_001"
        amount = 50

        # Workspace must exist (FK constraint on workspace_credit_pools).
        workspace = Workspace(
            id=ws_id,
            organization_id=test_organization.id,
            name="SC5 Workspace",
            is_active=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db_session.add(workspace)
        db_session.commit()

        starting_balance = test_organization.credits_balance
        # First allocation creates a pool + ADJUSTMENT row.
        workspace_credits_service.allocate_credits_to_pool(
            db=db_session, org=test_organization, workspace_id=ws_id, amount=amount
        )
        db_session.commit()

        # Second allocation with the SAME workspace_id MUST NOT double-deduct:
        # record_transaction's idempotency check returns the same ADJUSTMENT row.
        workspace_credits_service.allocate_credits_to_pool(
            db=db_session, org=test_organization, workspace_id=ws_id, amount=amount
        )
        db_session.commit()

        # Exactly 1 ADJUSTMENT row keyed by reference_type='workspace_pool' + ws_id.
        rows = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == test_organization.id,
                CreditTransaction.reference_type == "workspace_pool",
                CreditTransaction.reference_id == ws_id,
            )
            .all()
        )
        assert len(rows) == 1, (
            f"SC5 violation: expected 1 ADJUSTMENT row for workspace_pool/{ws_id}, "
            f"got {len(rows)}; idempotency dedup is NOT preventing duplicates."
        )

        # Aggregate: org balance deducted ONCE (not twice).
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == starting_balance - amount, (
            f"Expected credits_balance={starting_balance - amount} (single effect), "
            f"got {test_organization.credits_balance}. Duplicate allocations fired."
        )
