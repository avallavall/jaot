"""Tests for financial bug fixes (Phase 10).

Covers: FIN-02, FIN-03, FIN-05, FIN-08 (partial).
Verifies balance guard, idempotency, frozen org check, holding period,
withdrawable balance, minimum withdrawal, commission rate, admin created_by,
workspace audit trail, and self-purchase block.
"""

from datetime import timedelta

import pytest

from app.models import (
    CreditTransaction,
    ModelCatalog,
    Organization,
    TransactionType,
)
from app.services.credits_service import CreditsService, InsufficientCreditsError
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class TestBalanceGuard:
    """D-17: record_transaction prevents negative balance on deduction paths."""

    def test_deduction_exceeding_balance_raises_error(self, db_session):
        """Deducting more than available balance raises InsufficientCreditsError."""
        org = Organization(
            id=generate_id("org_"),
            name="Test Org",
            credits_balance=100,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        with pytest.raises(InsufficientCreditsError) as exc_info:
            service.record_transaction(
                organization_id=org.id,
                transaction_type=TransactionType.EXECUTION,
                credits_amount=-200,
                description="Test deduction exceeding balance",
            )
        assert exc_info.value.credits_needed == 200
        assert exc_info.value.credits_available == 100

    def test_allow_negative_permits_negative_balance(self, db_session):
        """allow_negative=True allows balance to go below zero (D-06/D-07)."""
        org = Organization(
            id=generate_id("org_"),
            name="Test Org",
            credits_balance=50,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.REFUND_CLAWBACK,
            credits_amount=-100,
            description="Refund clawback",
            allow_negative=True,
        )
        assert txn.balance_after == -50
        db_session.refresh(org)
        assert org.credits_balance == -50

    def test_positive_transactions_always_allowed(self, db_session):
        """Positive credits (grants, refunds) never blocked by balance guard."""
        org = Organization(
            id=generate_id("org_"),
            name="Test Org",
            credits_balance=-50,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.REFUND,
            credits_amount=200,
            description="Refund",
        )
        assert txn.balance_after == 150

    def test_exact_balance_deduction_succeeds(self, db_session):
        """Deducting exactly the available balance succeeds (balance goes to 0)."""
        org = Organization(
            id=generate_id("org_"),
            name="Test Org",
            credits_balance=500,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-500,
            description="Exact balance deduction",
        )
        assert txn.balance_after == 0
        db_session.refresh(org)
        assert org.credits_balance == 0


class TestFrozenOrgCheck:
    """D-09: Frozen orgs cannot perform operations."""

    def test_frozen_org_blocked_on_deduction(self, db_session):
        """Deduction on frozen org raises ValueError."""
        org = Organization(
            id=generate_id("org_"),
            name="Frozen Org",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=True,
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        with pytest.raises(ValueError, match="frozen"):
            service.record_transaction(
                organization_id=org.id,
                transaction_type=TransactionType.EXECUTION,
                credits_amount=-10,
                description="Should be blocked",
            )

    def test_frozen_org_blocked_on_positive_purchase(self, db_session):
        """Even positive transactions on frozen org are blocked (unless allow_negative)."""
        org = Organization(
            id=generate_id("org_"),
            name="Frozen Org",
            credits_balance=100,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=True,
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        with pytest.raises(ValueError, match="frozen"):
            service.record_transaction(
                organization_id=org.id,
                transaction_type=TransactionType.PURCHASE,
                credits_amount=500,
                description="Should be blocked even for positive amount",
            )

    def test_frozen_org_allows_clawback(self, db_session):
        """allow_negative=True bypasses frozen check (admin-driven clawbacks)."""
        org = Organization(
            id=generate_id("org_"),
            name="Frozen Org",
            credits_balance=100,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=True,
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.CHARGEBACK_REVERSAL,
            credits_amount=-200,
            description="Chargeback clawback",
            allow_negative=True,
        )
        assert txn.balance_after == -100


class TestIdempotencyIntegrity:
    """D-18: Idempotency handles duplicate gracefully."""

    def test_duplicate_reference_returns_existing(self, db_session):
        """Second call with same reference returns existing transaction."""
        org = Organization(
            id=generate_id("org_"),
            name="Test",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn1 = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="First",
            reference_type="test",
            reference_id="ref_001",
        )
        txn2 = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="Duplicate",
            reference_type="test",
            reference_id="ref_001",
        )
        assert txn1.id == txn2.id  # Same transaction returned
        db_session.refresh(org)
        assert org.credits_balance == 990  # Only deducted once

    def test_different_reference_creates_new_transaction(self, db_session):
        """Different references create separate transactions."""
        org = Organization(
            id=generate_id("org_"),
            name="Test",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn1 = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="First",
            reference_type="test",
            reference_id="ref_A",
        )
        txn2 = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="Second",
            reference_type="test",
            reference_id="ref_B",
        )
        assert txn1.id != txn2.id
        db_session.refresh(org)
        assert org.credits_balance == 980


class TestHoldingPeriod:
    """D-10: SALE_EARNING has available_at set 14 days out."""

    def test_sale_earning_has_available_at(self, db_session):
        """SALE_EARNING transaction gets available_at ~14 days from now."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=100,
            description="Marketplace sale",
        )
        assert txn.available_at is not None
        # Should be approximately 14 days from now
        expected = utcnow() + timedelta(days=14)
        assert abs((txn.available_at - expected).total_seconds()) < 60

    def test_non_earning_has_no_available_at(self, db_session):
        """Non-SALE_EARNING transactions do NOT get available_at."""
        org = Organization(
            id=generate_id("org_"),
            name="Test",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="Solve",
        )
        assert txn.available_at is None


class TestWithdrawableBalance:
    """D-11: Withdrawable = matured SALE_EARNING - completed WITHDRAWAL."""

    def test_immature_earnings_not_withdrawable(self, db_session):
        """Earnings still in holding period are not withdrawable."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=500,
            description="Sale",
        )
        # available_at is 14 days out -- not matured yet
        withdrawable = service.get_withdrawable_balance(org.id)
        assert withdrawable == 0

    def test_matured_earnings_are_withdrawable(self, db_session):
        """Earnings past holding period are withdrawable."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=500,
            description="Sale",
        )
        # Manually set available_at to past
        txn.available_at = utcnow() - timedelta(days=1)
        db_session.flush()

        withdrawable = service.get_withdrawable_balance(org.id)
        assert withdrawable == 500

    def test_withdrawals_reduce_withdrawable(self, db_session):
        """Past withdrawals reduce withdrawable balance."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=500,
            credits_earned=500,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        # Record matured earning
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=500,
            description="Sale",
        )
        txn.available_at = utcnow() - timedelta(days=1)
        db_session.flush()

        # Record withdrawal
        service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.WITHDRAWAL,
            credits_amount=-200,
            description="Withdrawal",
        )
        db_session.flush()

        withdrawable = service.get_withdrawable_balance(org.id)
        assert withdrawable == 300  # 500 matured - 200 withdrawn


