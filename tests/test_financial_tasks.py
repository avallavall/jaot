"""Tests for financial Celery tasks, admin withdrawal endpoints, and reconciliation (Phase 10).

Covers: FIN-04, FIN-06, FIN-07, FIN-09.
Verifies: scheduled withdrawal processing, ReconciliationService via direct call,
admin withdrawal list/approve/reject, checkout invoice creation.
"""

import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models import (
    CreditTransaction,
    Organization,
    ScheduleAmountType,
    ScheduleFrequency,
    TransactionType,
    Withdrawal,
    WithdrawalSchedule,
    WithdrawalStatus,
)
from app.services.credits_service import CreditsService
from app.services.reconciliation_service import ReconciliationService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


class TestReconciliation:
    """FIN-09: ReconciliationService detects balance discrepancies."""

    def test_detects_discrepancy(self, db_session):
        """run_reconciliation detects SUM(transactions) != credits_balance."""
        org = Organization(
            id=generate_id("org_"),
            name="Discrepancy Org",
            credits_balance=999,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        # Add a single transaction that doesn't match the org balance
        txn = CreditTransaction(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            transaction_type="purchase",
            credits_amount=500,
            balance_after=500,
            description="Initial purchase",
        )
        db_session.add(txn)
        db_session.flush()
        # balance=999, sum(txns)=500 -> discrepancy

        service = ReconciliationService(db_session)
        result = service.run_reconciliation()
        assert result["discrepancies"] > 0
        org_discrepancies = [d for d in result["details"] if d["organization_id"] == org.id]
        assert len(org_discrepancies) == 1
        assert org_discrepancies[0]["computed_balance"] == 500
        assert org_discrepancies[0]["actual_balance"] == 999
        assert org_discrepancies[0]["difference"] == 499

    def test_clean_reconciliation(self, db_session):
        """No discrepancies when data is consistent."""
        org = Organization(
            id=generate_id("org_"),
            name="Clean Org",
            credits_balance=500,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        txn = CreditTransaction(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            transaction_type="purchase",
            credits_amount=500,
            balance_after=500,
            description="Initial purchase",
        )
        db_session.add(txn)
        db_session.flush()

        service = ReconciliationService(db_session)
        result = service.run_reconciliation()
        # This org should not appear in discrepancies
        org_discrepancies = [d for d in result["details"] if d["organization_id"] == org.id]
        assert len(org_discrepancies) == 0

    def test_detects_no_transaction_org(self, db_session):
        """Detects orgs with non-zero balance but no transactions (excluding default 100)."""
        org = Organization(
            id=generate_id("org_"),
            name="Seeded Org",
            credits_balance=999,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()
        # No transactions at all, balance is 999 (not default 100)

        service = ReconciliationService(db_session)
        result = service.run_reconciliation()
        org_discrepancies = [d for d in result["details"] if d["organization_id"] == org.id]
        assert len(org_discrepancies) == 1
        assert "No CreditTransaction records found" in org_discrepancies[0].get("note", "")

    def test_default_balance_100_not_flagged(self, db_session):
        """Orgs with default balance=100 and no transactions are NOT flagged."""
        org = Organization(
            id=generate_id("org_"),
            name="Default Org",
            credits_balance=100,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = ReconciliationService(db_session)
        result = service.run_reconciliation()
        org_discrepancies = [d for d in result["details"] if d["organization_id"] == org.id]
        assert len(org_discrepancies) == 0


class TestScheduledWithdrawals:
    """FIN-06: Scheduled withdrawal processing."""

    def test_process_due_schedules(self, db_session):
        """process_scheduled_withdrawals processes due schedules."""
        org = Organization(
            id=generate_id("org_"),
            name="Scheduled Seller",
            credits_balance=5000,
            credits_earned=5000,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_onboarding_complete=True,
        )
        db_session.add(org)
        db_session.flush()

        # Create matured earnings (available_at in the past)
        cs = CreditsService(db_session)
        txn = cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=5000,
            description="Sale earnings",
        )
        txn.available_at = utcnow() - timedelta(days=1)
        db_session.flush()

        # Create a schedule with next_execution in the past (due now)
        schedule = WithdrawalSchedule(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            frequency=ScheduleFrequency.WEEKLY.value,
            amount_type=ScheduleAmountType.ALL.value,
            amount_value=None,
            min_threshold=100,
            next_execution=utcnow() - timedelta(hours=1),
            is_active=True,
        )
        db_session.add(schedule)
        db_session.flush()

        withdrawals = cs.process_scheduled_withdrawals()
        assert len(withdrawals) >= 1
        assert withdrawals[0].organization_id == org.id
        assert withdrawals[0].credits_amount > 0

    def test_inactive_schedule_skipped(self, db_session):
        """Inactive schedules are not processed."""
        org = Organization(
            id=generate_id("org_"),
            name="Inactive Seller",
            credits_balance=5000,
            credits_earned=5000,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_onboarding_complete=True,
        )
        db_session.add(org)
        db_session.flush()

        schedule = WithdrawalSchedule(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            frequency=ScheduleFrequency.WEEKLY.value,
            amount_type=ScheduleAmountType.ALL.value,
            min_threshold=100,
            next_execution=utcnow() - timedelta(hours=1),
            is_active=False,
        )
        db_session.add(schedule)
        db_session.flush()

        cs = CreditsService(db_session)
        withdrawals = cs.process_scheduled_withdrawals()
        assert len(withdrawals) == 0

    def test_future_schedule_not_processed(self, db_session):
        """Schedules with future next_execution are not processed."""
        org = Organization(
            id=generate_id("org_"),
            name="Future Seller",
            credits_balance=5000,
            credits_earned=5000,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_onboarding_complete=True,
        )
        db_session.add(org)
        db_session.flush()

        schedule = WithdrawalSchedule(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            frequency=ScheduleFrequency.WEEKLY.value,
            amount_type=ScheduleAmountType.ALL.value,
            min_threshold=100,
            next_execution=utcnow() + timedelta(days=7),
            is_active=True,
        )
        db_session.add(schedule)
        db_session.flush()

        cs = CreditsService(db_session)
        withdrawals = cs.process_scheduled_withdrawals()
        assert len(withdrawals) == 0


class TestAdminWithdrawals:
    """FIN-04: Admin withdrawal list, approve, reject."""

    @pytest.fixture(autouse=True)
    def _enable_monetization(self, enable_monetization):
        """Admin withdrawal endpoints are paid-only; enable monetization for this class."""

    def _create_pending_withdrawal(self, db_session, org):
        """Helper to create a pending withdrawal."""
        withdrawal = Withdrawal(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            withdrawal_type="manual",
            credits_amount=500,
            credits_per_eur=10,
            eur_amount=50.0,
            target_currency="EUR",
            exchange_rate=1.0,
            local_amount=50.0,
            status=WithdrawalStatus.PENDING.value,
        )
        db_session.add(withdrawal)
        db_session.flush()
        return withdrawal

    def test_list_pending_withdrawals(self, admin_client, db_session, test_organization):
        """GET /admin/withdrawals?status=pending returns pending withdrawals."""
        withdrawal = self._create_pending_withdrawal(db_session, test_organization)
        db_session.commit()

        response = admin_client.get("/api/v2/admin/withdrawals?status=pending")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        ids = [w["id"] for w in data["items"]]
        assert withdrawal.id in ids

    def test_reject_withdrawal_refunds_credits(self, admin_client, db_session, test_organization):
        """POST /admin/withdrawals/{id}/reject refunds credits."""
        withdrawal = self._create_pending_withdrawal(db_session, test_organization)

        # Also create a WITHDRAWAL transaction that deducted credits
        cs = CreditsService(db_session)
        cs.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.WITHDRAWAL,
            credits_amount=-500,
            description="Withdrawal deduction",
            reference_type="withdrawal",
            reference_id=withdrawal.id,
        )
        db_session.commit()
        db_session.refresh(test_organization)
        balance_after_deduction = test_organization.credits_balance

        response = admin_client.post(
            f"/api/v2/admin/withdrawals/{withdrawal.id}/reject",
            json={"reason": "Test rejection"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == WithdrawalStatus.FAILED.value

        # Verify credits were refunded
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == balance_after_deduction + 500

    def test_reject_nonexistent_withdrawal_404(self, admin_client):
        """Rejecting non-existent withdrawal returns 404."""
        response = admin_client.post(
            "/api/v2/admin/withdrawals/nonexistent/reject",
            json={"reason": "Test"},
        )
        assert response.status_code == 404

    @patch("app.api.v2.routes.admin.withdrawals.StripeConnectService")
    def test_approve_withdrawal_triggers_payout(
        self, mock_connect_cls, admin_client, db_session, test_organization
    ):
        """POST /admin/withdrawals/{id}/approve triggers Stripe payout."""
        # Set up org for approval
        test_organization.stripe_connect_onboarding_complete = True
        test_organization.stripe_connect_account_id = "acct_test"
        db_session.flush()

        withdrawal = self._create_pending_withdrawal(db_session, test_organization)
        db_session.commit()

        # Mock StripeConnectService
        mock_service = MagicMock()
        mock_connect_cls.return_value = mock_service
        mock_service.has_accepted_seller_tos.return_value = True
        mock_service.create_payout.return_value = "tr_test_approve"

        response = admin_client.post(
            f"/api/v2/admin/withdrawals/{withdrawal.id}/approve",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["stripe_transfer_id"] == "tr_test_approve"

        # Verify withdrawal status
        db_session.refresh(withdrawal)
        assert withdrawal.status == WithdrawalStatus.COMPLETED.value
        assert withdrawal.stripe_transfer_id == "tr_test_approve"


class TestInvoiceIntegration:
    """FIN-07: Checkout persists a real Invoice row to the DB."""

    @patch("app.services.stripe_service.StripeService.is_configured", return_value=True)
    def test_checkout_creates_invoice(self, mock_configured, db_session):
        """checkout.session.completed persists a subscription Invoice (FIN-07)."""
        from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
        from app.services.stripe_service import StripeService

        org = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_checkout_completed(
            {
                "id": "cs_test_invoice",
                "subscription": "sub_test",
                "payment_intent": "pi_test",
                "metadata": {
                    "organization_id": org.id,
                    "type": "subscription",
                    "plan": "pro",
                    "credits": "5000",
                },
            }
        )

        assert result["action"] == "subscription_activated"

        # Real DB round-trip: Invoice row must exist with the right fields.
        invoices = db_session.query(Invoice).filter(Invoice.organization_id == org.id).all()
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.invoice_type == InvoiceType.SUBSCRIPTION.value
        assert invoice.status == InvoiceStatus.PAID.value
        assert invoice.org_name == "Buyer"
        # Pro plan monthly price = €49, 2500 credits granted.
        assert invoice.subtotal_eur == 49.0
        assert invoice.total_eur == 49.0
        assert invoice.credits_granted == 2500
        assert invoice.stripe_payment_intent_id == "pi_test"
        assert invoice.invoice_number.startswith("INV-")

    @patch("app.services.stripe_service.StripeService.is_configured", return_value=True)
    def test_topup_checkout_creates_invoice(self, mock_configured, db_session):
        """Topup checkout.session.completed persists a topup Invoice row."""
        from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
        from app.services.stripe_service import StripeService

        org = Organization(
            id=generate_id("org_"),
            name="Topup Buyer",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_checkout_completed(
            {
                "id": "cs_topup_invoice",
                "payment_intent": "pi_topup",
                "metadata": {
                    "organization_id": org.id,
                    "type": "topup",
                    "credits": "2000",
                },
            }
        )

        assert result["action"] == "topup_completed"
        assert result["credits"] == 2000

        # Real DB round-trip: Invoice row must exist with the right fields.
        invoices = db_session.query(Invoice).filter(Invoice.organization_id == org.id).all()
        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.invoice_type == InvoiceType.TOPUP.value
        assert invoice.status == InvoiceStatus.PAID.value
        assert invoice.org_name == "Topup Buyer"
        # Topup of 2000 credits costs €48 per TOPUP_PRICES_EUR.
        assert invoice.subtotal_eur == 48.0
        assert invoice.credits_granted == 2000
        assert invoice.stripe_payment_intent_id == "pi_topup"


class TestAdminReconciliation:
    """FIN-09: Admin manual reconciliation trigger."""

    def test_manual_reconciliation_endpoint(self, admin_client, db_session):
        """POST /admin/reconciliation/run returns concrete reconciliation results.

        Seeds a known discrepancy (positive credits_balance on an org with NO
        transactions) so the reconciliation service must flag exactly 1.
        """
        # Seed a bad-state org: non-default balance with no matching tx rows.
        bad_org = Organization(
            id=generate_id("org_"),
            name="Recon Discrepancy",
            credits_balance=777,
            credits_earned=0,
            monthly_quota=0,
            currency="EUR",
        )
        db_session.add(bad_org)
        db_session.commit()

        response = admin_client.post("/api/v2/admin/reconciliation/run")
        assert response.status_code == 200
        data = response.json()
        assert data["checked"] >= 1
        assert data["discrepancies"] >= 1

        # The seeded bad_org must be in the details list.
        details = data["details"]
        assert isinstance(details, list)
        flagged_org_ids = {d.get("organization_id") for d in details}
        assert bad_org.id in flagged_org_ids, (
            f"Seeded discrepancy org {bad_org.id} not flagged; got {flagged_org_ids}"
        )
