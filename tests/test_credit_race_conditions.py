"""Credit race condition tests.

Proves SELECT FOR UPDATE correctness under real multi-thread concurrency.
Each test spawns N threads, each with its own SQLAlchemy session,
all racing to modify the same organization's credit balance.

Two tests verify previously documented production bugs are now FIXED:
- test_record_transaction_direct_allows_negative_balance
- test_async_solve_no_refund_on_failure

Two lock-ordering siblings of the create_withdrawal deadlock fix (W3, W6):
- TestWithdrawalLockOrdering — scheduled + manual withdrawal cannot overdraw
- TestMarketplaceSaleLockOrdering — opposite-direction sales don't ABBA-deadlock

Requires: docker-compose --profile test up -d
"""

import queue
import threading
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models import (
    CreditTransaction,
    Organization,
    ScheduleAmountType,
    ScheduleFrequency,
    TransactionType,
    Withdrawal,
    WithdrawalSchedule,
)
from app.services.credits_service import CreditsService, InsufficientCreditsError
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


# CONTRACT-TEST: credit-concurrency-invariants
#   SELECT FOR UPDATE correctness under multi-thread concurrency:
#   balance never goes negative; concurrent solves do not double-debit;
#   async refunds settle exactly once.
class TestCreditRaceConditions:
    """Real concurrency tests proving credit system integrity."""

    # --- Local fixtures ---
    @pytest.fixture
    def race_org(self, db_session):
        """Organization with known balance for race tests."""
        org = Organization(
            id="org_race_test",
            name="Race Test Org",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)
        return org

    # --- Helper: join with liveness check ---
    def _join_threads(self, threads, timeout=30):
        """Join all threads, fail if any is still alive after timeout."""
        for t in threads:
            t.join(timeout=timeout)
        abandoned = [t.name for t in threads if t.is_alive()]
        if abandoned:
            pytest.fail(f"Threads still alive after {timeout}s: {abandoned}")

    # Test 1: 20 concurrent deductions, all should succeed
    def test_20_concurrent_deductions_exact_balance(self, db_engine, db_session, race_org):
        """20 threads each deduct 50 from 1000. All 20 succeed, balance=0."""
        org_id = race_org.id
        results = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def deduct_worker(thread_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=50,
                    description=f"Race deduction {thread_id}",
                    reference_type="execution",
                    reference_id=f"race1_{thread_id}",
                )
                session.commit()
                results.put(("success", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=deduct_worker, args=(i,), name=f"deduct-{i}") for i in range(20)
        ]
        for t in threads:
            t.start()
        self._join_threads(threads)

        # Drain results
        successes = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            else:
                errors += 1

        assert successes == 20, f"Expected 20 successes, got {successes} (errors: {errors})"
        assert errors == 0

        # Verify final balance
        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 0, f"Expected 0, got {org.credits_balance}"
        fresh.close()

    # Test 2: 20 threads, only 10 should succeed
    def test_20_concurrent_deductions_half_fail(self, db_engine, db_session, race_org):
        """20 threads each deduct 100 from 1000. Exactly 10 succeed."""
        org_id = race_org.id
        results = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def deduct_worker(thread_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=100,
                    description=f"Half-fail deduction {thread_id}",
                    reference_type="execution",
                    reference_id=f"race2_{thread_id}",
                )
                session.commit()
                results.put(("success", thread_id))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=deduct_worker, args=(i,), name=f"half-fail-{i}")
            for i in range(20)
        ]
        for t in threads:
            t.start()
        self._join_threads(threads)

        successes = 0
        insufficient = 0
        unexpected_errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            elif r[0] == "insufficient":
                insufficient += 1
            else:
                unexpected_errors += 1

        assert successes == 10, f"Expected 10 successes, got {successes}"
        assert insufficient == 10, f"Expected 10 insufficient, got {insufficient}"
        assert unexpected_errors == 0

        # Verify final balance
        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 0, f"Expected 0, got {org.credits_balance}"
        fresh.close()

    # Test 3: Negative balance prevention via deduct_credits
    def test_negative_balance_impossible_via_deduct(self, db_engine, db_session, race_org):
        """Balance must never go below 0 even under heavy concurrency."""
        org_id = race_org.id
        results = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def deduct_worker(thread_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=100,
                    description=f"Negative check {thread_id}",
                    reference_type="execution",
                    reference_id=f"race3_{thread_id}",
                )
                session.commit()
                results.put(("success", thread_id))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=deduct_worker, args=(i,), name=f"neg-check-{i}")
            for i in range(20)
        ]
        for t in threads:
            t.start()
        self._join_threads(threads)

        successes = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1

        # Verify balance is exactly 0, never negative
        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance >= 0, (
            f"CRITICAL: Negative balance detected: {org.credits_balance}"
        )
        assert org.credits_balance == 0, f"Expected 0, got {org.credits_balance}"
        assert successes == 10, f"Expected exactly 10 successes, got {successes}"
        fresh.close()

    # Test 4: Concurrent deduct + refund
    def test_concurrent_deduct_and_refund(self, db_engine, db_session, race_org):
        """Interleaved deductions and refunds maintain correct balance."""
        org_id = race_org.id
        results = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def deduct_worker(thread_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=50,
                    description=f"Deduct {thread_id}",
                    reference_type="execution",
                    reference_id=f"race4_deduct_{thread_id}",
                )
                session.commit()
                results.put(("deduct_success", thread_id))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("deduct_insufficient", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("deduct_error", thread_id, str(exc)))
            finally:
                session.close()

        def refund_worker(thread_id):
            session = Session()
            try:
                service = CreditsService(session)
                service.refund_credits(
                    organization_id=org_id,
                    credits=100,
                    description=f"Refund {thread_id}",
                    reference_type="refund",
                    reference_id=f"race4_refund_{thread_id}",
                )
                session.commit()
                results.put(("refund_success", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("refund_error", thread_id, str(exc)))
            finally:
                session.close()

        # 20 deduct threads (50 each) + 5 refund threads (100 each)
        threads = []
        for i in range(20):
            threads.append(threading.Thread(target=deduct_worker, args=(i,), name=f"deduct-{i}"))
        for i in range(5):
            threads.append(threading.Thread(target=refund_worker, args=(i,), name=f"refund-{i}"))

        for t in threads:
            t.start()
        self._join_threads(threads)

        # Count results
        deduct_successes = 0
        deduct_insufficient = 0
        refund_successes = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "deduct_success":
                deduct_successes += 1
            elif r[0] == "deduct_insufficient":
                deduct_insufficient += 1
            elif r[0] == "refund_success":
                refund_successes += 1
            else:
                errors += 1

        assert errors == 0, f"Unexpected errors: {errors}"
        assert refund_successes == 5, f"All refunds should succeed, got {refund_successes}"

        # Verify: final balance = 1000 - (successful_deductions * 50) + (5 * 100)
        expected_balance = 1000 - (deduct_successes * 50) + (5 * 100)
        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == expected_balance, (
            f"Expected {expected_balance}, got {org.credits_balance} "
            f"(deducts={deduct_successes}, refunds={refund_successes})"
        )
        fresh.close()

    # Test 5: Idempotency under concurrent retry (low contention)
    def test_idempotent_deduction_retry(self, db_engine, db_session, race_org):
        """Same reference_id submitted by 3 threads: only 1 deduction happens.

        NOTE: This works at low thread counts because SELECT serializes
        behind FOR UPDATE. See test_idempotency_toctou_race for the
        high-contention bug.
        """
        org_id = race_org.id
        results = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def deduct_worker(thread_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=100,
                    description=f"Idempotent deduction {thread_id}",
                    reference_type="execution",
                    reference_id="exec_same_001",
                )
                session.commit()
                results.put(("success", thread_id))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=deduct_worker, args=(i,), name=f"idem-{i}") for i in range(3)
        ]
        for t in threads:
            t.start()
        self._join_threads(threads)

        successes = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1

        # Only 1 transaction should exist with this reference
        fresh = Session()
        tx_count = (
            fresh.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org_id,
                CreditTransaction.reference_id == "exec_same_001",
            )
            .count()
        )
        org = fresh.query(Organization).filter(Organization.id == org_id).first()

        assert tx_count == 1, f"Expected 1 transaction, got {tx_count}"
        assert org.credits_balance == 900, f"Expected 900 (1000 - 100), got {org.credits_balance}"
        fresh.close()

    # Test 6: Double-spend prevention
    def test_double_spend_prevention(self, db_engine, db_session, race_org):
        """20 threads try to spend the entire balance simultaneously."""
        org_id = race_org.id
        results = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def deduct_worker(thread_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=1000,
                    description=f"Double-spend {thread_id}",
                    reference_type="execution",
                    reference_id=f"race6_{thread_id}",
                )
                session.commit()
                results.put(("success", thread_id))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=deduct_worker, args=(i,), name=f"dbl-spend-{i}")
            for i in range(20)
        ]
        for t in threads:
            t.start()
        self._join_threads(threads)

        successes = 0
        insufficient = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            elif r[0] == "insufficient":
                insufficient += 1
            else:
                errors += 1

        assert successes == 1, f"Expected exactly 1 success, got {successes}"
        assert insufficient == 19, f"Expected 19 insufficient, got {insufficient}"
        assert errors == 0

        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 0
        fresh.close()

    # Test 7: DB timeout mid-transaction recovery
    def test_db_timeout_mid_transaction(self, db_engine, db_session, race_org):
        """If a session times out mid-transaction, other threads proceed."""
        org_id = race_org.id
        results = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def slow_worker():
            """Acquire lock then sleep until statement_timeout kills us."""
            session = Session()
            try:
                session.execute(text("SET statement_timeout = '1s'"))
                # Lock the org row
                session.execute(
                    text("SELECT id FROM organizations WHERE id = :org_id FOR UPDATE"),
                    {"org_id": org_id},
                )
                # Sleep longer than timeout -- will raise OperationalError
                session.execute(text("SELECT pg_sleep(5)"))
                session.commit()
                results.put(("slow_success",))
            except Exception as exc:
                session.rollback()
                results.put(("slow_error", str(type(exc).__name__)))
            finally:
                session.close()

        def normal_worker():
            """Normal deduction that waits for the lock."""
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=100,
                    description="Normal deduction after timeout",
                    reference_type="execution",
                    reference_id="race7_normal",
                )
                session.commit()
                results.put(("normal_success",))
            except Exception as exc:
                session.rollback()
                results.put(("normal_error", str(exc)))
            finally:
                session.close()

        t_slow = threading.Thread(target=slow_worker, name="slow-worker")
        t_normal = threading.Thread(target=normal_worker, name="normal-worker")

        t_slow.start()
        # Small delay to ensure slow thread acquires lock first
        import time

        time.sleep(0.1)
        t_normal.start()

        self._join_threads([t_slow, t_normal], timeout=30)

        slow_result = None
        normal_result = None
        while not results.empty():
            r = results.get()
            if r[0].startswith("slow"):
                slow_result = r
            else:
                normal_result = r

        # Slow thread should have errored (statement_timeout)
        assert slow_result is not None
        assert slow_result[0] == "slow_error", f"Slow thread should error: {slow_result}"

        # Normal thread should succeed
        assert normal_result is not None
        assert normal_result[0] == "normal_success", (
            f"Normal thread should succeed: {normal_result}"
        )

        # Only normal deduction applied
        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 900, f"Expected 900, got {org.credits_balance}"
        fresh.close()

    # Test 8: Deadlock recovery
    def test_deadlock_recovery(self, db_engine, db_session, race_org):
        """Concurrent operations on the same row eventually succeed."""
        org_id = race_org.id
        results = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def deduct_worker(thread_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=10,
                    description=f"Deadlock test {thread_id}",
                    reference_type="execution",
                    reference_id=f"race8_{thread_id}",
                )
                session.commit()
                results.put(("success", thread_id))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        # 20 rapid-fire threads, each deducts 10 from 1000
        threads = [
            threading.Thread(target=deduct_worker, args=(i,), name=f"deadlock-{i}")
            for i in range(20)
        ]
        for t in threads:
            t.start()
        self._join_threads(threads)

        successes = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            elif r[0] == "error":
                errors += 1

        # All 20 should succeed (200 total from 1000)
        assert successes == 20, f"Expected 20 successes, got {successes}"
        assert errors == 0, f"Unexpected errors: {errors}"

        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 800, f"Expected 800, got {org.credits_balance}"
        fresh.close()

    # Test 9 (BUG FIX VERIFIED): record_transaction guards negative balance
    def test_record_transaction_direct_allows_negative_balance(
        self, db_engine, db_session, race_org
    ):
        """FIXED (Phase 10): record_transaction() now guards against negative balance.

        Previously this was a known bug: record_transaction() did not check
        credits_balance >= 0, so direct calls with a negative credits_amount
        exceeding the balance would produce a negative balance.

        Phase 10 (plan 02) added a balance guard to record_transaction with
        allow_negative=False default. Now InsufficientCreditsError is raised.
        """
        org_id = race_org.id

        # Call record_transaction directly (NOT deduct_credits)
        # with credits_amount=-2000 on an org with balance=1000
        service = CreditsService(db_session)
        with pytest.raises(InsufficientCreditsError) as exc_info:
            service.record_transaction(
                organization_id=org_id,
                transaction_type=TransactionType.EXECUTION,
                credits_amount=-2000,
                description="Direct call should now raise error",
                reference_type="execution",
                reference_id="bug_test_negative",
            )

        # Bug is FIXED: InsufficientCreditsError raised, balance unchanged
        assert exc_info.value.credits_needed == 2000
        assert exc_info.value.credits_available == 1000
        db_session.refresh(race_org)
        assert race_org.credits_balance == 1000, (
            f"Expected 1000 (unchanged), got {race_org.credits_balance}. "
            "Balance should not change after InsufficientCreditsError."
        )

    # Test 10 (BUG FIX VERIFIED): solve_async refunds on failure
    def test_async_solve_no_refund_on_failure(self, db_engine, db_session, race_org):
        """FIXED (Phase 10): solve_async now refunds credits on exception.

        Invokes the Celery task synchronously (via .apply()) with malformed
        problem_data that fails `OptimizationProblem(**problem_data)` parsing
        inside the task. The exception is caught by the task's outer `except
        Exception`, which must trigger the refund path.

        Asserts:
          - task result status == "error"
          - a refund CreditTransaction was written with matching credits
          - the org balance is unchanged end-to-end (deduct + refund cancel)
        """
        from app.domains.solver.tasks.solve_tasks import solve_async as solve_async_task

        org_id = race_org.id
        prepaid_credits = 7

        # Pre-pay credits the same way the endpoint does (so we can verify refund).
        CreditsService.deduct_credits(
            db=db_session,
            organization_id=org_id,
            credits=prepaid_credits,
            description="Pre-pay for async solve test",
            reference_type="solve",
            reference_id="race_async_prepay",
        )
        db_session.commit()
        db_session.refresh(race_org)
        balance_after_deduct = race_org.credits_balance
        assert balance_after_deduct == 1000 - prepaid_credits

        # Malformed problem_data: missing the required `variables` and
        # `objective` fields. OptimizationProblem(**problem_data) will raise
        # a Pydantic ValidationError inside the task, which the outer
        # `except Exception` catches and triggers the refund path.
        bad_problem = {
            "name": "race_async_bad",
            "description": "Will fail during parsing",
            # Intentionally missing 'objective' and 'variables'.
            "_prepaid_credits": prepaid_credits,
        }

        # Invoke task synchronously via .apply() — runs in-process, no broker.
        result = solve_async_task.apply(
            args=[bad_problem, org_id, None, None, None],
        )
        task_result = result.get(disable_sync_subtasks=False)
        assert task_result["status"] == "error", (
            f"Task should have failed; got status={task_result.get('status')!r}"
        )
        task_id = task_result["task_id"]

        # Verify a refund transaction was written in the refund DB session.
        fresh = sessionmaker(bind=db_engine)()
        try:
            refund_tx = (
                fresh.query(CreditTransaction)
                .filter(
                    CreditTransaction.organization_id == org_id,
                    CreditTransaction.reference_type == "solve_task",
                    CreditTransaction.reference_id == task_id,
                )
                .one_or_none()
            )
            assert refund_tx is not None, (
                f"No refund transaction found for failed async task {task_id}"
            )
            assert refund_tx.credits_amount == prepaid_credits, (
                f"Refund amount mismatch: expected +{prepaid_credits}, "
                f"got {refund_tx.credits_amount}"
            )
            assert refund_tx.transaction_type == TransactionType.REFUND.value

            # End-to-end: deduct + refund cancel, so the balance is back to 1000.
            refund_org = fresh.query(Organization).filter(Organization.id == org_id).first()
            assert refund_org.credits_balance == 1000, (
                f"Expected balance to be restored to 1000 after refund, "
                f"got {refund_org.credits_balance}"
            )
        finally:
            fresh.close()


