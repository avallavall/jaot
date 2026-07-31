"""The solver domain's host ports and JAOT's wiring of them (D-16).

The domain no longer imports platform services: it declares a scenario-budget
reader and a solve-event sink in ``app/domains/solver/ports.py``, and JAOT
registers implementations at BOTH boots — the API lifespan and the Celery
worker (via the ``include`` list). The dangerous failure mode is a missing
registration in exactly one process: in production the two run separately, in
tests they are one process, so pytest alone cannot see the gap. These tests
pin the two things pytest CAN see: the wiring is on both boot paths, and an
unwired port fails loudly instead of falling back.
"""

import pytest

from app.domains.solver import ports
from app.models import Notification, NotificationType
from app.models.model_project import ModelProject, ModelProjectListing
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core.celery_app import celery_app
from app.shared.utils.id_generator import generate_id
from app.tasks.solver_ports import PlatformSolveEvents, register_solver_ports


@pytest.fixture
def unregistered_ports():
    """Blank port registry for the duration of one test, restored afterwards."""
    saved_reader = ports._scenario_budget_reader
    saved_sink = ports._solve_event_sink
    ports._scenario_budget_reader = None
    ports._solve_event_sink = None
    try:
        yield
    finally:
        ports._scenario_budget_reader = saved_reader
        ports._solve_event_sink = saved_sink


# CONTRACT-TEST: the worker's boot path must import the wiring module. The API
# registers in its lifespan; the worker's ONLY registration point is this
# include entry — dropping it would leave every solve in production unhosted
# while the single-process test suite keeps passing.
def test_worker_include_list_carries_the_port_wiring():
    assert "app.tasks.solver_ports" in celery_app.conf.include


# CONTRACT-TEST: an unwired port raises instead of falling back. The silent
# alternative — default budgets, dropped notifications — is exactly the failure
# no test suite would notice, so the domain must refuse to run unhosted.
def test_unregistered_ports_raise_instead_of_defaulting(unregistered_ports):
    with pytest.raises(RuntimeError, match="scenario-budget reader"):
        ports.scenario_budget(db=None)
    with pytest.raises(RuntimeError, match="solve-event sink"):
        ports.solve_events()


def test_register_solver_ports_wires_both_ports(unregistered_ports, db_session):
    """One call registers everything the domain declares — no port left behind."""
    register_solver_ports()
    assert ports.scenario_budget(db_session) is not None
    assert ports.solve_events() is not None


def test_budget_reader_reads_the_six_sensitivity_settings(db_session):
    """The registered reader answers with the platform's own values."""
    budget = ports.scenario_budget(db_session)

    assert budget.max_resolves == PSS.get_int(db_session, "SENSITIVITY_MAX_RESOLVES")
    assert budget.top_constraints == PSS.get_int(db_session, "SENSITIVITY_TOP_CONSTRAINTS")
    assert budget.top_decisions == PSS.get_int(db_session, "SENSITIVITY_TOP_DECISIONS")
    assert budget.per_solve_multiplier == PSS.get_float(
        db_session, "SENSITIVITY_PER_SOLVE_MULTIPLIER"
    )
    assert budget.per_solve_cap_seconds == PSS.get_int(
        db_session, "SENSITIVITY_PER_SOLVE_CAP_SECONDS"
    )
    assert budget.total_seconds == PSS.get_int(db_session, "SENSITIVITY_TOTAL_BUDGET_SECONDS")


BOUNDED_LP_INPUT = {
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 4}],
    "objective": {"sense": "maximize", "expression": "x"},
}