class TestMinimumWithdrawal:
    """D-15: Minimum withdrawal is 500 credits."""

    def test_withdrawal_below_minimum_rejected(self, db_session):
        """Withdrawal < 500 credits raises ValueError."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=1000,
            credits_earned=1000,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_onboarding_complete=True,
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        with pytest.raises(ValueError, match="Minimum withdrawal"):
            service.create_withdrawal(
                organization_id=org.id,
                credits_amount=100,
            )

    def test_withdrawal_requires_stripe_connect(self, db_session):
        """Withdrawal without Stripe Connect onboarding raises ValueError (D-05)."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=1000,
            credits_earned=1000,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_onboarding_complete=False,
        )
        db_session.add(org)
        db_session.flush()

        # Create matured earnings to satisfy withdrawable check
        service = CreditsService(db_session)
        txn = service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=1000,
            description="Sale",
        )
        txn.available_at = utcnow() - timedelta(days=1)
        db_session.flush()

        with pytest.raises(ValueError, match="Stripe Connect onboarding"):
            service.create_withdrawal(
                organization_id=org.id,
                credits_amount=500,
            )


class TestCommissionRateRecording:
    """Success criterion 14: Commission rate recorded on transactions."""

    def test_marketplace_sale_records_commission_rate(self, db_session):
        """record_marketplace_sale sets commission_rate on COMMISSION and SALE_EARNING."""
        seller = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        buyer = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add_all([seller, buyer])
        db_session.flush()

        service = CreditsService(db_session)
        buyer_tx, commission_tx, seller_tx = service.record_marketplace_sale(
            seller_organization_id=seller.id,
            buyer_organization_id=buyer.id,
            model_id="model_test",
            credits_price=100,
            commission_rate=0.15,
        )
        assert commission_tx.commission_rate == 0.15
        assert seller_tx.commission_rate == 0.15

    def test_marketplace_sale_correct_amounts(self, db_session):
        """record_marketplace_sale calculates commission and seller share correctly."""
        seller = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        buyer = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add_all([seller, buyer])
        db_session.flush()

        service = CreditsService(db_session)
        buyer_tx, commission_tx, seller_tx = service.record_marketplace_sale(
            seller_organization_id=seller.id,
            buyer_organization_id=buyer.id,
            model_id="model_test2",
            credits_price=1000,
            commission_rate=0.10,
        )
        # Buyer pays full price
        assert buyer_tx.credits_amount == -1000
        # Commission is 10% of 1000 = 100 (stored as audit, credits_amount=0)
        assert commission_tx.credits_amount == 0
        # Seller gets 1000 - 100 = 900
        assert seller_tx.credits_amount == 900