# CONTRACT-TEST: withdrawal-lock-ordering
#   Scheduled and manual withdrawals on the same org serialize on the org row
#   lock (W3 — sibling of the create_withdrawal share→exclusive fix): the
#   withdrawable balance can never be double-spent and the race never
#   deadlocks. "Locking: concurrent access tests mandatory" (project policy).
class TestWithdrawalLockOrdering:
    """W3: _execute_scheduled_withdrawal must serialize with create_withdrawal."""

    @pytest.fixture
    def seller_org(self, db_session):
        """Org with exactly 1000 withdrawable credits (matured earnings)."""
        org = Organization(
            id=generate_id("org_"),
            name="Withdrawal Race Org",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_active=True,
            stripe_connect_onboarding_complete=True,
        )
        db_session.add(org)
        db_session.commit()

        cs = CreditsService(db_session)
        txn = cs.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=1000,
            description="Matured marketplace earnings",
            reference_type="model",
            reference_id=generate_id("cat_"),
        )
        # Mature the holding period so the full 1000 is withdrawable.
        txn.available_at = (utcnow() - timedelta(days=1)).replace(tzinfo=None)
        db_session.commit()
        db_session.refresh(org)
        assert cs.get_withdrawable_balance(org.id) == 1000
        return org

    def _join_threads(self, threads, timeout=30):
        for t in threads:
            t.join(timeout=timeout)
        abandoned = [t.name for t in threads if t.is_alive()]
        if abandoned:
            pytest.fail(f"Threads still alive after {timeout}s (deadlock?): {abandoned}")

    def test_concurrent_scheduled_and_manual_withdrawal_cannot_overdraw(
        self, db_engine, db_session, seller_org
    ):
        """A scheduled and a manual withdrawal racing for the same 1000
        withdrawable credits must produce EXACTLY ONE 600-credit withdrawal.

        Pre-fix, _execute_scheduled_withdrawal read the org without a lock and
        computed `withdrawable` outside any serialization, so both paths could
        observe 1000 and withdraw 600 each (1200 > 1000) — or deadlock on the
        share→exclusive upgrade. Post-fix both serialize on the org row lock:
        whichever runs second sees withdrawable=400, which is below the
        500-credit minimum (scheduled path skips; manual path raises).
        """
        org_id = seller_org.id

        # Due scheduled withdrawal: FIXED 600 credits.
        schedule = WithdrawalSchedule(
            id=generate_id("wds_"),
            organization_id=org_id,
            frequency=ScheduleFrequency.WEEKLY.value,
            amount_type=ScheduleAmountType.FIXED.value,
            amount_value=600,
            min_threshold=100,
            next_execution=(utcnow() - timedelta(hours=1)).replace(tzinfo=None),
            is_active=True,
        )
        db_session.add(schedule)
        db_session.commit()

        Session = sessionmaker(bind=db_engine)
        barrier = threading.Barrier(2)
        results = queue.Queue()

        def manual_worker():
            session = Session()
            try:
                barrier.wait(timeout=10)
                CreditsService(session).create_withdrawal(
                    organization_id=org_id,
                    credits_amount=600,
                    created_by="race-test",
                )
                session.commit()
                results.put(("manual_success",))
            except ValueError as exc:
                session.rollback()
                # Losing the race legitimately surfaces as insufficient funds.
                results.put(("manual_insufficient", str(exc)))
            except Exception as exc:
                session.rollback()
                results.put(("manual_error", repr(exc)))
            finally:
                session.close()

        def scheduled_worker():
            session = Session()
            try:
                barrier.wait(timeout=10)
                withdrawals = CreditsService(session).process_scheduled_withdrawals()
                session.commit()
                results.put(("scheduled_done", len(withdrawals)))
            except Exception as exc:
                session.rollback()
                results.put(("scheduled_error", repr(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=manual_worker, name="manual-withdrawal"),
            threading.Thread(target=scheduled_worker, name="scheduled-withdrawal"),
        ]
        for t in threads:
            t.start()
        self._join_threads(threads)

        outcomes = {}
        while not results.empty():
            r = results.get()
            outcomes[r[0]] = r

        # No deadlocks / unexpected errors on either path.
        assert "manual_error" not in outcomes, f"Manual path crashed: {outcomes}"
        assert "scheduled_error" not in outcomes, f"Scheduled path crashed: {outcomes}"

        fresh = Session()
        try:
            withdrawals = fresh.query(Withdrawal).filter(Withdrawal.organization_id == org_id).all()
            total_withdrawn = sum(w.credits_amount for w in withdrawals)

            # The core invariant: never more than the withdrawable balance.
            assert total_withdrawn <= 1000, (
                f"OVERDRAW: {total_withdrawn} credits withdrawn from a 1000-credit "
                f"withdrawable balance ({[w.credits_amount for w in withdrawals]})"
            )
            # And with 600+600 racing for 1000, exactly one can win.
            assert len(withdrawals) == 1, (
                f"Expected exactly 1 winning withdrawal, got "
                f"{[(w.withdrawal_type, w.credits_amount) for w in withdrawals]}"
            )
            assert total_withdrawn == 600

            org = fresh.query(Organization).filter(Organization.id == org_id).first()
            assert org.credits_balance == 1000 - 600
            assert org.credits_earned == 1000 - 600
            assert CreditsService(fresh).get_withdrawable_balance(org_id) == 400
        finally:
            fresh.close()


# CONTRACT-TEST: marketplace-sale-lock-ordering
#   record_marketplace_sale acquires both org locks in sorted-ID order (W6),
#   so opposite-direction concurrent sales (A↔B) cannot ABBA-deadlock and all
#   three transactions per sale settle exactly once.
class TestMarketplaceSaleLockOrdering:
    """W6: opposite-direction concurrent marketplace sales must not deadlock."""

    ROUNDS = 5
    PRICE = 100  # commission 10 (10%), seller nets 90

    def _join_threads(self, threads, timeout=30):
        for t in threads:
            t.join(timeout=timeout)
        abandoned = [t.name for t in threads if t.is_alive()]
        if abandoned:
            pytest.fail(f"Threads still alive after {timeout}s (deadlock?): {abandoned}")

    def test_opposite_direction_sales_do_not_deadlock(self, db_engine, db_session):
        """N rounds of simultaneous A→B and B→A sales all succeed.

        Pre-fix, record_transaction locked buyer first then seller, so the
        two directions acquired (X, Y) and (Y, X) — Postgres aborts one
        transaction per collision with a deadlock error. Post-fix both
        directions pre-lock in sorted-ID order and serialize cleanly.
        """
        org_x = Organization(
            id=generate_id("org_"),
            name="Marketplace Org X",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_active=True,
        )
        org_y = Organization(
            id=generate_id("org_"),
            name="Marketplace Org Y",
            credits_balance=1000,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_active=True,
        )
        db_session.add_all([org_x, org_y])
        db_session.commit()

        Session = sessionmaker(bind=db_engine)
        results = queue.Queue()

        def sale_worker(name, seller_id, buyer_id, model_id, barrier):
            session = Session()
            try:
                barrier.wait(timeout=10)
                CreditsService(session).record_marketplace_sale(
                    seller_organization_id=seller_id,
                    buyer_organization_id=buyer_id,
                    model_id=model_id,
                    credits_price=self.PRICE,
                )
                session.commit()
                results.put(("success", name))
            except Exception as exc:
                session.rollback()
                results.put(("error", name, repr(exc)))
            finally:
                session.close()

        for round_i in range(self.ROUNDS):
            barrier = threading.Barrier(2)
            threads = [
                threading.Thread(
                    target=sale_worker,
                    args=(f"x-sells-{round_i}", org_x.id, org_y.id, f"mdl_x_{round_i}", barrier),
                    name=f"x-sells-{round_i}",
                ),
                threading.Thread(
                    target=sale_worker,
                    args=(f"y-sells-{round_i}", org_y.id, org_x.id, f"mdl_y_{round_i}", barrier),
                    name=f"y-sells-{round_i}",
                ),
            ]
            for t in threads:
                t.start()
            self._join_threads(threads)

        successes = 0
        errors = []
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            else:
                errors.append(r)

        assert not errors, f"Deadlock or failure in concurrent sales: {errors}"
        assert successes == self.ROUNDS * 2

        # Balance integrity: each org bought 5 times (-100 each) and sold 5
        # times (+90 each after 10% commission) → net -10 per round.
        fresh = Session()
        try:
            for org_id in (org_x.id, org_y.id):
                org = fresh.query(Organization).filter(Organization.id == org_id).first()
                expected = 1000 + self.ROUNDS * (90 - self.PRICE)
                assert org.credits_balance == expected, (
                    f"{org_id}: expected {expected}, got {org.credits_balance}"
                )
                sale_earnings = (
                    fresh.query(CreditTransaction)
                    .filter(
                        CreditTransaction.organization_id == org_id,
                        CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
                    )
                    .count()
                )
                assert sale_earnings == self.ROUNDS
        finally:
            fresh.close()
