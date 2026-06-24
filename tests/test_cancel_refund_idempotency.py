"""Cancel/refund idempotency regression tests (CR-01).

Proves the "exactly one refund per solve_task" invariant under concurrent
access — the classic double-refund race between:

  * ``app/api/v2/solve.py::cancel_async_task`` — user-triggered cancel that
    would historically call ``refund_credits`` directly.
  * ``app/domains/solver/tasks/solve_tasks.py::solve_async`` except-handler
    — worker-side refund when the SIGTERM'd task lands in the outer
    ``except Exception`` block.

Both paths can reach ``CreditsService.refund_credits`` with the same
``(organization_id, reference_type='solve_task', reference_id=task_id)``
tuple. Without DB-level idempotency, concurrent timing produces two refund
rows and doubles the refunded credits.

This test file locks in the invariant end-to-end using real Postgres +
real threading + per-thread sessions (pattern mirrors
``tests/test_credit_race_conditions.py``). The tests currently pass against
HEAD because the existing ``uq_credit_txn_reference`` partial unique index
(migration ``20260317_add_credit_idempotency_constraint.py``) already covers
the race via ``record_transaction``'s try/except IntegrityError path.
Phase 6.1 Plan 02 adds a narrower explicit index
(``ux_credit_txn_refund_solve_task``, migration 20260418) as a
belt-and-suspenders audit-friendly constraint — behavior is unchanged.

Requires real Postgres: ``docker-compose up -d postgres`` (jaot_test DB
is auto-created on the same instance).
"""

import queue
import threading

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import CreditTransaction, Organization, TransactionType
from app.services.credits_service import CreditsService


# CONTRACT-TEST: refund-idempotency (CR-01)
#   Exactly one refund row per (organization_id, reference_type='solve_task',
#   reference_id=task_id) under concurrent cancel + worker-except race.
#   Removing this test removes the only guard against double-refund regressions.
@pytest.mark.integration
class TestCancelRefundIdempotency:
    """CR-01 regression: concurrent cancel + worker-except produces exactly one refund."""

    # --- Local fixtures ---
    @pytest.fixture
    def race_org(self, db_session):
        """Organization with credits_balance=0 so refunds are observable as net positive."""
        org = Organization(
            id="org_cr01_race",
            name="CR-01 Race Org",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)
        return org

    # --- Helper: join with liveness check (mirrors test_credit_race_conditions) ---
    def _join_threads(self, threads, timeout=30):
        """Join all threads, fail if any is still alive after timeout."""
        for t in threads:
            t.join(timeout=timeout)
        abandoned = [t.name for t in threads if t.is_alive()]
        if abandoned:
            pytest.fail(f"Threads still alive after {timeout}s: {abandoned}")

    # Test A: concurrent cancel + worker-except yields exactly one refund row
    def test_concurrent_cancel_and_worker_refund_yields_exactly_one_row(
        self, db_engine, db_session, race_org
    ):
        """Two threads race to refund the same task_id. Exactly one row wins."""
        org_id = race_org.id
        task_id = "celery_task_cr01_race_01"
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def refund_worker(thread_id):
            session = Session()
            try:
                CreditsService(session).refund_credits(
                    organization_id=org_id,
                    credits=10,
                    description=f"Race refund from thread {thread_id}",
                    reference_type="solve_task",
                    reference_id=task_id,
                )
                session.commit()
                results.put(("success", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=refund_worker, args=(i,), name=f"refund-{i}") for i in range(2)
        ]
        for t in threads:
            t.start()
        self._join_threads(threads)

        # Drain and assert both threads ran without raising
        outcomes = []
        while not results.empty():
            outcomes.append(results.get())
        assert all(o[0] == "success" for o in outcomes), f"outcomes: {outcomes}"
        assert len(outcomes) == 2, f"Expected 2 thread outcomes, got {len(outcomes)}"

        # Assert exactly one refund row for this task_id
        verify = Session()
        try:
            refund_rows = (
                verify.query(CreditTransaction)
                .filter(
                    CreditTransaction.organization_id == org_id,
                    CreditTransaction.transaction_type == TransactionType.REFUND.value,
                    CreditTransaction.reference_type == "solve_task",
                    CreditTransaction.reference_id == task_id,
                )
                .all()
            )
            assert len(refund_rows) == 1, (
                f"Expected 1 refund row, got {len(refund_rows)}. "
                f"Double-refund race is NOT prevented."
            )

            # Assert balance increased by exactly 10, not 20
            org = verify.query(Organization).filter(Organization.id == org_id).first()
            assert org.credits_balance == 10, (
                f"Expected +10 (single refund), got {org.credits_balance}. "
                f"Double-refund race inflated balance."
            )
        finally:
            verify.close()

    # Test B: direct refund called twice (same session) returns existing row
    def test_direct_refund_called_twice_is_noop(self, db_session, race_org):
        """Second call with same reference_id returns the existing transaction."""
        org_id = race_org.id
        service = CreditsService(db_session)

        first = service.refund_credits(
            organization_id=org_id,
            credits=5,
            description="First refund call",
            reference_type="solve_task",
            reference_id="task_B_dup",
        )
        db_session.commit()

        second = service.refund_credits(
            organization_id=org_id,
            credits=5,
            description="Second refund call (should be no-op)",
            reference_type="solve_task",
            reference_id="task_B_dup",
        )
        db_session.commit()

        # Both calls return the SAME transaction row (idempotent)
        assert first.id == second.id, (
            f"Expected same transaction id, got first={first.id} second={second.id}. "
            f"Second refund created a duplicate row."
        )

        # Balance increased by exactly 5, not 10
        db_session.refresh(race_org)
        assert race_org.credits_balance == 5, (
            f"Expected +5 (single refund), got {race_org.credits_balance}. "
            f"Second refund double-credited."
        )

        # Exactly one refund row in the database for this reference_id
        refund_count = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org_id,
                CreditTransaction.transaction_type == TransactionType.REFUND.value,
                CreditTransaction.reference_type == "solve_task",
                CreditTransaction.reference_id == "task_B_dup",
            )
            .count()
        )
        assert refund_count == 1, f"Expected 1 refund row, got {refund_count}"

    # Test C: different reference_ids produce distinct rows (scoping proof)
    def test_refund_idempotency_scoped_by_reference_id(self, db_session, race_org):
        """Different task_ids produce distinct refund rows; scoping is correct."""
        org_id = race_org.id
        service = CreditsService(db_session)

        tx_a = service.refund_credits(
            organization_id=org_id,
            credits=3,
            description="Refund for task_A",
            reference_type="solve_task",
            reference_id="task_A",
        )
        db_session.commit()

        tx_b = service.refund_credits(
            organization_id=org_id,
            credits=7,
            description="Refund for task_B",
            reference_type="solve_task",
            reference_id="task_B",
        )
        db_session.commit()

        # Two distinct transactions
        assert tx_a.id != tx_b.id, "Different reference_ids must produce distinct rows"

        # Total balance increased by sum of both refunds
        db_session.refresh(race_org)
        assert race_org.credits_balance == 10, f"Expected +10 (3+7), got {race_org.credits_balance}"

        # Both refund rows exist
        refund_count = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org_id,
                CreditTransaction.transaction_type == TransactionType.REFUND.value,
                CreditTransaction.reference_type == "solve_task",
            )
            .count()
        )
        assert refund_count == 2, f"Expected 2 refund rows, got {refund_count}"
