"""Extended refund and chargeback tests (Task 3.9).

Tests exercise ACTUAL DB state changes for refund and chargeback scenarios
that go beyond the basic coverage in test_stripe_refund_chargeback.py.

Covers:
1. Refund of a top-up -- credits deducted from org
2. Refund of a subscription -- subscription cancelled, plan downgraded
3. Chargeback event handling -- org frozen, credits clawed, chargeback_count
4. Partial refund handling -- only refunded portion is clawed back
5. Refund when user has already spent credits -- negative balance scenario
6. Multiple sequential refunds on the same charge
7. Chargeback escalation path (1 -> 2 -> 3 chargebacks)
8. Refund found via stripe_customer_id (no org_id in metadata)
"""

from app.models import CreditTransaction, Organization, TransactionType
from app.services.credits_service import CreditsService
from app.services.stripe_service import StripeService
from app.shared.utils.id_generator import generate_id


def _make_org(db_session, *, balance=1000, plan="free", **kwargs):
    """Create and persist a test organization."""
    defaults = dict(
        id=generate_id("org_"),
        name="Refund Test Org",
        plan=plan,
        credits_balance=balance,
        credits_earned=0,
        monthly_quota=100,
        currency="EUR",
        is_active=True,
        is_frozen=False,
        chargeback_count=0,
    )
    defaults.update(kwargs)
    org = Organization(**defaults)
    db_session.add(org)
    db_session.flush()
    return org


def _count_transactions(db_session, org_id, txn_type=None):
    """Count credit transactions for an org, optionally filtered by type."""
    q = db_session.query(CreditTransaction).filter(CreditTransaction.organization_id == org_id)
    if txn_type:
        q = q.filter(CreditTransaction.transaction_type == txn_type.value)
    return q.count()


