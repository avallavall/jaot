"""Comprehensive tests for consolidated CreditsService.

Covers: happy paths, error paths, edge cases, idempotency, concurrency,
balance tracking, notification logic, and transaction type correctness.
"""

import threading

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models import CreditTransaction, Organization, TransactionType
from app.services.credits_service import CreditsService, InsufficientCreditsError


@pytest.fixture
def test_org(db_session: Session) -> Organization:
    """Organization with 1000 credits, monthly_quota=100."""
    org = Organization(
        id="test-org-consolidated",
        name="Consolidated Test Org",
        credits_balance=1000,
        credits_earned=0,
        monthly_quota=100,
        currency="EUR",
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def buyer_org(db_session: Session) -> Organization:
    """Second organization to act as buyer in marketplace tests."""
    org = Organization(
        id="test-org-buyer",
        name="Buyer Org",
        credits_balance=500,
        credits_earned=0,
        monthly_quota=50,
        currency="EUR",
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def service(db_session: Session) -> CreditsService:
    return CreditsService(db_session)


class TestDeductCredits:
    def test_deduct_creates_transaction_and_updates_balance(
        self, db_session: Session, test_org: Organization
    ):
        initial = test_org.credits_balance
        CreditsService.deduct_credits(
            db=db_session,
            organization_id=test_org.id,
            credits=10,
            description="Test deduction",
            reference_type="execution",
            reference_id="exec_001",
        )
        db_session.commit()
        db_session.refresh(test_org)
        assert test_org.credits_balance == initial - 10

        txn = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.reference_id == "exec_001")
            .first()
        )
        assert txn is not None
        assert txn.credits_amount == -10
        assert txn.balance_after == initial - 10
        assert txn.transaction_type == TransactionType.EXECUTION.value

    def test_deduct_multiple_sequential(self, db_session: Session, test_org: Organization):
        """Multiple sequential deductions maintain correct running balance."""
        initial = test_org.credits_balance
        for i in range(5):
            CreditsService.deduct_credits(
                db=db_session,
                organization_id=test_org.id,
                credits=10,
                description=f"Deduction {i}",
                reference_type="execution",
                reference_id=f"seq_{i}",
            )
            db_session.commit()

        db_session.refresh(test_org)
        assert test_org.credits_balance == initial - 50

        # Verify last transaction's balance_after is correct
        txn = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.reference_id == "seq_4")
            .first()
        )
        assert txn.balance_after == initial - 50

    def test_deduct_exactly_all_credits(self, db_session: Session, test_org: Organization):
        """Deducting exactly the full balance should succeed."""
        balance = test_org.credits_balance
        CreditsService.deduct_credits(
            db=db_session,
            organization_id=test_org.id,
            credits=balance,
            description="All credits",
            reference_type="execution",
            reference_id="all_001",
        )
        db_session.commit()
        db_session.refresh(test_org)
        assert test_org.credits_balance == 0

    def test_deduct_zero_credits_still_records(self, db_session: Session, test_org: Organization):
        """Deducting 0 credits should not raise and MUST still write the transaction row."""
        initial = test_org.credits_balance
        CreditsService.deduct_credits(
            db=db_session,
            organization_id=test_org.id,
            credits=0,
            description="Zero deduction",
            reference_type="execution",
            reference_id="zero_001",
        )
        db_session.commit()
        db_session.refresh(test_org)
        assert test_org.credits_balance == initial

        # The test name says "still_records" — verify the row exists.
        tx = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == test_org.id,
                CreditTransaction.reference_type == "execution",
                CreditTransaction.reference_id == "zero_001",
            )
            .one()
        )
        assert tx.credits_amount == 0
        assert tx.balance_after == initial
        assert tx.transaction_type == TransactionType.EXECUTION.value