def _seed_listed_fork(db_session, organization, suffix: str) -> str:
    """A fork of a published generic listing, so the whole outcome path has
    somewhere real to land: a listing row for the counters, a user's model to
    execute. Returns the fork's id (its source listing id is ``hp_src_{suffix}``)."""
    db_session.add(
        ModelProject(
            id=f"hp_src_{suffix}",
            organization_id=organization.id,
            name=f"hp_src_{suffix}",
            status="active",
        )
    )
    db_session.flush()
    db_session.add(
        ModelProjectListing(
            model_project_id=f"hp_src_{suffix}",
            name=f"hp_src_{suffix}",
            display_name="Host Ports Listing",
            description="D-16 host-port wiring",
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            status="published",
            is_public=True,
            author_organization_id=organization.id,
        )
    )
    fork = ModelProject(
        id=f"hp_fork_{suffix}",
        organization_id=organization.id,
        name="Host ports fork",
        status="active",
        source_type="marketplace",
        source_ref=f"hp_src_{suffix}",
    )
    db_session.add(fork)
    db_session.commit()
    return fork.id


class TestSolveOutcomesSurviveTheWorkerSession:
    """The worker writes outcomes on its OWN session and closes it when the task
    ends. The notification writer only flushes, so without the task's follow-up
    commit the row silently died with that session — the log line printed, the
    bell stayed empty, and no assertion on the test's long-lived shared session
    could tell the difference. These tests read back through a DIFFERENT session
    after the worker's is gone, so only committed truth passes."""

    # CONTRACT-TEST: the completed-solve notification must survive the worker's
    # session. It was flushed and never committed — lost on close, invisible to
    # the suite, gone in production where the worker is a separate process.
    def test_completed_solve_notification_survives_the_worker_session(
        self, authenticated_client, db_session, test_organization
    ):
        model_id = _seed_listed_fork(db_session, test_organization, "done")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute",
            json={"input_data": BOUNDED_LP_INPUT, "async_mode": True},
        )
        assert response.status_code == 200, response.text
        execution_id = response.json()["execution_id"]

        # The eager worker ran on its own session and closed it. Expire ours so
        # every read below is DB truth, not this session's stale identity map.
        db_session.expire_all()

        rows = db_session.query(Notification).filter_by(organization_id=test_organization.id).all()
        row = next((r for r in rows if r.data.get("execution_id") == execution_id), None)
        assert row is not None, "the completed-solve notification did not survive the worker"
        assert row.type == NotificationType.EXECUTION_COMPLETED.value

        listing = db_session.get(ModelProjectListing, "hp_src_done")
        assert listing.total_executions == 1
        assert listing.successful_executions == 1

    # CONTRACT-TEST: the failed-solve notification takes a different path (the
    # except handler, after the failed row's own commit) and must survive too.
    def test_failed_solve_notification_survives_the_worker_session(
        self, authenticated_client, db_session, test_organization, monkeypatch
    ):
        import app.domains.solver.tasks.solve_tasks as solve_tasks_mod

        def _boom(*args, **kwargs):
            raise RuntimeError("solver exploded before loading")

        monkeypatch.setattr(solve_tasks_mod, "get_solver_service", _boom)
        model_id = _seed_listed_fork(db_session, test_organization, "fail")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute",
            json={"input_data": BOUNDED_LP_INPUT, "async_mode": True},
        )
        assert response.status_code == 200, response.text
        execution_id = response.json()["execution_id"]

        db_session.expire_all()

        rows = db_session.query(Notification).filter_by(organization_id=test_organization.id).all()
        row = next((r for r in rows if r.data.get("execution_id") == execution_id), None)
        assert row is not None, "the failed-solve notification did not survive the worker"
        assert row.type == NotificationType.EXECUTION_FAILED.value
        assert "solver exploded" in row.data["error"]