class TestTopupRefund:
    """Refund of a top-up purchase should deduct the credited amount."""

    def test_full_topup_refund_deducts_credits(self, db_session):
        """Full refund of a 500-credit top-up (50 EUR) deducts 500 credits."""
        org = _make_org(db_session, balance=0)

        # Simulate the original top-up
        cs = CreditsService(db_session)
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=500,
            description="Credit top-up: 500 credits",
            reference_type="stripe",
            reference_id="ch_topup_refund_001",
        )
        db_session.flush()
        db_session.refresh(org)
        assert org.credits_balance == 500

        # Process refund webhook
        ss = StripeService(db_session)
        result = ss._handle_charge_refunded(
            {
                "id": "ch_topup_refund_001",
                "customer": None,
                "amount_refunded": 5000,  # 50 EUR * 100 cents = 5000 cents
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "refund_clawback"
        assert result["credits"] == 500  # 50 EUR * 10 credits/EUR
        db_session.refresh(org)
        assert org.credits_balance == 0  # 500 - 500

    def test_topup_refund_creates_clawback_transaction(self, db_session):
        """Refund creates a REFUND_CLAWBACK transaction record."""
        org = _make_org(db_session, balance=500)

        ss = StripeService(db_session)
        ss._handle_charge_refunded(
            {
                "id": "ch_topup_txn_001",
                "amount_refunded": 2000,  # 20 EUR = 200 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        txn = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org.id,
                CreditTransaction.transaction_type == TransactionType.REFUND_CLAWBACK.value,
            )
            .one()
        )
        assert txn.credits_amount == -200
        assert txn.reference_type == "stripe_refund"
        assert txn.reference_id == "ch_topup_txn_001"

    def test_topup_refund_balance_after_is_correct(self, db_session):
        """The balance_after on the clawback transaction is accurate."""
        org = _make_org(db_session, balance=800)

        ss = StripeService(db_session)
        ss._handle_charge_refunded(
            {
                "id": "ch_bal_after",
                "amount_refunded": 3000,  # 30 EUR = 300 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        txn = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org.id,
                CreditTransaction.transaction_type == TransactionType.REFUND_CLAWBACK.value,
            )
            .one()
        )
        assert txn.balance_after == 500  # 800 - 300


class TestSubscriptionRefund:
    """Refund for a subscription payment deducts credits.

    Note: Stripe sends charge.refunded, not customer.subscription.deleted,
    for refunds. The subscription deletion is a separate event. But the
    refund handler should still claw back the credits that were granted.
    """

    def test_subscription_refund_claws_back_plan_credits(self, db_session):
        """Refund of a subscription payment claws back granted credits."""
        org = _make_org(db_session, balance=0, plan="pro")
        org.stripe_subscription_id = "sub_refund_001"
        db_session.flush()

        # Simulate original subscription grant
        cs = CreditsService(db_session)
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=2500,
            description="Subscription activated: PRO plan",
            reference_type="stripe",
            reference_id="ch_sub_refund_orig",
        )
        db_session.flush()
        db_session.refresh(org)
        assert org.credits_balance == 2500

        # Simulate refund of the subscription charge
        ss = StripeService(db_session)
        result = ss._handle_charge_refunded(
            {
                "id": "ch_sub_refund_orig",
                "amount_refunded": 25000,  # 250 EUR = 2500 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "refund_clawback"
        assert result["credits"] == 2500
        db_session.refresh(org)
        assert org.credits_balance == 0

    def test_subscription_deletion_after_refund(self, db_session):
        """After refund + subscription.deleted, org is on free plan."""
        org = _make_org(db_session, balance=2500, plan="pro")
        org.stripe_subscription_id = "sub_del_after_refund"
        db_session.flush()

        ss = StripeService(db_session)

        # 1. Refund webhook
        ss._handle_charge_refunded(
            {
                "id": "ch_sub_del_ref",
                "amount_refunded": 25000,  # 250 EUR = 2500 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        # 2. Subscription deleted webhook
        ss._handle_subscription_deleted(
            {
                "id": "sub_del_after_refund",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        db_session.refresh(org)
        assert org.plan == "free"
        assert org.stripe_subscription_id is None
        assert org.credits_balance == 0


class TestChargebackHandling:
    """Full chargeback flow: freeze, claw back, count increment."""

    def test_chargeback_full_flow(self, db_session):
        """Single chargeback: freeze + clawback + count = 1, not permanent."""
        org = _make_org(db_session, balance=1000)

        ss = StripeService(db_session)
        result = ss._handle_charge_dispute_created(
            {
                "id": "dp_full_flow",
                "amount": 5000,  # 50 EUR = 500 credits
                "charge": "ch_full_flow",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "chargeback_freeze"
        assert result["credits_clawed"] == 500
        assert result["chargeback_count"] == 1
        assert result["permanent_ban"] is False

        db_session.refresh(org)
        assert org.is_frozen is True
        assert org.credits_balance == 500  # 1000 - 500
        assert org.chargeback_count == 1

    def test_chargeback_creates_reversal_transaction(self, db_session):
        """Chargeback creates a CHARGEBACK_REVERSAL transaction."""
        org = _make_org(db_session, balance=1000)

        ss = StripeService(db_session)
        ss._handle_charge_dispute_created(
            {
                "id": "dp_txn_check",
                "amount": 3000,  # 30 EUR = 300 credits
                "charge": "ch_txn_check",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        txn = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org.id,
                CreditTransaction.transaction_type == TransactionType.CHARGEBACK_REVERSAL.value,
            )
            .one()
        )
        assert txn.credits_amount == -300
        assert txn.reference_type == "stripe_dispute"
        assert txn.reference_id == "dp_txn_check"

    def test_chargeback_allows_negative_balance(self, db_session):
        """Chargeback can push balance below zero."""
        org = _make_org(db_session, balance=100)

        ss = StripeService(db_session)
        result = ss._handle_charge_dispute_created(
            {
                "id": "dp_neg_bal",
                "amount": 5000,  # 50 EUR = 500 credits
                "charge": "ch_neg_bal",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["credits_clawed"] == 500
        db_session.refresh(org)
        assert org.credits_balance == -400  # 100 - 500


class TestPartialRefund:
    """Partial refund should only claw back the refunded portion."""

    def test_partial_refund_deducts_proportional_credits(self, db_session):
        """Half-refund of a 50 EUR charge (500 credits) deducts only 250 credits."""
        org = _make_org(db_session, balance=500)

        ss = StripeService(db_session)
        result = ss._handle_charge_refunded(
            {
                "id": "ch_partial_001",
                "amount_refunded": 2500,  # 25 EUR = 250 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "refund_clawback"
        assert result["credits"] == 250
        db_session.refresh(org)
        assert org.credits_balance == 250  # 500 - 250

    def test_small_partial_refund(self, db_session):
        """Refund of 1 EUR (10 credits) on a large charge."""
        org = _make_org(db_session, balance=5000)

        ss = StripeService(db_session)
        result = ss._handle_charge_refunded(
            {
                "id": "ch_small_partial",
                "amount_refunded": 100,  # 1 EUR = 10 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["credits"] == 10
        db_session.refresh(org)
        assert org.credits_balance == 4990

    def test_partial_refund_then_another_partial(self, db_session):
        """Two partial refunds on different charges both apply."""
        org = _make_org(db_session, balance=1000)

        ss = StripeService(db_session)

        # First partial refund
        ss._handle_charge_refunded(
            {
                "id": "ch_multi_part_1",
                "amount_refunded": 2000,  # 20 EUR = 200 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        # Second partial refund (different charge)
        ss._handle_charge_refunded(
            {
                "id": "ch_multi_part_2",
                "amount_refunded": 1500,  # 15 EUR = 150 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        db_session.refresh(org)
        assert org.credits_balance == 650  # 1000 - 200 - 150

        # Two separate REFUND_CLAWBACK transactions
        count = _count_transactions(db_session, org.id, TransactionType.REFUND_CLAWBACK)
        assert count == 2

    def test_refund_amount_less_than_one_credit_is_zero(self, db_session):
        """Refund amount below 1 credit (< 10 cents) results in 0 credits clawed."""
        org = _make_org(db_session, balance=500)

        ss = StripeService(db_session)
        result = ss._handle_charge_refunded(
            {
                "id": "ch_tiny_refund",
                "amount_refunded": 5,  # 0.05 EUR = 0.5 credits -> int(0.5) = 0
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        # 0 credits to claw -> skipped
        assert result["action"] == "skipped"
        assert result["reason"] == "zero refund amount"
        db_session.refresh(org)
        assert org.credits_balance == 500  # unchanged


class TestRefundNegativeBalance:
    """Refund when user has spent the credits pushes balance negative."""

    def test_spent_all_credits_then_refund(self, db_session):
        """User bought 500 credits, spent all, then gets refunded -> balance -500."""
        org = _make_org(db_session, balance=0)

        cs = CreditsService(db_session)
        # Simulate purchase
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=500,
            description="Top-up",
            reference_type="stripe",
            reference_id="ch_spend_001",
        )
        db_session.flush()
        assert org.credits_balance == 500

        # Simulate spending all credits
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-500,
            description="Model execution",
            reference_type="execution",
            reference_id="exec_001",
        )
        db_session.flush()
        assert org.credits_balance == 0

        # Now refund happens
        ss = StripeService(db_session)
        result = ss._handle_charge_refunded(
            {
                "id": "ch_spend_001",
                "amount_refunded": 5000,  # 50 EUR = 500 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "refund_clawback"
        assert result["credits"] == 500
        db_session.refresh(org)
        assert org.credits_balance == -500  # 0 - 500

    def test_partially_spent_credits_then_refund(self, db_session):
        """User bought 500, spent 300, refund claws 500 -> balance -300."""
        org = _make_org(db_session, balance=0)

        cs = CreditsService(db_session)
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=500,
            description="Top-up",
            reference_type="stripe",
            reference_id="ch_partial_spend",
        )
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-300,
            description="Model execution",
            reference_type="execution",
            reference_id="exec_partial",
        )
        db_session.flush()
        assert org.credits_balance == 200  # 500 - 300

        ss = StripeService(db_session)
        ss._handle_charge_refunded(
            {
                "id": "ch_partial_spend",
                "amount_refunded": 5000,  # 50 EUR = 500 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        db_session.refresh(org)
        assert org.credits_balance == -300  # 200 - 500

    def test_negative_balance_recorded_in_transaction(self, db_session):
        """Negative balance_after is correctly recorded on the transaction."""
        org = _make_org(db_session, balance=50)

        ss = StripeService(db_session)
        ss._handle_charge_refunded(
            {
                "id": "ch_neg_txn",
                "amount_refunded": 2000,  # 20 EUR = 200 credits
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        txn = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org.id,
                CreditTransaction.transaction_type == TransactionType.REFUND_CLAWBACK.value,
            )
            .one()
        )
        assert txn.balance_after == -150  # 50 - 200


class TestRefundCustomerIdFallback:
    """When metadata has no org_id, find org via stripe_customer_id."""

    def test_refund_found_by_customer_id(self, db_session):
        """charge.refunded with no org_id in metadata finds org by customer ID."""
        org = _make_org(
            db_session,
            balance=500,
            stripe_customer_id="cus_fallback_001",
        )

        ss = StripeService(db_session)
        result = ss._handle_charge_refunded(
            {
                "id": "ch_cust_fallback",
                "customer": "cus_fallback_001",
                "amount_refunded": 1000,  # 10 EUR = 100 credits
                "metadata": {},  # no organization_id
            }
        )
        db_session.flush()

        assert result["action"] == "refund_clawback"
        assert result["credits"] == 100
        assert result["org_id"] == org.id
        db_session.refresh(org)
        assert org.credits_balance == 400  # 500 - 100

    def test_refund_no_customer_no_metadata_skipped(self, db_session):
        """Refund with neither metadata nor customer ID is skipped."""
        ss = StripeService(db_session)
        result = ss._handle_charge_refunded(
            {
                "id": "ch_no_org",
                "customer": None,
                "amount_refunded": 1000,
                "metadata": {},
            }
        )
        assert result["action"] == "skipped"
        assert result["reason"] == "org not found"


class TestChargebackEscalation:
    """Verify escalation from 0 -> 1 -> 2 -> 3 chargebacks and permanent ban."""

    def test_escalation_to_permanent_ban(self, db_session):
        """Three chargebacks escalate to permanent ban."""
        org = _make_org(db_session, balance=5000)
        ss = StripeService(db_session)

        for i in range(1, 4):
            result = ss._handle_charge_dispute_created(
                {
                    "id": f"dp_escalate_{i}",
                    "amount": 1000,  # 10 EUR = 100 credits each
                    "charge": f"ch_escalate_{i}",
                    "metadata": {"organization_id": org.id},
                }
            )
            db_session.flush()

            db_session.refresh(org)
            assert org.chargeback_count == i
            assert org.is_frozen is True

            if i < 3:
                assert result["permanent_ban"] is False
                # Manually unfreeze to allow next dispute
                # (in production, admin would do this)
                org.is_frozen = False
                db_session.flush()
            else:
                assert result["permanent_ban"] is True

        # Final state
        db_session.refresh(org)
        assert org.chargeback_count == 3
        assert org.is_frozen is True
        assert org.credits_balance == 4700  # 5000 - 3*100

    def test_dispute_won_does_not_unfreeze_after_three(self, db_session):
        """Even if dispute is won, permanent ban (3+ chargebacks) stays."""
        org = _make_org(
            db_session,
            balance=0,
            is_frozen=True,
            chargeback_count=3,
        )

        cs = CreditsService(db_session)
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.CHARGEBACK_REVERSAL,
            credits_amount=-500,
            description="Chargeback",
            reference_type="stripe_dispute",
            reference_id="dp_perm_won",
            allow_negative=True,
        )
        db_session.flush()

        ss = StripeService(db_session)
        result = ss._handle_charge_dispute_closed(
            {
                "id": "dp_perm_won",
                "status": "won",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "dispute_won_still_banned"
        db_session.refresh(org)
        assert org.is_frozen is True  # STILL frozen

    def test_dispute_won_unfreezes_below_three(self, db_session):
        """Dispute won with chargeback_count < 3 unfreezes org."""
        org = _make_org(
            db_session,
            balance=0,
            is_frozen=True,
            chargeback_count=2,
        )

        cs = CreditsService(db_session)
        cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.CHARGEBACK_REVERSAL,
            credits_amount=-300,
            description="Chargeback",
            reference_type="stripe_dispute",
            reference_id="dp_won_unfreeze",
            allow_negative=True,
        )
        db_session.flush()

        ss = StripeService(db_session)
        result = ss._handle_charge_dispute_closed(
            {
                "id": "dp_won_unfreeze",
                "status": "won",
                "metadata": {"organization_id": org.id},
            }
        )
        db_session.flush()

        assert result["action"] == "dispute_won_unfrozen"
        db_session.refresh(org)
        assert org.is_frozen is False


class TestChargebackSellerReversal:
    """Chargeback on marketplace purchase reverses seller's earning (D-08)."""

    def test_seller_earning_reversed_on_chargeback(self, db_session):
        """Seller loses earned credits when buyer's charge is disputed."""
        buyer = _make_org(db_session, balance=1000, name="Buyer")
        seller = _make_org(db_session, balance=0, name="Seller")

        cs = CreditsService(db_session)

        # Record the original marketplace purchase
        cs.record_transaction(
            organization_id=buyer.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-500,
            description="Model purchase",
            reference_type="stripe",
            reference_id="ch_market_chbk",
            buyer_organization_id=buyer.id,
        )
        # Record seller earning
        cs.record_transaction(
            organization_id=seller.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=450,
            description="Marketplace sale",
            reference_type="stripe",
            reference_id="ch_market_chbk",
            buyer_organization_id=buyer.id,
        )
        db_session.flush()

        db_session.refresh(seller)
        seller_balance_before = seller.credits_balance
        assert seller_balance_before == 450

        # Chargeback
        ss = StripeService(db_session)
        result = ss._handle_charge_dispute_created(
            {
                "id": "dp_seller_rev",
                "amount": 5000,  # 50 EUR = 500 credits
                "charge": "ch_market_chbk",
                "metadata": {"organization_id": buyer.id},
            }
        )
        db_session.flush()

        assert result["action"] == "chargeback_freeze"

        # Seller's balance should be reduced by the earning amount (450)
        db_session.refresh(seller)
        assert seller.credits_balance == 0  # 450 - 450

    def test_seller_reversal_can_go_negative(self, db_session):
        """If seller already withdrew some earnings, reversal goes negative."""
        buyer = _make_org(db_session, balance=2000, name="Buyer")
        seller = _make_org(db_session, balance=0, name="Seller")

        cs = CreditsService(db_session)

        # Marketplace purchase
        cs.record_transaction(
            organization_id=buyer.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-1000,
            description="Model purchase",
            reference_type="stripe",
            reference_id="ch_neg_seller",
            buyer_organization_id=buyer.id,
        )
        cs.record_transaction(
            organization_id=seller.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=900,
            description="Marketplace sale",
            reference_type="stripe",
            reference_id="ch_neg_seller",
            buyer_organization_id=buyer.id,
        )
        db_session.flush()

        # Seller spends most of the earnings
        cs.record_transaction(
            organization_id=seller.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-800,
            description="Seller model execution",
            reference_type="execution",
            reference_id="exec_seller_001",
        )
        db_session.flush()
        db_session.refresh(seller)
        assert seller.credits_balance == 100  # 900 - 800

        # Chargeback reverses the full 900
        ss = StripeService(db_session)
        ss._handle_charge_dispute_created(
            {
                "id": "dp_neg_seller_rev",
                "amount": 10000,
                "charge": "ch_neg_seller",
                "metadata": {"organization_id": buyer.id},
            }
        )
        db_session.flush()

        db_session.refresh(seller)
        assert seller.credits_balance == -800  # 100 - 900

    def test_chargeback_reverses_only_the_matching_sellers_earning(self, db_session):
        """Two parallel marketplace sales: a chargeback on ONE charge reverses
        only THAT sale's seller earning, never the other seller's.

        Pins the org_id + reference_id scoping of the dispute-reversal lookups in
        _handle_charge_dispute_created (original_txn + seller_earning). Both sales
        carry reference_type="stripe"; only the (buyer org, charge_id) pair
        disambiguates them, so dropping either filter would let the reversal hit
        the wrong seller. The order_by added to those lookups makes such a
        misselect deterministic rather than .first()-arbitrary (mutmut §16.3).
        """
        buyer_a = _make_org(db_session, balance=1000, name="Buyer A")
        seller_a = _make_org(db_session, balance=0, name="Seller A")
        buyer_b = _make_org(db_session, balance=1000, name="Buyer B")
        seller_b = _make_org(db_session, balance=0, name="Seller B")

        cs = CreditsService(db_session)
        # Sale A: buyer_a -> seller_a on charge ch_two_org_a.
        cs.record_transaction(
            organization_id=buyer_a.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-500,
            description="Purchase A",
            reference_type="stripe",
            reference_id="ch_two_org_a",
            buyer_organization_id=buyer_a.id,
        )
        cs.record_transaction(
            organization_id=seller_a.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=450,
            description="Sale A",
            reference_type="stripe",
            reference_id="ch_two_org_a",
            buyer_organization_id=buyer_a.id,
        )
        # Sale B: buyer_b -> seller_b on a DIFFERENT charge ch_two_org_b.
        cs.record_transaction(
            organization_id=buyer_b.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-500,
            description="Purchase B",
            reference_type="stripe",
            reference_id="ch_two_org_b",
            buyer_organization_id=buyer_b.id,
        )
        cs.record_transaction(
            organization_id=seller_b.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=450,
            description="Sale B",
            reference_type="stripe",
            reference_id="ch_two_org_b",
            buyer_organization_id=buyer_b.id,
        )
        db_session.flush()
        db_session.refresh(seller_a)
        db_session.refresh(seller_b)
        assert seller_a.credits_balance == 450
        assert seller_b.credits_balance == 450

        # Chargeback ONLY on sale A's charge.
        ss = StripeService(db_session)
        ss._handle_charge_dispute_created(
            {
                "id": "dp_two_org_a",
                "amount": 5000,  # 50 EUR clawed from buyer_a
                "charge": "ch_two_org_a",
                "metadata": {"organization_id": buyer_a.id},
            }
        )
        db_session.flush()

        # Seller A's earning reversed; Seller B's earning (other charge/org) untouched.
        db_session.refresh(seller_a)
        db_session.refresh(seller_b)
        assert seller_a.credits_balance == 0, (
            f"Seller A's 450-credit earning should be reversed by the chargeback, "
            f"got {seller_a.credits_balance}"
        )
        assert seller_b.credits_balance == 450, (
            f"Seller B's earning (different charge/org) must NOT be touched, "
            f"got {seller_b.credits_balance}"
        )


class TestRefundIdempotency:
    """Refund clawback should be idempotent (same charge refunded twice)."""

    def test_same_refund_event_processed_twice_is_idempotent(self, db_session):
        """Processing the same charge.refunded event twice does not double-deduct."""
        org = _make_org(db_session, balance=500)

        ss = StripeService(db_session)
        charge_data = {
            "id": "ch_idem_refund",
            "amount_refunded": 2000,  # 20 EUR = 200 credits
            "metadata": {"organization_id": org.id},
        }

        # First processing
        ss._handle_charge_refunded(charge_data)
        db_session.flush()
        db_session.commit()

        db_session.expire_all()
        balance_after_1 = db_session.get(Organization, org.id).credits_balance

        # Second processing (duplicate)
        ss._handle_charge_refunded(charge_data)
        db_session.flush()
        db_session.commit()

        db_session.expire_all()
        balance_after_2 = db_session.get(Organization, org.id).credits_balance

        # Balance should not change on second call
        assert balance_after_1 == balance_after_2
        assert balance_after_2 == 300  # 500 - 200

        # Only one clawback transaction
        count = _count_transactions(db_session, org.id, TransactionType.REFUND_CLAWBACK)
        assert count == 1


class TestDisputeLost:
    """Lost dispute keeps clawback in place and org frozen."""

    def test_dispute_lost_no_credit_restoration(self, db_session):
        """Losing a dispute does not restore credits."""
        org = _make_org(db_session, balance=500, is_frozen=True, chargeback_count=1)

        ss = StripeService(db_session)
        result = ss._handle_charge_dispute_closed(
            {
                "id": "dp_lost_final",
                "status": "lost",
                "metadata": {"organization_id": org.id},
            }
        )

        assert result["action"] == "dispute_closed_lost"
        db_session.refresh(org)
        assert org.is_frozen is True
        assert org.credits_balance == 500  # unchanged

    def test_dispute_other_status_handled(self, db_session):
        """Dispute with status other than 'won' or 'lost' (e.g. 'needs_response')."""
        org = _make_org(db_session, balance=500, is_frozen=True, chargeback_count=1)

        ss = StripeService(db_session)
        result = ss._handle_charge_dispute_closed(
            {
                "id": "dp_needs_resp",
                "status": "needs_response",
                "metadata": {"organization_id": org.id},
            }
        )

        assert result["action"] == "dispute_closed_needs_response"
        db_session.refresh(org)
        assert org.is_frozen is True  # unchanged
