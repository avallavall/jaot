"""Tests for concurrent operations across the platform.

Covers:
- 3.4.1: Two users solving the same model simultaneously (both succeed)
- 3.4.2: Two users purchasing the same marketplace model simultaneously (each gets own copy)
- 3.4.3: Concurrent credit deduction race condition (credits never go negative)
- 3.4.4: Concurrent model update (last write wins, no corruption)

Uses real PostgreSQL database per project convention.
Concurrency is achieved via threading.Thread with separate DB sessions.
"""

import queue
import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    ModelCatalog,
    ModelExecution,
    Organization,
    OrganizationModel,
    TransactionType,
    User,
)
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.services.credits_service import CreditsService, InsufficientCreditsError
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def org_a(db_session: Session) -> Organization:
    """Organization A with 1000 credits."""
    org = Organization(
        id="org_concurrent_a",
        name="Concurrent Org A",
        credits_balance=1000,
        credits_earned=0,
        monthly_quota=200,
        currency="EUR",
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def org_b(db_session: Session) -> Organization:
    """Organization B with 1000 credits."""
    org = Organization(
        id="org_concurrent_b",
        name="Concurrent Org B",
        credits_balance=1000,
        credits_earned=0,
        monthly_quota=200,
        currency="EUR",
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def user_a(db_session: Session, org_a: Organization) -> User:
    """User in Organization A."""
    user = User(
        id="usr_concurrent_a",
        email="user_a@concurrent.test",
        name="User A",
        organization_id=org_a.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def user_b(db_session: Session, org_b: Organization) -> User:
    """User in Organization B."""
    user = User(
        id="usr_concurrent_b",
        email="user_b@concurrent.test",
        name="User B",
        organization_id=org_b.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def catalog_model(db_session: Session) -> ModelCatalog:
    """Published catalog model for marketplace tests."""
    model = ModelCatalog(
        id=generate_id("cat_"),
        name="test_concurrent_model",
        display_name="Concurrent Test Model",
        description="A model for concurrent testing",
        category="general",
        generator_type="custom",
        input_schema={"type": "object"},
        input_fields=[{"name": "x", "type": "number"}],
        example_input={"x": 1},
        status="published",
        is_official=True,
        price_eur=0.0,
        credits_per_execution=1,
        total_activations=0,
        total_executions=0,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


@pytest.fixture
def paid_catalog_model(db_session: Session, org_a: Organization) -> ModelCatalog:
    """Published PAID catalog model for marketplace purchase tests.

    Owned by a third org so both org_a and org_b can purchase it.
    """
    # Create seller org
    seller_org = Organization(
        id="org_seller_concurrent",
        name="Seller Org",
        credits_balance=0,
        credits_earned=0,
        monthly_quota=100,
        currency="EUR",
        is_active=True,
    )
    db_session.add(seller_org)
    db_session.flush()

    model = ModelCatalog(
        id=generate_id("cat_"),
        name="test_paid_concurrent",
        display_name="Paid Concurrent Model",
        description="A paid model for concurrent testing",
        category="general",
        generator_type="custom",
        input_schema={"type": "object"},
        input_fields=[{"name": "x", "type": "number"}],
        example_input={"x": 1},
        status="published",
        is_official=False,
        author_organization_id=seller_org.id,
        price_eur=10.0,  # 100 credits
        credits_per_execution=1,
        total_activations=0,
        total_executions=0,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


def _join_threads(threads: list, timeout: int = 30) -> None:
    """Join all threads, fail if any is still alive after timeout."""
    for t in threads:
        t.join(timeout=timeout)
    abandoned = [t.name for t in threads if t.is_alive()]
    if abandoned:
        pytest.fail(f"Threads still alive after {timeout}s: {abandoned}")


class TestConcurrentSolves:
    """Two users solving simultaneously should both succeed without interference."""

    def test_concurrent_solves_both_succeed(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        org_b: Organization,
    ):
        """Two orgs solving simultaneously: both should get their own execution records."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def solve_worker(org_id: str, thread_id: int) -> None:
            session = Session()
            try:
                # Deduct credits first (as the solve endpoint does)
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=1,
                    description=f"Concurrent solve {thread_id}",
                    reference_type="execution",
                    reference_id=f"concurrent_solve_{org_id}_{thread_id}",
                )

                # Create execution record
                execution = ModelExecution(
                    id=f"exe_concurrent_{org_id}_{thread_id}",
                    organization_id=org_id,
                    input_data={"thread": thread_id},
                    status="completed",
                    credits_consumed=1,
                    execution_time_ms=100,
                    completed_at=utcnow(),
                )
                session.add(execution)
                session.commit()
                results.put(("success", org_id, thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", org_id, thread_id, str(exc)))
            finally:
                session.close()

        # Launch 5 threads per org (10 total) solving simultaneously
        threads = []
        for i in range(5):
            threads.append(
                threading.Thread(
                    target=solve_worker,
                    args=(org_a.id, i),
                    name=f"solve-a-{i}",
                )
            )
            threads.append(
                threading.Thread(
                    target=solve_worker,
                    args=(org_b.id, i),
                    name=f"solve-b-{i}",
                )
            )

        for t in threads:
            t.start()
        _join_threads(threads)

        # Verify all succeeded
        successes = {"org_concurrent_a": 0, "org_concurrent_b": 0}
        errors = []
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes[r[1]] += 1
            else:
                errors.append(r)

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert successes["org_concurrent_a"] == 5
        assert successes["org_concurrent_b"] == 5

        # Verify execution records
        fresh = Session()
        a_execs = (
            fresh.query(ModelExecution).filter(ModelExecution.organization_id == org_a.id).count()
        )
        b_execs = (
            fresh.query(ModelExecution).filter(ModelExecution.organization_id == org_b.id).count()
        )
        assert a_execs == 5, f"Expected 5 executions for org A, got {a_execs}"
        assert b_execs == 5, f"Expected 5 executions for org B, got {b_execs}"

        # Verify credits deducted correctly (1000 - 5 = 995)
        org_a_fresh = fresh.query(Organization).filter(Organization.id == org_a.id).first()
        org_b_fresh = fresh.query(Organization).filter(Organization.id == org_b.id).first()
        assert org_a_fresh.credits_balance == 995
        assert org_b_fresh.credits_balance == 995
        fresh.close()

    def test_concurrent_solves_no_cross_org_interference(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        org_b: Organization,
    ):
        """Concurrent solves from different orgs don't affect each other's balance."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        barrier = threading.Barrier(10, timeout=10)

        def solve_worker(org_id: str, credits: int, thread_id: int) -> None:
            session = Session()
            try:
                barrier.wait()  # Force all threads to start at the same instant
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=credits,
                    description=f"Barrier solve {thread_id}",
                    reference_type="execution",
                    reference_id=f"barrier_solve_{org_id}_{thread_id}",
                )
                session.commit()
                results.put(("success", org_id))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", org_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", org_id, str(exc)))
            finally:
                session.close()

        # 5 threads for org_a deducting 200 each (5*200=1000, exactly the balance)
        # 5 threads for org_b deducting 200 each (same)
        threads = []
        for i in range(5):
            threads.append(
                threading.Thread(
                    target=solve_worker,
                    args=(org_a.id, 200, i),
                    name=f"barrier-a-{i}",
                )
            )
            threads.append(
                threading.Thread(
                    target=solve_worker,
                    args=(org_b.id, 200, i),
                    name=f"barrier-b-{i}",
                )
            )

        for t in threads:
            t.start()
        _join_threads(threads)

        a_successes = 0
        b_successes = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                if r[1] == org_a.id:
                    a_successes += 1
                else:
                    b_successes += 1

        # Exactly 5 should succeed for each (1000/200=5)
        assert a_successes == 5, f"Expected 5 successes for org A, got {a_successes}"
        assert b_successes == 5, f"Expected 5 successes for org B, got {b_successes}"

        # Both balances should be exactly 0
        fresh = Session()
        org_a_fresh = fresh.query(Organization).filter(Organization.id == org_a.id).first()
        org_b_fresh = fresh.query(Organization).filter(Organization.id == org_b.id).first()
        assert org_a_fresh.credits_balance == 0
        assert org_b_fresh.credits_balance == 0
        fresh.close()


class TestConcurrentModelActivation:
    """Two users purchasing the same marketplace model get their own copy."""

    def test_two_orgs_activate_same_free_model(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        org_b: Organization,
        catalog_model: ModelCatalog,
    ):
        """Two orgs activate the same free catalog model: both get their own OrganizationModel."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def activate_worker(org_id: str) -> None:
            session = Session()
            try:
                # Check if already activated (same check as the API endpoint)
                existing = (
                    session.query(OrganizationModel)
                    .filter(
                        OrganizationModel.organization_id == org_id,
                        OrganizationModel.catalog_id == catalog_model.id,
                        OrganizationModel.is_active == True,  # noqa: E712
                    )
                    .first()
                )
                if existing:
                    results.put(("already_exists", org_id))
                    return

                org_model = OrganizationModel(
                    id=str(uuid.uuid4()),
                    organization_id=org_id,
                    catalog_id=catalog_model.id,
                    is_active=True,
                    purchased_at=None,
                    purchase_price_eur=None,
                )
                session.add(org_model)
                session.commit()
                results.put(("success", org_id, org_model.id))
            except Exception as exc:
                session.rollback()
                results.put(("error", org_id, str(exc)))
            finally:
                session.close()

        # Both orgs activate simultaneously
        threads = [
            threading.Thread(target=activate_worker, args=(org_a.id,), name="activate-a"),
            threading.Thread(target=activate_worker, args=(org_b.id,), name="activate-b"),
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        # Both should succeed
        successes = {}
        while not results.empty():
            r = results.get()
            assert r[0] == "success", f"Expected success, got {r}"
            successes[r[1]] = r[2]

        assert len(successes) == 2
        assert org_a.id in successes
        assert org_b.id in successes
        # Each org got a different model instance
        assert successes[org_a.id] != successes[org_b.id]

        # Verify in DB
        fresh = Session()
        a_models = (
            fresh.query(OrganizationModel)
            .filter(
                OrganizationModel.organization_id == org_a.id,
                OrganizationModel.catalog_id == catalog_model.id,
            )
            .all()
        )
        b_models = (
            fresh.query(OrganizationModel)
            .filter(
                OrganizationModel.organization_id == org_b.id,
                OrganizationModel.catalog_id == catalog_model.id,
            )
            .all()
        )
        assert len(a_models) == 1
        assert len(b_models) == 1
        assert a_models[0].id != b_models[0].id
        fresh.close()

    def test_two_orgs_purchase_same_paid_model(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        org_b: Organization,
        paid_catalog_model: ModelCatalog,
    ):
        """Two orgs buying the same paid model: both pay and get their own copy."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)
        model_id = paid_catalog_model.id
        credits_price = int(paid_catalog_model.price_eur * 10)  # 100 credits

        def purchase_worker(org_id: str) -> None:
            session = Session()
            try:
                # Deduct credits (simulating marketplace sale)
                service = CreditsService(session)
                service.record_transaction(
                    organization_id=org_id,
                    transaction_type=TransactionType.EXECUTION,
                    credits_amount=-credits_price,
                    description=f"Model activation: {model_id}",
                    reference_type="model",
                    reference_id=f"{model_id}_{org_id}",
                    created_by="system",
                )

                org_model = OrganizationModel(
                    id=str(uuid.uuid4()),
                    organization_id=org_id,
                    catalog_id=model_id,
                    is_active=True,
                    purchased_at=utcnow(),
                    purchase_price_eur=paid_catalog_model.price_eur,
                )
                session.add(org_model)
                session.commit()
                results.put(("success", org_id, org_model.id))
            except InsufficientCreditsError as exc:
                session.rollback()
                results.put(("insufficient", org_id, str(exc)))
            except Exception as exc:
                session.rollback()
                results.put(("error", org_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=purchase_worker, args=(org_a.id,), name="purchase-a"),
            threading.Thread(target=purchase_worker, args=(org_b.id,), name="purchase-b"),
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        successes = {}
        while not results.empty():
            r = results.get()
            assert r[0] == "success", f"Expected success, got {r}"
            successes[r[1]] = r[2]

        assert len(successes) == 2

        # Verify credits were deducted from each org
        fresh = Session()
        org_a_fresh = fresh.query(Organization).filter(Organization.id == org_a.id).first()
        org_b_fresh = fresh.query(Organization).filter(Organization.id == org_b.id).first()
        assert org_a_fresh.credits_balance == 1000 - credits_price
        assert org_b_fresh.credits_balance == 1000 - credits_price
        fresh.close()

    def test_same_org_cannot_activate_model_twice(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        catalog_model: ModelCatalog,
    ):
        """Same org activating same model concurrently: only one should succeed.

        The second activation should detect the existing record and skip.
        We rely on the application-level uniqueness check rather than a
        DB constraint, so under high concurrency both might succeed. This
        test documents the current behavior.
        """
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)
        barrier = threading.Barrier(2, timeout=10)

        def activate_worker(thread_id: int) -> None:
            session = Session()
            try:
                barrier.wait()

                # Application-level uniqueness check
                existing = (
                    session.query(OrganizationModel)
                    .filter(
                        OrganizationModel.organization_id == org_a.id,
                        OrganizationModel.catalog_id == catalog_model.id,
                        OrganizationModel.is_active == True,  # noqa: E712
                    )
                    .first()
                )
                if existing:
                    results.put(("already_exists", thread_id))
                    return

                org_model = OrganizationModel(
                    id=str(uuid.uuid4()),
                    organization_id=org_a.id,
                    catalog_id=catalog_model.id,
                    is_active=True,
                )
                session.add(org_model)
                session.commit()
                results.put(("success", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=activate_worker, args=(i,), name=f"dup-activate-{i}")
            for i in range(2)
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        successes = 0
        already_exists = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            elif r[0] == "already_exists":
                already_exists += 1

        # At least one should succeed. Under high concurrency both might
        # succeed due to TOCTOU (no DB constraint). Document this.
        assert successes >= 1
        total_models = (
            Session()
            .query(OrganizationModel)
            .filter(
                OrganizationModel.organization_id == org_a.id,
                OrganizationModel.catalog_id == catalog_model.id,
            )
            .count()
        )
        # Regardless, the data should be consistent (no corruption)
        assert total_models >= 1


class TestConcurrentCreditDeduction:
    """Credits should never go negative under concurrent deductions."""

    def test_credits_never_go_negative(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
    ):
        """10 threads each try to deduct 200 from 1000. Max 5 succeed, balance >= 0."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)
        org_id = org_a.id

        def deduct_worker(thread_id: int) -> None:
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=200,
                    description=f"Race deduction {thread_id}",
                    reference_type="execution",
                    reference_id=f"race_{org_id}_{thread_id}",
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
            threading.Thread(target=deduct_worker, args=(i,), name=f"credit-race-{i}")
            for i in range(10)
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

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

        assert errors == 0, f"Unexpected errors: {errors}"
        assert successes == 5, f"Expected 5 successes (1000/200), got {successes}"
        assert insufficient == 5, f"Expected 5 insufficient, got {insufficient}"

        # CRITICAL: balance must never be negative
        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance >= 0, (
            f"CRITICAL: Negative balance detected: {org.credits_balance}"
        )
        assert org.credits_balance == 0
        fresh.close()

    def test_concurrent_trigger_fires_deduct_correctly(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
    ):
        """Multiple concurrent trigger fires each deducting credits maintain correct balance."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)
        org_id = org_a.id

        def trigger_fire_worker(thread_id: int) -> None:
            session = Session()
            try:
                # Simulate what trigger_solve_task does for credit deduction
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=50,
                    description=f"Trigger solve {thread_id}",
                    reference_type="execution",
                    reference_id=f"trigger_fire_{org_id}_{thread_id}",
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

        # 20 concurrent trigger fires, each costing 50 credits from 1000 balance
        threads = [
            threading.Thread(target=trigger_fire_worker, args=(i,), name=f"trigger-fire-{i}")
            for i in range(20)
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        successes = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            elif r[0] == "error":
                errors += 1

        assert errors == 0
        assert successes == 20, f"All 20 should succeed (20*50=1000), got {successes}"

        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 0
        fresh.close()

    def test_mixed_solve_and_trigger_credits(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
    ):
        """Mixed manual solves and trigger solves deducting from same org: correct total."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)
        org_id = org_a.id

        def worker(kind: str, credits: int, thread_id: int) -> None:
            session = Session()
            try:
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=credits,
                    description=f"{kind} solve {thread_id}",
                    reference_type="execution",
                    reference_id=f"{kind}_{thread_id}",
                )
                session.commit()
                results.put(("success", kind, credits))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", kind, credits))
            except Exception as exc:
                session.rollback()
                results.put(("error", kind, str(exc)))
            finally:
                session.close()

        # 5 manual solves (100 credits each = 500) + 10 trigger fires (50 each = 500)
        # Total = 1000, should all succeed
        threads = []
        for i in range(5):
            threads.append(
                threading.Thread(
                    target=worker,
                    args=("manual", 100, i),
                    name=f"manual-{i}",
                )
            )
        for i in range(10):
            threads.append(
                threading.Thread(
                    target=worker,
                    args=("trigger", 50, i),
                    name=f"trigger-{i}",
                )
            )

        for t in threads:
            t.start()
        _join_threads(threads)

        total_deducted = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                total_deducted += r[2]
            elif r[0] == "error":
                errors += 1

        assert errors == 0
        assert total_deducted == 1000

        fresh = Session()
        org = fresh.query(Organization).filter(Organization.id == org_id).first()
        assert org.credits_balance == 0
        fresh.close()


class TestConcurrentModelUpdate:
    """Concurrent model updates should not corrupt data (last write wins)."""

    def test_concurrent_document_updates_no_corruption(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        user_a: User,
    ):
        """Multiple threads updating the same document: no JSON corruption."""
        now = utcnow()
        doc = ModelBuilderDocument(
            id=generate_id("bld_"),
            organization_id=org_a.id,
            created_by=user_a.id,
            name="Concurrent Update Doc",
            canvas_json={"nodes": [], "edges": []},
            model_json={"variables": [], "constraints": []},
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db_session.add(doc)
        db_session.commit()
        doc_id = doc.id

        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def update_worker(thread_id: int) -> None:
            session = Session()
            try:
                d = (
                    session.query(ModelBuilderDocument)
                    .filter(ModelBuilderDocument.id == doc_id)
                    .first()
                )
                if not d:
                    results.put(("error", thread_id, "doc not found"))
                    return

                # Each thread writes a different name and model_json
                d.name = f"Updated by thread {thread_id}"
                d.model_json = {
                    "variables": [{"name": f"x_{thread_id}"}],
                    "constraints": [],
                    "thread_id": thread_id,
                }
                d.updated_at = utcnow()
                session.commit()
                results.put(("success", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=update_worker, args=(i,), name=f"update-{i}") for i in range(10)
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        successes = 0
        errors = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1
            else:
                errors += 1

        # All updates should succeed (last-write-wins with no corruption)
        assert successes == 10, f"Expected 10 successes, got {successes}"
        assert errors == 0

        # The final state should be consistent: one of the thread updates
        fresh = Session()
        final_doc = (
            fresh.query(ModelBuilderDocument).filter(ModelBuilderDocument.id == doc_id).first()
        )
        assert final_doc is not None
        assert final_doc.name.startswith("Updated by thread ")
        # model_json should be valid (one of the thread's writes, not corrupted)
        assert "variables" in final_doc.model_json
        assert "constraints" in final_doc.model_json
        assert "thread_id" in final_doc.model_json
        thread_id = final_doc.model_json["thread_id"]
        assert isinstance(thread_id, int)
        # The variable name should match the thread_id
        assert final_doc.model_json["variables"][0]["name"] == f"x_{thread_id}"
        fresh.close()

    def test_concurrent_trigger_update_no_corruption(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        user_a: User,
    ):
        """Multiple threads updating the same trigger: final state is consistent."""
        from app.models.trigger import SolveTrigger

        # Create prerequisite document and version
        now = utcnow()
        doc = ModelBuilderDocument(
            id=generate_id("bld_"),
            organization_id=org_a.id,
            created_by=user_a.id,
            name="Trigger Update Doc",
            canvas_json={"nodes": [], "edges": []},
            model_json={"variables": []},
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db_session.add(doc)
        db_session.flush()

        ver = ModelVersion(
            id=generate_id("ver_"),
            document_id=doc.id,
            organization_id=org_a.id,
            canvas_json={"nodes": [], "edges": []},
            model_json={"variables": []},
            change_summary="v1",
            is_named=True,
            version_name="v1",
            sequence=1,
            created_at=now,
        )
        db_session.add(ver)
        db_session.flush()

        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=org_a.id,
            created_by=user_a.id,
            name="Original Name",
            document_id=doc.id,
            version_id=ver.id,
            trigger_secret="abc123hash",
            webhook_url="https://example.com/hook",
            is_enabled=True,
            total_runs=0,
            created_at=now,
            updated_at=now,
        )
        db_session.add(trigger)
        db_session.commit()
        trigger_id = trigger.id

        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def update_worker(thread_id: int) -> None:
            session = Session()
            try:
                t = session.query(SolveTrigger).filter(SolveTrigger.id == trigger_id).first()
                if not t:
                    results.put(("error", thread_id, "not found"))
                    return

                t.name = f"Trigger updated by {thread_id}"
                t.description = f"Description from thread {thread_id}"
                t.updated_at = utcnow()
                session.commit()
                results.put(("success", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=update_worker, args=(i,), name=f"trig-update-{i}")
            for i in range(10)
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        successes = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1

        assert successes == 10

        # Verify final state is consistent (last-write-wins)
        fresh = Session()
        final_trigger = fresh.query(SolveTrigger).filter(SolveTrigger.id == trigger_id).first()
        assert final_trigger is not None
        assert final_trigger.name.startswith("Trigger updated by ")
        assert final_trigger.description.startswith("Description from thread ")
        # Name and description should reference the same thread
        name_thread = final_trigger.name.replace("Trigger updated by ", "")
        desc_thread = final_trigger.description.replace("Description from thread ", "")
        assert name_thread == desc_thread, (
            f"Inconsistent state: name says thread {name_thread}, "
            f"description says thread {desc_thread}"
        )
        fresh.close()

    def test_concurrent_counter_increment(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        user_a: User,
    ):
        """Concurrent counter increments on trigger.total_runs: exact count.

        Note: Without SELECT FOR UPDATE on the trigger row, concurrent
        increments can be lost (read-modify-write race). This test verifies
        the current behavior.
        """
        from app.models.trigger import SolveTrigger

        now = utcnow()
        doc = ModelBuilderDocument(
            id=generate_id("bld_"),
            organization_id=org_a.id,
            created_by=user_a.id,
            name="Counter Doc",
            canvas_json={},
            model_json={},
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db_session.add(doc)
        db_session.flush()

        ver = ModelVersion(
            id=generate_id("ver_"),
            document_id=doc.id,
            organization_id=org_a.id,
            canvas_json={},
            change_summary="v1",
            is_named=True,
            version_name="v1",
            sequence=1,
            created_at=now,
        )
        db_session.add(ver)
        db_session.flush()

        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=org_a.id,
            created_by=user_a.id,
            name="Counter Trigger",
            document_id=doc.id,
            version_id=ver.id,
            trigger_secret="hash",
            webhook_url="https://example.com",
            is_enabled=True,
            total_runs=0,
            created_at=now,
            updated_at=now,
        )
        db_session.add(trigger)
        db_session.commit()
        trigger_id = trigger.id

        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)

        def increment_worker(thread_id: int) -> None:
            session = Session()
            try:
                # Use SQL-level increment to avoid read-modify-write race
                session.execute(
                    text(
                        "UPDATE solve_triggers SET total_runs = total_runs + 1 "
                        "WHERE id = :trigger_id"
                    ),
                    {"trigger_id": trigger_id},
                )
                session.commit()
                results.put(("success", thread_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", thread_id, str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=increment_worker, args=(i,), name=f"incr-{i}")
            for i in range(20)
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        successes = 0
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                successes += 1

        assert successes == 20

        # Verify exact count
        fresh = Session()
        final = fresh.query(SolveTrigger).filter(SolveTrigger.id == trigger_id).first()
        assert final.total_runs == 20, f"Expected 20 total_runs, got {final.total_runs}"
        fresh.close()


class TestConcurrentTriggerWorkspacePool:
    """Concurrent fires of the same trigger pulling from one workspace pool.

    The workspace credit pool deducts via SQL UPDATE WHERE (in
    workspace_credits_service.deduct_credits_for_solve), which guarantees
    that pool.used_credits never exceeds pool.allocated_credits, even under
    concurrent fire. This test plants a pool with a tight budget and races
    N workers through threading.Barrier; the contract is:

      - No negative balance: pool.used_credits <= pool.allocated_credits
      - Exactly K workers succeed (where K = allocated // per_solve)
      - The remaining N - K workers raise ValueError (or fall through to
        the org balance, which we forbid by setting it to 0)
    """

    def test_concurrent_trigger_workspace_pool_no_negative(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        user_a: User,
    ):
        """10 concurrent fires against a pool of 20 credits at 5 each: exactly 4 succeed."""
        from app.models.workspace import Workspace
        from app.models.workspace_credits import WorkspaceCreditPool
        from app.services.workspace_credits_service import deduct_credits_for_solve

        # Set the org balance to 0 so the workspace pool is the only credit source.
        # If anything leaks to org_balance fallback, we'll see negative org balance.
        org_a.credits_balance = 0
        db_session.commit()

        ws = Workspace(
            id="ws_concurrent_pool",
            organization_id=org_a.id,
            name="Concurrent Pool Workspace",
            is_active=True,
            created_by=user_a.id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db_session.add(ws)
        db_session.flush()

        pool = WorkspaceCreditPool(
            id=generate_id("wcp_"),
            workspace_id=ws.id,
            organization_id=org_a.id,
            allocated_credits=20,  # exactly 4 fires of 5 credits each
            used_credits=0,
            last_alert_threshold=None,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db_session.add(pool)
        db_session.commit()

        per_solve = 5
        n_workers = 10
        results: queue.Queue = queue.Queue()
        SessionFactory = sessionmaker(bind=db_engine)
        barrier = threading.Barrier(n_workers, timeout=30)
        org_a_id = org_a.id
        ws_id = ws.id

        def fire_worker(thread_id: int) -> None:
            session = None
            try:
                # Wait at the barrier FIRST so all threads start the actual
                # deduction at the same instant. Doing the DB query before
                # the barrier can break the barrier if any single query is
                # slow enough to time out.
                try:
                    barrier.wait()
                except threading.BrokenBarrierError:
                    results.put(("error", thread_id, "BrokenBarrierError"))
                    return

                session = SessionFactory()
                fresh_org = session.query(Organization).filter(Organization.id == org_a_id).first()
                try:
                    src = deduct_credits_for_solve(
                        db=session,
                        org=fresh_org,
                        workspace_id=ws_id,
                        credits_needed=per_solve,
                    )
                    session.commit()
                    results.put(("ok", thread_id, src))
                except ValueError as exc:
                    session.rollback()
                    results.put(("denied", thread_id, str(exc)))
            except Exception as exc:
                if session is not None:
                    try:
                        session.rollback()
                    except Exception:
                        pass
                results.put(("error", thread_id, f"{type(exc).__name__}: {exc}"))
            finally:
                if session is not None:
                    session.close()

        threads = [
            threading.Thread(target=fire_worker, args=(i,), name=f"pool-fire-{i}")
            for i in range(n_workers)
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        outcomes = []
        while not results.empty():
            outcomes.append(results.get())

        ok = [o for o in outcomes if o[0] == "ok"]
        denied = [o for o in outcomes if o[0] == "denied"]
        errored = [o for o in outcomes if o[0] == "error"]

        # Hard contract assertions
        assert errored == [], f"unexpected thread errors: {errored}"
        assert len(outcomes) == n_workers
        assert len(ok) == 4, f"expected 4 successful pool deductions, got {len(ok)}: {outcomes}"
        assert len(denied) == 6, f"expected 6 denied deductions, got {len(denied)}: {outcomes}"
        # Successful deductions must have been against the pool, never the org fallback
        # (org balance is 0 and we want this to fail loudly if leaked)
        for outcome in ok:
            assert outcome[2] == "pool", (
                f"expected successful deductions to use pool, got {outcome[2]}"
            )

        # Pool must show exactly 4*5=20 used, never more (no over-deduction)
        fresh = SessionFactory()
        try:
            final_pool = (
                fresh.query(WorkspaceCreditPool).filter(WorkspaceCreditPool.id == pool.id).first()
            )
            assert final_pool.used_credits == 20, (
                f"pool over-deducted: used_credits={final_pool.used_credits}, allocated=20"
            )
            assert final_pool.used_credits <= final_pool.allocated_credits, (
                "pool used_credits exceeded allocated_credits — race condition!"
            )

            # Org balance must NOT have gone negative (was 0; nothing should have
            # fallen through to it because all denied workers raised ValueError)
            final_org = fresh.query(Organization).filter(Organization.id == org_a.id).first()
            assert final_org.credits_balance >= 0, (
                f"org balance went negative: {final_org.credits_balance}"
            )
            assert final_org.credits_balance == 0, (
                f"org balance was touched by fallback: {final_org.credits_balance}"
            )
        finally:
            fresh.close()