class TestPlatformSolveEvents:
    """JAOT's sink hands each event to the real service, real rows included."""

    def test_solve_completed_rings_the_notification_bell(
        self, db_session, test_user, test_organization
    ):
        PlatformSolveEvents().solve_completed(
            db_session,
            user_id=test_user.id,
            organization_id=test_organization.id,
            execution_id="exec-ports-1",
            model_name="Ports Fixture",
            objective_value=42.0,
        )
        db_session.flush()

        rows = (
            db_session.query(Notification)
            .filter_by(user_id=test_user.id, organization_id=test_organization.id)
            .all()
        )
        row = next(r for r in rows if r.data.get("execution_id") == "exec-ports-1")
        assert row.type == NotificationType.EXECUTION_COMPLETED.value
        assert row.data["model_name"] == "Ports Fixture"
        assert row.data["objective_value"] == 42.0

    def test_solve_failed_carries_the_error(self, db_session, test_user, test_organization):
        PlatformSolveEvents().solve_failed(
            db_session,
            user_id=test_user.id,
            organization_id=test_organization.id,
            execution_id="exec-ports-2",
            model_name="Ports Fixture",
            error="infeasible after presolve",
        )
        db_session.flush()

        rows = (
            db_session.query(Notification)
            .filter_by(user_id=test_user.id, organization_id=test_organization.id)
            .all()
        )
        row = next(r for r in rows if r.data.get("execution_id") == "exec-ports-2")
        assert row.type == NotificationType.EXECUTION_FAILED.value
        assert row.data["error"] == "infeasible after presolve"

    def test_listing_executed_moves_the_marketplace_counters(self, db_session, test_organization):
        project = ModelProject(
            id=generate_id("mp_"),
            organization_id=test_organization.id,
            name="Ports Listing Fixture",
        )
        db_session.add(project)
        db_session.flush()
        listing = ModelProjectListing(
            model_project_id=project.id,
            name="Ports Listing Fixture",
            display_name="Ports Listing Fixture",
            description="Counts runs for the port-wiring tests.",
            category="hr",
            version="1.0.0",
            status="published",
        )
        db_session.add(listing)
        db_session.flush()

        PlatformSolveEvents().listing_executed(
            db_session, project.id, succeeded=True, execution_time_ms=125.0
        )
        db_session.flush()
        db_session.refresh(listing)

        assert listing.total_executions == 1
        assert listing.successful_executions == 1
        assert listing.avg_execution_time_ms == pytest.approx(125.0)


class TestEveryTerminalRunNotifies:
    """# CONTRACT-TEST: finishing a solve must leave a notification, whoever ran it.

    Only ``solve_model_async`` (running a catalog model) emitted the completion
    event. ``solve_async`` — the path every studio solve takes, and the most
    common origin on the reference install — never did, so a run finished, the
    toast appeared, and the bell stayed empty forever. The emission now lives in
    the single execution writer all three workers commit through, so a fourth
    terminal path cannot quietly skip it.
    """

    def test_the_writer_notifies_when_it_completes_a_run(
        self, db_session, test_user, test_organization, monkeypatch
    ):
        from app.domains.solver import execution_writer

        project = ModelProject(
            id=generate_id("mp_"),
            organization_id=test_organization.id,
            name="Studio Model",
            status="active",
        )
        db_session.add(project)
        db_session.flush()

        execution = execution_writer.insert_pending(
            db_session,
            execution_id=generate_id("exe_"),
            organization_id=test_organization.id,
            celery_task_id=generate_id("task_"),
            input_data={},
            solver_name="scip",
            executed_by_user_id=test_user.id,
            origin="visual_builder",
            model_project_id=project.id,
        )
        execution.objective_value = 12.0
        db_session.flush()

        register_solver_ports()
        execution_writer._notify_completed(db_session, execution)
        db_session.flush()

        row = (
            db_session.query(Notification)
            .filter_by(user_id=test_user.id, type=NotificationType.EXECUTION_COMPLETED.value)
            .first()
        )
        assert row is not None, "a studio solve finished and left no notification"
        # The name comes from the project, since the execution row has none.
        assert "Studio Model" in (row.message or "") + (row.title or "")

    def test_a_run_with_no_person_behind_it_notifies_nobody(self, db_session, test_organization):
        """API-key runs have no user to ring; that must not raise."""
        from app.domains.solver import execution_writer

        execution = execution_writer.insert_pending(
            db_session,
            execution_id=generate_id("exe_"),
            organization_id=test_organization.id,
            celery_task_id=generate_id("task_"),
            input_data={},
            solver_name="scip",
            executed_by_user_id=None,
            origin="api",
        )
        db_session.flush()

        register_solver_ports()
        execution_writer._notify_completed(db_session, execution)

        assert db_session.query(Notification).count() == 0
