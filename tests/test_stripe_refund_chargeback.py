"""Tests for Stripe refund and chargeback webhook handlers (Phase 10).

Covers: FIN-01, D-06, D-07, D-08, D-09.
Verifies: charge.refunded clawback, charge.dispute.created freeze + chargeback count,
permanent ban at 3+ chargebacks, dispute closed unfreeze vs permanent ban.
"""

from app.models import Organization, TransactionType
from app.services.credits_service import CreditsService
from app.services.stripe_service import StripeService
from app.shared.utils.id_generator import generate_id


class TestRefundWebhook:
    """charge.refunded webhook handler claws back credits (D-06, FIN-01)."""

    def test_refund_allows_negative_balance(self, db_session):
        """Refund clawback can push balance negative (D-06)."""
        org = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=50,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            stripe_customer_id="cus_neg_test",
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_refunded(
            {
                "id": "ch_neg_refund",
                "customer": "cus_neg_test",
                "amount_refunded": 1000,  # 10 EUR = 100 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "refund_clawback"
        assert result["credits"] == 100
        db_session.refresh(org)
        assert org.credits_balance == -50  # 50 - 100 = -50

    def test_refund_zero_amount_skipped(self, db_session):
        """Zero refund amount is skipped."""
        org = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=500,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_refunded(
            {
                "id": "ch_zero",
                "amount_refunded": 0,
                "metadata": {"organization_id": org.id},
            }
        )
        assert result["action"] == "skipped"
        assert result["reason"] == "zero refund amount"

    def test_refund_org_not_found_skipped(self, db_session):
        """Refund with no org metadata is skipped."""
        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_refunded(
            {
                "id": "ch_unknown",
                "amount_refunded": 1000,
                "metadata": {},
            }
        )
        assert result["action"] == "skipped"
        assert result["reason"] == "org not found"


class TestChargebackWebhook:
    """charge.dispute.created webhook handler (D-07, D-08, D-09, FIN-01)."""

    def test_dispute_created_freezes_org(self, db_session):
        """charge.dispute.created freezes org."""
        org = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=False,
            chargeback_count=0,
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_dispute_created(
            {
                "id": "dp_freeze_test",
                "amount": 5000,  # 50 EUR = 500 credits
                "charge": "ch_freeze_test",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "chargeback_freeze"
        db_session.refresh(org)
        assert org.is_frozen is True

    def test_dispute_created_increments_chargeback_count(self, db_session):
        """Chargeback count incremented (D-07)."""
        org = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=False,
            chargeback_count=0,
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_dispute_created(
            {
                "id": "dp_count_test",
                "amount": 1000,
                "charge": "ch_count_test",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["chargeback_count"] == 1
        db_session.refresh(org)
        assert org.chargeback_count == 1

    def test_dispute_created_claws_back_credits(self, db_session):
        """Chargeback claws back the disputed amount."""
        org = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=False,
            chargeback_count=0,
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_dispute_created(
            {
                "id": "dp_claw_test",
                "amount": 5000,  # 50 EUR = 500 credits
                "charge": "ch_claw_test",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["credits_clawed"] == 500
        db_session.refresh(org)
        assert org.credits_balance == 500  # 1000 - 500

    def test_dispute_created_reverses_seller_earning(self, db_session):
        """Marketplace chargeback reverses seller SALE_EARNING (D-08)."""
        buyer = Organization(
            id=generate_id("org_"),
            name="Buyer",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=False,
            chargeback_count=0,
        )
        seller = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add_all([buyer, seller])
        db_session.flush()

        cs = CreditsService(db_session)
        # Record the original purchase transaction (buyer paid via Stripe)
        cs.record_transaction(
            organization_id=buyer.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-500,
            description="Model purchase",
            reference_type="stripe",
            reference_id="ch_market_dispute",
            buyer_organization_id=buyer.id,
        )
        # Record seller earning
        cs.record_transaction(
            organization_id=seller.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=450,
            description="Marketplace sale",
            reference_type="stripe",
            reference_id="ch_market_dispute",
            buyer_organization_id=buyer.id,
        )
        db_session.flush()

        initial_seller_balance = seller.credits_balance

        # Now a chargeback occurs on the buyer's charge
        stripe_service = StripeService(db_session)
        stripe_service._handle_charge_dispute_created(
            {
                "id": "dp_market_test",
                "amount": 5000,  # 50 EUR = 500 credits
                "charge": "ch_market_dispute",
                "metadata": {"organization_id": buyer.id},
            }
        )
        db_session.flush()

        # Seller balance should be reduced by the earning amount
        db_session.refresh(seller)
        assert seller.credits_balance == initial_seller_balance - 450

    def test_third_chargeback_triggers_permanent_ban(self, db_session):
        """D-07: 3rd chargeback sets permanent_ban=True."""
        org = Organization(
            id=generate_id("org_"),
            name="Repeat Offender",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=False,
            chargeback_count=2,
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_dispute_created(
            {
                "id": "dp_ban_test",
                "amount": 5000,
                "charge": "ch_ban_test",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["permanent_ban"] is True
        assert result["chargeback_count"] == 3
        db_session.refresh(org)
        assert org.is_frozen is True
        assert org.chargeback_count == 3


class TestDisputeClosedWebhook:
    """charge.dispute.closed webhook handler (D-07 permanent ban enforcement)."""

    def test_dispute_won_unfreezes_org(self, db_session):
        """charge.dispute.closed with status=won unfreezes org (chargeback_count < 3)."""
        org = Organization(
            id=generate_id("org_"),
            name="Lucky Org",
            credits_balance=500,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=True,
            chargeback_count=1,
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.CHARGEBACK_REVERSAL,
            credits_amount=-200,
            description="Original chargeback",
            reference_type="stripe_dispute",
            reference_id="dp_won_test",
            allow_negative=True,
        )
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_dispute_closed(
            {
                "id": "dp_won_test",
                "status": "won",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "dispute_won_unfrozen"
        db_session.refresh(org)
        assert org.is_frozen is False

    def test_dispute_won_restores_credits(self, db_session):
        """Won dispute restores the clawed-back credits."""
        org = Organization(
            id=generate_id("org_"),
            name="Credit Restore Org",
            credits_balance=300,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=True,
            chargeback_count=1,
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.CHARGEBACK_REVERSAL,
            credits_amount=-200,
            description="Original chargeback",
            reference_type="stripe_dispute",
            reference_id="dp_restore_test",
            allow_negative=True,
        )
        db_session.flush()
        db_session.refresh(org)
        balance_after_chargeback = org.credits_balance  # 300 - 200 = 100

        stripe_service = StripeService(db_session)
        stripe_service._handle_charge_dispute_closed(
            {
                "id": "dp_restore_test",
                "status": "won",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        db_session.refresh(org)
        # Credits should be restored by +200
        assert org.credits_balance == balance_after_chargeback + 200

    def test_dispute_won_does_not_unfreeze_permanent_ban(self, db_session):
        """D-07: dispute won does NOT unfreeze when chargeback_count >= 3."""
        org = Organization(
            id=generate_id("org_"),
            name="Banned Org",
            credits_balance=-500,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=True,
            chargeback_count=3,
        )
        db_session.add(org)
        db_session.flush()

        service = CreditsService(db_session)
        service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.CHARGEBACK_REVERSAL,
            credits_amount=-500,
            description="Original chargeback",
            reference_type="stripe_dispute",
            reference_id="dp_perm_ban",
            allow_negative=True,
        )
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_dispute_closed(
            {
                "id": "dp_perm_ban",
                "status": "won",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        # Credits restored but org stays frozen
        assert result["action"] == "dispute_won_still_banned"
        db_session.refresh(org)
        assert org.is_frozen is True  # Still frozen (permanent ban)

    def test_dispute_lost_stays_frozen(self, db_session):
        """Lost dispute keeps org frozen, no credits restored."""
        org = Organization(
            id=generate_id("org_"),
            name="Lost Dispute Org",
            credits_balance=500,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_frozen=True,
            chargeback_count=1,
        )
        db_session.add(org)
        db_session.flush()

        stripe_service = StripeService(db_session)
        result = stripe_service._handle_charge_dispute_closed(
            {
                "id": "dp_lost_test",
                "status": "lost",
                "metadata": {"organization_id": org.id},
            }
        )

        assert result["action"] == "dispute_closed_lost"
        db_session.refresh(org)
        assert org.is_frozen is True  # Stays frozen