class TestDeductCreditsErrors:
    def test_insufficient_credits_raises_error(self, db_session: Session, test_org: Organization):
        test_org.credits_balance = 5
        db_session.commit()

        with pytest.raises(InsufficientCreditsError) as exc_info:
            CreditsService.deduct_credits(
                db=db_session,
                organization_id=test_org.id,
                credits=100,
                description="Too expensive",
                reference_type="execution",
                reference_id="fail_001",
            )

        assert exc_info.value.credits_needed == 100
        assert exc_info.value.credits_available == 5

    def test_insufficient_does_not_create_transaction(
        self, db_session: Session, test_org: Organization
    ):
        """Failed deduction must not leave a partial transaction."""
        test_org.credits_balance = 5
        db_session.commit()

        with pytest.raises(InsufficientCreditsError):
            CreditsService.deduct_credits(
                db=db_session,
                organization_id=test_org.id,
                credits=100,
                description="Should not persist",
                reference_type="execution",
                reference_id="no_txn_001",
            )

        db_session.rollback()
        txn = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.reference_id == "no_txn_001")
            .first()
        )
        assert txn is None

    def test_nonexistent_org_raises_value_error(self, db_session: Session):
        with pytest.raises(ValueError, match="not found"):
            CreditsService.deduct_credits(
                db=db_session,
                organization_id="nonexistent-org-xyz",
                credits=10,
                description="Should fail",
                reference_type="execution",
                reference_id="bad_org_001",
            )

    def test_record_transaction_nonexistent_org_raises(self, db_session: Session):
        service = CreditsService(db_session)
        with pytest.raises(ValueError, match="not found"):
            service.record_transaction(
                organization_id="ghost-org",
                transaction_type=TransactionType.ADJUSTMENT,
                credits_amount=50,
                description="Should fail",
            )


class TestIdempotency:
    def test_duplicate_deduct_credits_no_double_charge(
        self, db_session: Session, test_org: Organization
    ):
        """Calling deduct_credits twice with same ref should not double-charge."""
        initial = test_org.credits_balance

        CreditsService.deduct_credits(
            db=db_session,
            organization_id=test_org.id,
            credits=10,
            description="First call",
            reference_type="execution",
            reference_id="idem_001",
        )
        db_session.commit()
        db_session.refresh(test_org)
        after_first = test_org.credits_balance
        assert after_first == initial - 10

        # Second call — same reference
        service = CreditsService(db_session)
        result = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="Duplicate call",
            reference_type="execution",
            reference_id="idem_001",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_balance == after_first  # No second deduction
        assert result.reference_id == "idem_001"

    def test_same_ref_different_org_is_not_idempotent(
        self, db_session: Session, test_org: Organization, buyer_org: Organization
    ):
        """Same reference_id on different orgs should create separate transactions."""
        service = CreditsService(db_session)

        tx1 = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="Org A deduction",
            reference_type="execution",
            reference_id="shared_ref",
        )
        tx2 = service.record_transaction(
            organization_id=buyer_org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="Org B deduction",
            reference_type="execution",
            reference_id="shared_ref",
        )
        db_session.commit()

        assert tx1.id != tx2.id
        assert tx1.organization_id != tx2.organization_id

    def test_same_ref_different_txn_type_is_not_idempotent(
        self, db_session: Session, test_org: Organization
    ):
        """Same reference but different txn type should create both transactions."""
        service = CreditsService(db_session)

        tx1 = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-10,
            description="Deduction",
            reference_type="execution",
            reference_id="dual_type_ref",
        )
        tx2 = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.REFUND,
            credits_amount=10,
            description="Refund",
            reference_type="execution",
            reference_id="dual_type_ref",
        )
        db_session.commit()

        assert tx1.id != tx2.id

    def test_no_reference_skips_idempotency_check(
        self, db_session: Session, test_org: Organization
    ):
        """Transactions without reference should always create new records."""
        service = CreditsService(db_session)
        initial = test_org.credits_balance

        tx1 = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.ADJUSTMENT,
            credits_amount=10,
            description="Adjustment 1",
        )
        tx2 = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.ADJUSTMENT,
            credits_amount=10,
            description="Adjustment 2",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert tx1.id != tx2.id
        assert test_org.credits_balance == initial + 20


