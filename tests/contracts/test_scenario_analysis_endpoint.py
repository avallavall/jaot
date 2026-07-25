"""POST/GET /models/executions/{id}/scenario-analysis — the what-if batch (L2).

The batch is expensive (a full re-solve per scenario), so the endpoint contract
is as much about what it REFUSES to do — start a second batch, recompute a
cached one, spin forever on a dead one — as about the analysis itself.
"""

import queue
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import app.domains.solver.tasks.scenario_tasks as scenario_tasks_mod
from app.domains.solver import scenario_job
from app.models import ModelExecution, Organization
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

pytestmark = pytest.mark.contract

_PROBLEM = {
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0},
        {"name": "y", "type": "continuous", "lower_bound": 0},
    ],
    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
    "constraints": [
        {"name": "cap", "expression": "x + y <= 10"},
        {"name": "xmax", "expression": "x <= 4"},
    ],
}


def _seed_execution(db: Session, org_id: str, **overrides) -> ModelExecution:
    fields = {
        "id": generate_id("exe_"),
        "organization_id": org_id,
        "input_data": _PROBLEM,
        "result_data": {"model": {"x": 4.0, "y": 6.0}, "objective_value": 24.0},
        "status": "completed",
        "solver_status": "optimal",
        "solver_name": "scip",
        "objective_value": 24.0,
        "execution_time_ms": 40,
    }
    fields.update(overrides)
    execution = ModelExecution(**fields)
    db.add(execution)
    db.commit()
    return execution


@pytest.fixture
def captured_dispatch(monkeypatch):
    """Capture the enqueue instead of dialling a broker."""
    calls: list[dict] = []

    class _Result:
        id = "task_scenario_1"

    def _fake_apply_async(*args, **kwargs):
        calls.append(kwargs)
        return _Result()

    monkeypatch.setattr(
        scenario_tasks_mod.scenario_analysis_async, "apply_async", _fake_apply_async
    )
    return calls


def test_requesting_the_batch_queues_it_once(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    captured_dispatch: list[dict],
):
    execution = _seed_execution(db_session, test_organization.id)

    res = authenticated_client.post(f"/api/v2/models/executions/{execution.id}/scenario-analysis")

    assert res.status_code == 202
    assert res.json()["status"] == "running"
    assert len(captured_dispatch) == 1
    # Routed to the queue of the execution's own solver, and bounded: a hung
    # analysis must not pin a worker any more than a hung solve does.
    assert captured_dispatch[0]["queue"] == "solve_scip"
    assert captured_dispatch[0]["soft_time_limit"] > 0
    assert captured_dispatch[0]["time_limit"] > captured_dispatch[0]["soft_time_limit"]


# CONTRACT-TEST: requesting the batch twice must never start two batches — each
# scenario is a full solve, so a double click would double the worker load.
def test_a_second_request_joins_the_batch_in_flight(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    captured_dispatch: list[dict],
):
    execution = _seed_execution(db_session, test_organization.id)
    url = f"/api/v2/models/executions/{execution.id}/scenario-analysis"

    first = authenticated_client.post(url)
    second = authenticated_client.post(url)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["status"] == "running"
    assert len(captured_dispatch) == 1


def test_a_completed_batch_is_served_from_the_cache(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    captured_dispatch: list[dict],
):
    execution = _seed_execution(db_session, test_organization.id)
    execution.scenario_analysis = {
        "status": scenario_job.STATUS_COMPLETED,
        "requested_at": utcnow().isoformat(),
        "completed_at": utcnow().isoformat(),
        "error": None,
        "result": {"computed": True, "base_objective": 24.0, "resolves_used": 3},
    }
    db_session.commit()

    res = authenticated_client.post(f"/api/v2/models/executions/{execution.id}/scenario-analysis")

    assert res.json()["status"] == "completed"
    assert res.json()["analysis"]["resolves_used"] == 3
    assert captured_dispatch == []  # never re-run what is already answered


def test_a_batch_that_died_with_its_worker_can_be_requeued(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    captured_dispatch: list[dict],
):
    """A 'running' row past its own budget is dead, not working — the button
    must come back instead of spinning forever."""
    execution = _seed_execution(db_session, test_organization.id)
    long_dead = utcnow() - timedelta(seconds=scenario_job.STALE_GRACE_SECONDS + 3600)
    execution.scenario_analysis = {
        "status": scenario_job.STATUS_RUNNING,
        "requested_at": long_dead.isoformat(),
        "budget_seconds": 300.0,
        "result": None,
    }
    db_session.commit()

    read = authenticated_client.get(f"/api/v2/models/executions/{execution.id}/scenario-analysis")
    assert read.json()["status"] == "absent"

    res = authenticated_client.post(f"/api/v2/models/executions/{execution.id}/scenario-analysis")
    assert res.json()["status"] == "running"
    assert len(captured_dispatch) == 1