class TestAdminCreatedBy:
    """FIN-05: Admin credit adjustments record created_by."""

    def test_admin_adjust_credits_records_created_by(
        self, admin_client, db_session, test_organization
    ):
        """POST to admin credit adjustment endpoint records created_by from user."""
        response = admin_client.post(
            "/api/v2/admin/credits/adjust",
            json={
                "organization_id": test_organization.id,
                "amount": 500,
                "reason": "Test admin adjustment",
            },
        )
        assert response.status_code == 200
        data = response.json()
        txn_id = data["id"]

        # Verify the transaction has created_by set
        txn = db_session.query(CreditTransaction).filter(CreditTransaction.id == txn_id).first()
        assert txn is not None
        assert txn.created_by is not None
        assert txn.created_by != "unknown_admin"
        # Should be the admin user's ID
        assert txn.created_by.startswith("user_")

    # Missing-test #4: negative-amount validation on admin adjustment.

    def test_admin_adjust_credits_negative_over_balance_rejected(
        self, admin_client, db_session, test_organization
    ):
        """Negative adjustment that would drive balance below zero returns 400."""
        test_organization.credits_balance = 100
        db_session.commit()
        before_tx_count = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.organization_id == test_organization.id)
            .count()
        )

        response = admin_client.post(
            "/api/v2/admin/credits/adjust",
            json={
                "organization_id": test_organization.id,
                "amount": -500,  # would land at -400
                "reason": "Attempted over-deduction",
            },
        )
        assert response.status_code == 400
        assert "negative balance" in response.json()["detail"].lower()

        # No tx written, balance unchanged.
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == 100
        after_tx_count = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.organization_id == test_organization.id)
            .count()
        )
        assert after_tx_count == before_tx_count

    def test_admin_adjust_credits_missing_reason_rejected(self, admin_client, test_organization):
        """Missing required 'reason' field fails Pydantic validation with 422."""
        response = admin_client.post(
            "/api/v2/admin/credits/adjust",
            json={
                "organization_id": test_organization.id,
                "amount": 100,
                # reason omitted
            },
        )
        assert response.status_code == 422
        errors = response.json().get("detail", [])
        assert any("reason" in err.get("loc", []) for err in errors), (
            f"Expected validation error on 'reason' field, got {errors!r}"
        )

    def test_admin_adjust_credits_non_admin_rejected(self, authenticated_client, test_organization):
        """Non-admin users cannot hit the admin credit adjustment endpoint."""
        response = authenticated_client.post(
            "/api/v2/admin/credits/adjust",
            json={
                "organization_id": test_organization.id,
                "amount": 100,
                "reason": "Not an admin",
            },
        )
        assert response.status_code == 403

    def test_admin_adjust_credits_nonexistent_org_returns_404(self, admin_client, db_session):
        """Adjusting an unknown org returns 404 with no DB changes."""
        before_tx_count = db_session.query(CreditTransaction).count()
        response = admin_client.post(
            "/api/v2/admin/credits/adjust",
            json={
                "organization_id": "org_does_not_exist",
                "amount": 100,
                "reason": "Ghost org",
            },
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
        assert db_session.query(CreditTransaction).count() == before_tx_count


class TestWorkspaceAuditTrail:
    """FIN-02: Workspace pool allocation creates CreditTransaction record."""

    def test_pool_allocation_creates_transaction(self, db_session):
        """allocate_credits_to_pool creates CreditTransaction record."""
        from app.models.workspace import Workspace
        from app.services.workspace_credits_service import allocate_credits_to_pool

        org = Organization(
            id=generate_id("org_"),
            name="Test Org",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        workspace = Workspace(
            id=generate_id("ws_"),
            organization_id=org.id,
            name="Test Workspace",
        )
        db_session.add(workspace)
        db_session.flush()
        workspace_id = workspace.id

        # Count transactions before
        before_count = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.organization_id == org.id)
            .count()
        )

        allocate_credits_to_pool(
            db=db_session,
            org=org,
            workspace_id=workspace_id,
            amount=200,
        )
        db_session.flush()

        # Count transactions after
        after_count = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.organization_id == org.id)
            .count()
        )

        assert after_count == before_count + 1

        # Verify the transaction details
        txn = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org.id,
                CreditTransaction.reference_type == "workspace_pool",
            )
            .first()
        )
        assert txn is not None
        assert txn.credits_amount == -200
        assert txn.reference_id == workspace_id

    def test_pool_deduct_fallback_creates_transaction(self, db_session):
        """deduct_credits_for_solve org fallback creates CreditTransaction record."""
        from app.services.workspace_credits_service import deduct_credits_for_solve

        org = Organization(
            id=generate_id("org_"),
            name="Test Org",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        # No pool exists, so org balance fallback triggers
        result = deduct_credits_for_solve(
            db=db_session,
            org=org,
            workspace_id=None,
            credits_needed=50,
        )
        assert result == "org_balance"

        # Verify a CreditTransaction was created (not just direct balance mutation)
        txn = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.organization_id == org.id)
            .first()
        )
        assert txn is not None
        assert txn.credits_amount == -50


class TestSelfPurchaseBlock:
    """D-14: Self-purchase is blocked (buyer org == author org)."""

    @pytest.fixture(autouse=True)
    def _enable_monetization(self, enable_monetization):
        """Self-purchase block only fires on paid models; enable monetization."""

    def test_self_purchase_returns_403(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        """Activating your own model returns 403."""
        catalog_model = ModelCatalog(
            id=generate_id("cat_"),
            name="test_self_purchase_model",
            display_name="Self Purchase Test",
            description="Test model for self-purchase block",
            generator_type="knapsack",
            input_schema={},
            input_fields=[],
            example_input={},
            price_eur=10.0,
            status="published",
            is_public=True,
            is_official=False,
            author_organization_id=test_organization.id,
            total_activations=0,
            total_executions=0,
        )
        db_session.add(catalog_model)
        db_session.commit()

        response = authenticated_client.post(
            f"/api/v2/models/catalog/{catalog_model.id}/activate",
            json={"custom_name": "My Copy"},
        )
        assert response.status_code == 403
        assert "own model" in response.json()["detail"].lower()
