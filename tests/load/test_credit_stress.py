"""Credit system stress tests.

Run separately: pytest tests/load/test_credit_stress.py -m load -v
Not included in default test runs (excluded by addopts).

Requires: docker-compose --profile test up -d
"""

import queue
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import CreditTransaction, Organization
from app.services.credits_service import CreditsService, InsufficientCreditsError


@pytest.mark.load
class TestCreditStress:
    @pytest.fixture
    def stress_org(self, db_session):
        org = Organization(
            id="org_stress_test",
            name="Stress Test Org",
            credits_balance=10000,
            credits_earned=0,
            monthly_quota=1000,
            currency="EUR",
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)
        return org

    def test_100_concurrent_deductions(self, db_engine, db_session, stress_org):
        """100 futures deducting 100 credits each from 10000 balance.
        All 100 should succeed, final balance = 0."""
        org_id = stress_org.id
        Session = sessionmaker(bind=db_engine)
        results = queue.Queue()

        def deduct_task(task_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=100,
                    description=f"Stress deduction {task_id}",
                    reference_type="execution",
                    reference_id=f"stress1_{task_id}",
                )
                session.commit()
                results.put(("success", task_id))
                return "success"
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", task_id))
                return "insufficient"
            except Exception as exc:
                session.rollback()
                results.put(("error", task_id, str(exc)))
                return f"error: {exc}"
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(deduct_task, i): i for i in range(100)}
            for future in as_completed(futures, timeout=60):
                future.result()  # Re-raise any unhandled exceptions

        successes = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1

        assert successes == 100, f"Expected 100 successes, got {successes}"

        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 0, f"Expected 0, got {org.credits_balance}"
        fresh.close()

    def test_mixed_operations_under_load(self, db_engine, db_session, stress_org):
        """50 deductions + 25 refunds + 25 deductions with same ref_id.
        Verify balance consistency and no deadlocks."""
        org_id = stress_org.id
        Session = sessionmaker(bind=db_engine)
        results = queue.Queue()

        def deduct_task(task_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=100,
                    description=f"Mixed deduction {task_id}",
                    reference_type="execution",
                    reference_id=f"stress2_deduct_{task_id}",
                )
                session.commit()
                results.put(("deduct_success", task_id))
                return "deduct_success"
            except InsufficientCreditsError:
                session.rollback()
                results.put(("deduct_insufficient", task_id))
                return "deduct_insufficient"
            except Exception as exc:
                session.rollback()
                results.put(("deduct_error", task_id, str(exc)))
                return f"error: {exc}"
            finally:
                session.close()

        def refund_task(task_id):
            session = Session()
            try:
                service = CreditsService(session)
                service.refund_credits(
                    organization_id=org_id,
                    credits=50,
                    description=f"Mixed refund {task_id}",
                    reference_type="refund",
                    reference_id=f"stress2_refund_{task_id}",
                )
                session.commit()
                results.put(("refund_success", task_id))
                return "refund_success"
            except Exception as exc:
                session.rollback()
                results.put(("refund_error", task_id, str(exc)))
                return f"error: {exc}"
            finally:
                session.close()

        def idempotent_deduct_task(task_id):
            """Deduction with shared reference_id (should be idempotent)."""
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=100,
                    description=f"Idempotent deduction {task_id}",
                    reference_type="execution",
                    reference_id="stress2_shared_ref",
                )
                session.commit()
                results.put(("idem_success", task_id))
                return "idem_success"
            except InsufficientCreditsError:
                session.rollback()
                results.put(("idem_insufficient", task_id))
                return "idem_insufficient"
            except Exception as exc:
                session.rollback()
                results.put(("idem_error", task_id, str(exc)))
                return f"error: {exc}"
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            # 50 unique deductions
            for i in range(50):
                futures.append(executor.submit(deduct_task, i))
            # 25 refunds
            for i in range(25):
                futures.append(executor.submit(refund_task, i))
            # 25 idempotent deductions (same ref_id)
            for i in range(25):
                futures.append(executor.submit(idempotent_deduct_task, i))

            for future in as_completed(futures, timeout=60):
                future.result()

        deduct_successes = 0
        refund_successes = 0
        idem_successes = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "deduct_success":
                deduct_successes += 1
            elif r[0] == "refund_success":
                refund_successes += 1
            elif r[0] == "idem_success":
                idem_successes += 1
            elif r[0].endswith("_error"):
                errors += 1

        assert errors == 0, f"Unexpected errors: {errors}"
        assert refund_successes == 25, f"All refunds should succeed: {refund_successes}"

        # Idempotent deductions: only 1 should actually deduct credits
        # The rest should return the existing transaction
        # (idem_success count may be 25 since all "succeed" from the caller's perspective)

        # Verify balance consistency
        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()

        # Idempotency invariant: the 25 tasks with shared reference_id
        # "stress2_shared_ref" must result in exactly ONE persisted transaction,
        # regardless of how many workers raced through. This is what lets us
        # bake the "- 100" into the expected balance below.
        shared_ref_tx_count = (
            fresh.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org_id,
                CreditTransaction.reference_type == "execution",
                CreditTransaction.reference_id == "stress2_shared_ref",
            )
            .count()
        )
        assert shared_ref_tx_count == 1, (
            f"Idempotency violation: expected exactly 1 transaction for "
            f"reference_id='stress2_shared_ref', got {shared_ref_tx_count}"
        )

        # Expected: 10000 - (deduct_successes * 100) + (25 * 50) - (1 * 100)
        # The 1 is for the single idempotent deduction that actually went through
        expected = 10000 - (deduct_successes * 100) + (25 * 50) - 100
        assert org.credits_balance == expected, (
            f"Expected {expected}, got {org.credits_balance} "
            f"(deducts={deduct_successes}, refunds={refund_successes}, "
            f"idem={idem_successes})"
        )
        fresh.close()

    def test_no_deadlock_under_sustained_load(self, db_engine, db_session, stress_org):
        """200 operations over sustained period. No deadlock, no timeout."""
        org_id = stress_org.id
        Session = sessionmaker(bind=db_engine)
        results = queue.Queue()

        def deduct_task(task_id):
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=50,
                    description=f"Sustained deduction {task_id}",
                    reference_type="execution",
                    reference_id=f"stress3_{task_id}",
                )
                session.commit()
                results.put(("success", task_id))
                return "success"
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", task_id))
                return "insufficient"
            except Exception as exc:
                session.rollback()
                results.put(("error", task_id, str(exc)))
                return f"error: {exc}"
            finally:
                session.close()

        # 200 small deductions: 200 * 50 = 10000 exactly
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(deduct_task, i): i for i in range(200)}
            # 60 second timeout for the entire batch
            for future in as_completed(futures, timeout=60):
                future.result()

        successes = 0
        insufficient = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            elif r[0] == "insufficient":
                insufficient += 1
            elif r[0] == "error":
                errors += 1

        assert errors == 0, f"Unexpected errors (deadlocks?): {errors}"
        assert successes == 200, f"Expected 200 successes, got {successes}"
        assert insufficient == 0, f"Unexpected insufficient: {insufficient}"

        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 0, f"Expected 0, got {org.credits_balance}"
        fresh.close()