def test_reading_before_any_request_reports_absent(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
):
    execution = _seed_execution(db_session, test_organization.id)

    res = authenticated_client.get(f"/api/v2/models/executions/{execution.id}/scenario-analysis")

    assert res.status_code == 200
    assert res.json()["status"] == "absent"
    assert res.json()["analysis"] is None


def test_an_execution_without_a_solution_is_refused(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    captured_dispatch: list[dict],
):
    execution = _seed_execution(db_session, test_organization.id, result_data={"model": {}})

    res = authenticated_client.post(f"/api/v2/models/executions/{execution.id}/scenario-analysis")

    assert res.status_code == 422
    assert res.json()["detail"] == "no_solution"
    assert captured_dispatch == []


def test_another_orgs_execution_is_not_analysable(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    captured_dispatch: list[dict],
):
    other_org = Organization(id=generate_id("org_"), name="Other", slug=f"other-{generate_id('')}")
    db_session.add(other_org)
    db_session.commit()
    execution = _seed_execution(db_session, other_org.id)

    post = authenticated_client.post(f"/api/v2/models/executions/{execution.id}/scenario-analysis")
    get = authenticated_client.get(f"/api/v2/models/executions/{execution.id}/scenario-analysis")

    assert post.status_code == 404
    assert get.status_code == 404
    assert captured_dispatch == []


def test_the_batch_needs_authentication(client: TestClient):
    assert client.post("/api/v2/models/executions/exe_x/scenario-analysis").status_code == 401
    assert client.get("/api/v2/models/executions/exe_x/scenario-analysis").status_code == 401


# CONTRACT-TEST: on a small model the worker can finish the whole batch before
# the POST returns. The request must not then bury that result under its own
# stale "running" envelope.
def test_a_fast_workers_result_is_not_buried_by_the_request(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    monkeypatch,
):
    execution = _seed_execution(db_session, test_organization.id)

    def _run_inline(*args, **kwargs):
        return scenario_tasks_mod.scenario_analysis_async.apply(
            args=kwargs["args"], task_id=kwargs.get("task_id")
        )

    monkeypatch.setattr(scenario_tasks_mod.scenario_analysis_async, "apply_async", _run_inline)

    res = authenticated_client.post(f"/api/v2/models/executions/{execution.id}/scenario-analysis")
    assert res.status_code == 202

    db_session.expire_all()
    stored = db_session.query(ModelExecution).filter(ModelExecution.id == execution.id).first()
    assert stored.scenario_analysis["status"] == scenario_job.STATUS_COMPLETED
    assert stored.scenario_analysis["result"]["computed"] is True
    # …and the id the row carries is the one that actually ran.
    assert stored.scenario_analysis["task_id"]


# CONTRACT-TEST: two SIMULTANEOUS claims must produce exactly one batch. The
# sequential test above passes even without a lock; this one does not.
def test_two_concurrent_claims_produce_one_batch(
    db_session: Session,
    db_engine,
    test_organization: Organization,
):
    execution = _seed_execution(db_session, test_organization.id)
    results: queue.Queue = queue.Queue()
    barrier = threading.Barrier(2, timeout=15)
    SessionFactory = sessionmaker(bind=db_engine, expire_on_commit=False)

    def claim_worker() -> None:
        session = SessionFactory()
        try:
            barrier.wait()
            _, _, claimed = scenario_job.claim_batch(
                session, execution.id, test_organization.id, 300.0
            )
            session.commit()
            results.put(claimed)
        except Exception as exc:  # surfaced as a failure below, never swallowed
            session.rollback()
            results.put(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=claim_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    outcomes = [results.get(timeout=5) for _ in range(2)]
    assert all(not isinstance(o, Exception) for o in outcomes), outcomes
    # Exactly one winner: the loser waited on the row lock and then saw it running.
    assert sorted(outcomes) == [False, True]


# CONTRACT-TEST: the cached answer comes from REAL re-solves — the whole point
# of L2 is that the delta is measured, not estimated.
def test_the_task_runs_real_resolves_and_caches_the_answer(
    db_session: Session,
    test_organization: Organization,
):
    execution = _seed_execution(db_session, test_organization.id)

    result = scenario_tasks_mod.scenario_analysis_async.apply(
        args=[execution.id, test_organization.id, "scip"]
    ).get()

    assert result["status"] == "success"
    assert result["resolves_used"] > 0

    db_session.expire_all()
    stored = db_session.query(ModelExecution).filter(ModelExecution.id == execution.id).first()
    job = stored.scenario_analysis
    assert job["status"] == scenario_job.STATUS_COMPLETED
    analysis = job["result"]
    assert analysis["computed"] is True
    assert analysis["base_objective"] == pytest.approx(24.0)
    relax_cap = next(
        row
        for row in analysis["rhs_scenarios"]
        if row["constraint"] == "cap" and row["direction"] == "relax"
    )
    # One more unit of capacity is worth exactly +2 here — solved, not guessed.
    assert relax_cap["objective_delta"] == pytest.approx(2.0)