class TestRefundCredits:
    def test_refund_creates_positive_transaction(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        initial = test_org.credits_balance
        txn = service.refund_credits(
            organization_id=test_org.id,
            credits=15,
            description="Solve failed, refunding",
            reference_type="execution_refund",
            reference_id="refund_001",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_balance == initial + 15
        assert txn.transaction_type == TransactionType.REFUND.value
        assert txn.credits_amount == 15
        assert txn.balance_after == initial + 15

    def test_refund_is_idempotent(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        """Duplicate refund with same ref should not double-credit."""
        initial = test_org.credits_balance

        service.refund_credits(
            organization_id=test_org.id,
            credits=20,
            description="First refund",
            reference_type="execution_refund",
            reference_id="refund_idem",
        )
        db_session.commit()
        db_session.refresh(test_org)
        after_first = test_org.credits_balance
        assert after_first == initial + 20

        # Duplicate
        service.refund_credits(
            organization_id=test_org.id,
            credits=20,
            description="Duplicate refund",
            reference_type="execution_refund",
            reference_id="refund_idem",
        )
        db_session.commit()
        db_session.refresh(test_org)
        assert test_org.credits_balance == after_first  # No double credit


class TestLowCreditsNotification:
    def test_fires_when_crossing_threshold(self, db_session: Session, test_org: Organization):
        """Notification fires when balance drops below 10% of monthly_quota."""
        test_org.credits_balance = 15
        test_org.monthly_quota = 100
        test_org.low_credits_notified = False
        db_session.commit()

        # Deduct to 9 credits (below threshold of 10)
        CreditsService.deduct_credits(
            db=db_session,
            organization_id=test_org.id,
            credits=6,
            description="Cross threshold",
            reference_type="execution",
            reference_id="low_001",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_balance == 9
        assert test_org.low_credits_notified is True

    def test_does_not_fire_above_threshold(self, db_session: Session, test_org: Organization):
        """Notification should not fire when balance stays above threshold."""
        test_org.credits_balance = 50
        test_org.monthly_quota = 100
        test_org.low_credits_notified = False
        db_session.commit()

        CreditsService.deduct_credits(
            db=db_session,
            organization_id=test_org.id,
            credits=10,
            description="Still above threshold",
            reference_type="execution",
            reference_id="above_001",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_balance == 40
        assert test_org.low_credits_notified is False

    def test_does_not_fire_twice(self, db_session: Session, test_org: Organization):
        """Once notified, subsequent deductions should not re-trigger."""
        test_org.credits_balance = 8
        test_org.monthly_quota = 100
        test_org.low_credits_notified = True  # already notified
        db_session.commit()

        CreditsService.deduct_credits(
            db=db_session,
            organization_id=test_org.id,
            credits=2,
            description="Further deduction",
            reference_type="execution",
            reference_id="double_001",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_balance == 6
        assert test_org.low_credits_notified is True  # Still True, not re-triggered

    def test_grant_resets_notification_flag(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        """Positive credit transaction resets the low_credits_notified flag."""
        test_org.low_credits_notified = True
        db_session.commit()

        service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=100,
            description="Top-up purchase",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.low_credits_notified is False

    def test_refund_resets_notification_flag(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        """Refund (positive amount) should also reset the notification flag."""
        test_org.low_credits_notified = True
        db_session.commit()

        service.refund_credits(
            organization_id=test_org.id,
            credits=10,
            description="Refund resets flag",
            reference_type="execution_refund",
            reference_id="reset_refund",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.low_credits_notified is False


class TestTransactionTypes:
    def test_sale_earning_increases_earned_credits(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        initial_earned = test_org.credits_earned
        service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=50,
            description="Marketplace sale",
            reference_type="model",
            reference_id="model_001",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_earned == initial_earned + 50

    def test_withdrawal_decreases_earned_credits(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        test_org.credits_earned = 100
        db_session.commit()

        service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.WITHDRAWAL,
            credits_amount=-30,
            description="Withdrawal",
            reference_type="withdrawal",
            reference_id="wd_001",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_earned == 70

    def test_adjustment_records_correctly(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        initial = test_org.credits_balance
        service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.ADJUSTMENT,
            credits_amount=-25,
            description="Admin correction",
            created_by="admin_user_001",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_balance == initial - 25

    def test_purchase_increases_balance(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        initial = test_org.credits_balance
        service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=200,
            description="Stripe purchase",
            amount_eur=20.0,
            payment_method="stripe",
        )
        db_session.commit()
        db_session.refresh(test_org)

        assert test_org.credits_balance == initial + 200


class TestMarketplaceSale:
    def test_marketplace_sale_creates_three_transactions(
        self,
        service: CreditsService,
        db_session: Session,
        test_org: Organization,
        buyer_org: Organization,
    ):
        buyer_initial = buyer_org.credits_balance
        seller_initial = test_org.credits_balance
        seller_earned = test_org.credits_earned

        buyer_tx, commission_tx, seller_tx = service.record_marketplace_sale(
            seller_organization_id=test_org.id,
            buyer_organization_id=buyer_org.id,
            model_id="model_sale_001",
            credits_price=100,
            commission_rate=0.10,
        )
        db_session.commit()
        db_session.refresh(test_org)
        db_session.refresh(buyer_org)

        # Buyer charged full price
        assert buyer_org.credits_balance == buyer_initial - 100
        assert buyer_tx.credits_amount == -100

        # Commission is audit record (0 credits)
        assert commission_tx.credits_amount == 0
        assert commission_tx.transaction_type == TransactionType.COMMISSION.value

        # Seller gets price minus commission
        assert seller_tx.credits_amount == 90
        assert test_org.credits_balance == seller_initial + 90
        assert test_org.credits_earned == seller_earned + 90

    def test_marketplace_sale_zero_commission(
        self,
        service: CreditsService,
        db_session: Session,
        test_org: Organization,
        buyer_org: Organization,
    ):
        """Zero commission — seller gets full price."""
        buyer_tx, commission_tx, seller_tx = service.record_marketplace_sale(
            seller_organization_id=test_org.id,
            buyer_organization_id=buyer_org.id,
            model_id="model_free_commission",
            credits_price=50,
            commission_rate=0.0,
        )
        db_session.commit()

        assert seller_tx.credits_amount == 50
        assert commission_tx.credits_amount == 0


class TestTransactionHistory:
    def test_history_returns_transactions_in_desc_order(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        for i in range(3):
            service.record_transaction(
                organization_id=test_org.id,
                transaction_type=TransactionType.ADJUSTMENT,
                credits_amount=10,
                description=f"Adjustment {i}",
            )
        db_session.commit()

        history = service.get_transaction_history(test_org.id)
        assert len(history) == 3
        # Most recent first
        assert history[0].description == "Adjustment 2"

    def test_history_filter_by_type(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=100,
            description="Purchase",
        )
        service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.ADJUSTMENT,
            credits_amount=-10,
            description="Adjustment",
        )
        db_session.commit()

        purchases = service.get_transaction_history(
            test_org.id, transaction_type=TransactionType.PURCHASE.value
        )
        assert len(purchases) == 1
        assert purchases[0].transaction_type == TransactionType.PURCHASE.value

    def test_history_pagination(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        for i in range(10):
            service.record_transaction(
                organization_id=test_org.id,
                transaction_type=TransactionType.ADJUSTMENT,
                credits_amount=1,
                description=f"Txn {i}",
            )
        db_session.commit()

        page1 = service.get_transaction_history(test_org.id, limit=3, offset=0)
        page2 = service.get_transaction_history(test_org.id, limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].id != page2[0].id


class TestConcurrency:
    def test_concurrent_deductions_maintain_correct_balance(self, db_engine, db_session, test_org):
        """Two concurrent deductions via separate sessions must not corrupt balance.

        This verifies that the SELECT FOR UPDATE row lock serializes concurrent
        access properly. Both threads try to deduct 10 credits simultaneously.
        The final balance should be initial - 20 (not initial - 10).
        """
        org_id = test_org.id
        initial_balance = test_org.credits_balance

        errors = []
        Session = sessionmaker(bind=db_engine)

        def deduct_in_thread(ref_id: str):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=10,
                    description=f"Concurrent deduction {ref_id}",
                    reference_type="execution",
                    reference_id=ref_id,
                )
                session.commit()
            except Exception as e:
                session.rollback()
                errors.append(e)
            finally:
                session.close()

        t1 = threading.Thread(target=deduct_in_thread, args=("concurrent_a",))
        t2 = threading.Thread(target=deduct_in_thread, args=("concurrent_b",))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert not errors, f"Concurrent deductions raised errors: {errors}"

        # Verify in fresh session
        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == initial_balance - 20
        fresh.close()

    def test_concurrent_deduction_one_insufficient(self, db_engine, db_session, test_org):
        """When two threads race to deduct and only one can win, the loser gets InsufficientCreditsError."""
        test_org.credits_balance = 15
        db_session.commit()
        org_id = test_org.id

        results = {"a": None, "b": None}
        Session = sessionmaker(bind=db_engine)

        def deduct_in_thread(ref_id: str, key: str):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=10,
                    description=f"Race deduction {ref_id}",
                    reference_type="execution",
                    reference_id=ref_id,
                )
                session.commit()
                results[key] = "success"
            except InsufficientCreditsError:
                session.rollback()
                results[key] = "insufficient"
            except Exception as e:
                session.rollback()
                results[key] = f"error: {e}"
            finally:
                session.close()

        t1 = threading.Thread(target=deduct_in_thread, args=("race_a", "a"))
        t2 = threading.Thread(target=deduct_in_thread, args=("race_b", "b"))

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # One should succeed, one should fail (or both succeed if 15 >= 20 is false)
        outcomes = [results["a"], results["b"]]
        assert "success" in outcomes, f"At least one should succeed: {outcomes}"
        # With 15 credits and 2x10 deductions, exactly one succeeds
        success_count = outcomes.count("success")
        assert success_count == 1, f"Exactly one should succeed with 15 credits: {outcomes}"


class TestBalanceTracking:
    def test_balance_after_is_always_correct(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        """Every transaction's balance_after should match the org's current balance at that point."""
        initial = test_org.credits_balance

        tx1 = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=100,
            description="Purchase",
        )
        assert tx1.balance_after == initial + 100

        tx2 = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.EXECUTION,
            credits_amount=-30,
            description="Execute",
            reference_type="execution",
            reference_id="track_001",
        )
        assert tx2.balance_after == initial + 100 - 30

        db_session.commit()
        db_session.refresh(test_org)
        assert test_org.credits_balance == tx2.balance_after

    def test_earned_balance_after_tracks_correctly(
        self, service: CreditsService, db_session: Session, test_org: Organization
    ):
        test_org.credits_earned = 0
        db_session.commit()

        tx = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=50,
            description="Sale",
            reference_type="model",
            reference_id="earned_track_001",
        )
        assert tx.earned_balance_after == 50

        tx2 = service.record_transaction(
            organization_id=test_org.id,
            transaction_type=TransactionType.WITHDRAWAL,
            credits_amount=-20,
            description="Withdraw",
            reference_type="withdrawal",
            reference_id="earned_track_002",
        )
        assert tx2.earned_balance_after == 30

        db_session.commit()
        db_session.refresh(test_org)
        assert test_org.credits_earned == 30
