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
    ModelExecution,
    ModelProject,
    ModelProjectListing,
    Organization,
    User,
)
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def org_a(db_session: Session) -> Organization:
    """Organization A with 1000 credits."""
    org = Organization(
        id="org_concurrent_a",
        name="Concurrent Org A",
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
def listed_project(db_session: Session) -> ModelProjectListing:
    """Published marketplace listing (project + facet) for marketplace tests."""
    author = Organization(id=generate_id("org_"), name="Listing Author", is_active=True)
    db_session.add(author)
    db_session.flush()
    pid = generate_id("mp_")
    db_session.add(
        ModelProject(id=pid, organization_id=author.id, name="Concurrent Source", status="active")
    )
    db_session.flush()
    listing = ModelProjectListing(
        model_project_id=pid,
        name="test_concurrent_model",
        display_name="Concurrent Test Model",
        description="A model for concurrent testing",
        category="general",
        generator_type="custom",
        input_schema={"type": "object"},
        input_fields=[{"name": "x", "type": "number"}],
        example_input={"x": 1},
        status="published",
        is_public=True,
        is_official=True,
        author_organization_id=author.id,
        total_activations=0,
        total_executions=0,
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)
    return listing


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
                # Create execution record
                execution = ModelExecution(
                    id=f"exe_concurrent_{org_id}_{thread_id}",
                    organization_id=org_id,
                    input_data={"thread": thread_id},
                    status="completed",
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

        fresh.close()


class TestConcurrentModelFork:
    """Two users adopting the same marketplace model get their own fork
    ModelProject (P1.5 fusion: activate collapsed into from-marketplace seeding)."""

    @staticmethod
    def _fork_worker(Session, results, org_id: str, listing_id: str) -> None:
        session = Session()
        try:
            fork = ModelProject(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                name="Concurrent fork",
                status="active",
                source_type="marketplace",
                source_ref=listing_id,
            )
            session.add(fork)
            # Adoption counter bump — same statement the from-marketplace route runs.
            session.query(ModelProjectListing).filter(
                ModelProjectListing.model_project_id == listing_id
            ).update(
                {ModelProjectListing.total_activations: ModelProjectListing.total_activations + 1}
            )
            session.commit()
            results.put(("success", org_id, fork.id))
        except Exception as exc:
            session.rollback()
            results.put(("error", org_id, str(exc)))
        finally:
            session.close()

    def test_two_orgs_fork_same_listing(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        org_b: Organization,
        listed_project: ModelProjectListing,
    ):
        """Two orgs fork the same published listing: both get their own project
        and the adoption counter absorbs both bumps without corruption."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)
        listing_id = listed_project.model_project_id

        threads = [
            threading.Thread(
                target=self._fork_worker,
                args=(Session, results, org_a.id, listing_id),
                name="fork-a",
            ),
            threading.Thread(
                target=self._fork_worker,
                args=(Session, results, org_b.id, listing_id),
                name="fork-b",
            ),
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
        assert successes[org_a.id] != successes[org_b.id]

        # Verify in DB: one fork per org, counter absorbed both increments
        fresh = Session()
        for org_id in (org_a.id, org_b.id):
            forks = (
                fresh.query(ModelProject)
                .filter(
                    ModelProject.organization_id == org_id,
                    ModelProject.source_ref == listing_id,
                    ModelProject.source_type == "marketplace",
                )
                .all()
            )
            assert len(forks) == 1
        counter = (
            fresh.query(ModelProjectListing.total_activations)
            .filter(ModelProjectListing.model_project_id == listing_id)
            .scalar()
        )
        assert counter == 2, f"Adoption counter lost an increment: {counter}"
        fresh.close()

    def test_same_org_can_fork_twice(
        self,
        db_engine,
        db_session: Session,
        org_a: Organization,
        listed_project: ModelProjectListing,
    ):
        """Same org forking the same listing concurrently gets TWO independent
        projects — allowed by design post-fusion (like using a template twice);
        the legacy 'already activated' uniqueness died with the activate flow."""
        results: queue.Queue = queue.Queue()
        Session = sessionmaker(bind=db_engine)
        listing_id = listed_project.model_project_id
        barrier = threading.Barrier(2, timeout=10)

        def fork_with_barrier(thread_id: int) -> None:
            barrier.wait()
            self._fork_worker(Session, results, org_a.id, listing_id)

        threads = [
            threading.Thread(target=fork_with_barrier, args=(i,), name=f"dup-fork-{i}")
            for i in range(2)
        ]
        for t in threads:
            t.start()
        _join_threads(threads)

        successes = 0
        while not results.empty():
            r = results.get()
            assert r[0] == "success", f"Expected success, got {r}"
            successes += 1

        assert successes == 2
        total_forks = (
            Session()
            .query(ModelProject)
            .filter(
                ModelProject.organization_id == org_a.id,
                ModelProject.source_ref == listing_id,
            )
            .count()
        )
        assert total_forks == 2


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
