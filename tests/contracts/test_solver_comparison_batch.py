"""POST/GET/cancel /solvers/compare/batches — several datasets, several solvers.

A matrix is read as evidence about which solver to pick, so what it has to keep
is stricter than "it returns a grid": every cell must have been solved on the
same terms, a dataset that could not be built must stop the launch instead of
quietly disappearing from the table, and the grid must say which dataset each row
came from. A missing row is read as "nothing to see there", which is exactly the
row that would have changed the answer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.v2.solver_comparison as comparison_api
import app.domains.solver.tasks.comparison_tasks as comparison_tasks_mod
from app.models import ModelExecution, ModelProject, Organization, SolverComparison
from app.models.optimization_model import ExecutionStatus
from app.models.solver_comparison import ComparisonStatus

pytestmark = pytest.mark.contract

_URL = "/api/v2/solvers/compare/batches"

#: A declaration-only source: it needs a dataset to become a problem, which is
#: what makes a matrix meaningful in the first place.
_SOURCE = """
set I;
param w{I};
var x{I} binary;
maximize total: sum{i in I} w[i] * x[i];
subject to cap: sum{i in I} x[i] <= 1;
"""

_JANUARY = {"sets": {"I": ["a", "b"]}, "params": {"w": {"a": 2, "b": 3}}}
_FEBRUARY = {"sets": {"I": ["a", "b", "c"]}, "params": {"w": {"a": 5, "b": 1, "c": 4}}}
#: Declares the set but never fills the parameter — a compile failure.
_BROKEN = {"sets": {"I": ["a", "b"]}, "params": {}}


@pytest.fixture
def captured_dispatch(monkeypatch):
    """Capture the enqueue instead of dialling a broker."""
    calls: list[dict] = []

    class _Result:
        id = "task_matrix_1"

    def _fake_apply_async(*args, **kwargs):
        calls.append(kwargs)
        return _Result()

    monkeypatch.setattr(
        comparison_tasks_mod.run_solver_comparison, "apply_async", _fake_apply_async
    )
    return calls


def _seed_project(client: TestClient, db_session: Session, *, source: str | None = _SOURCE) -> str:
    """A project whose draft carries the JModel source. Returns its id."""
    project_id = client.post("/api/v2/projects", json={"name": "Matrix host"}).json()["id"]
    if source is not None:
        project = db_session.query(ModelProject).filter(ModelProject.id == project_id).first()
        project.draft_dsl_source = source
        db_session.commit()
    return project_id


def _seed_dataset(client: TestClient, project_id: str, name: str, data: dict) -> str:
    response = client.post(
        f"/api/v2/projects/{project_id}/datasets", json={"name": name, "data_json": data}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _seed_matrix(
    client: TestClient, db_session: Session, **overrides
) -> tuple[str, list[str], dict]:
    """A project with January and February, launched against SCIP and HiGHS."""
    project_id = _seed_project(client, db_session)
    dataset_ids = [
        _seed_dataset(client, project_id, "January", _JANUARY),
        _seed_dataset(client, project_id, "February", _FEBRUARY),
    ]
    body = {
        "project_id": project_id,
        "dataset_ids": dataset_ids,
        "solver_names": ["scip", "highs"],
    }
    body.update(overrides)
    response = client.post(_URL, json=body)
    assert response.status_code == 202, response.text
    return project_id, dataset_ids, response.json()


# ──────────────────────────────────────────────────────────────
# Routing
# ──────────────────────────────────────────────────────────────


# CONTRACT-TEST: /solvers/compare/batches must not be swallowed by the
# /solvers/compare/{comparison_id} route. Both routers live under the same
# prefix, and included the other way round every path here answers
# "Comparison not found" — a 404 that looks like missing data, not a bug.
def test_the_batches_path_is_not_swallowed_by_the_comparison_id_route(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.get(_URL)

    assert response.status_code == 200, response.text
    assert "batches" in response.json()


# ──────────────────────────────────────────────────────────────
# Launching
# ──────────────────────────────────────────────────────────────


# CONTRACT-TEST: a matrix is one comparison PER DATASET, sharing a batch id.
# The per-row comparison is what carries the terms every solver received; a
# single row covering several datasets could not say that.
def test_a_matrix_is_one_comparison_per_dataset(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, dataset_ids, detail = _seed_matrix(authenticated_client, db_session)

    assert len(detail["rows"]) == 2
    rows = db_session.query(SolverComparison).all()
    assert len(rows) == 2
    assert {row.batch_id for row in rows} == {detail["batch_id"]}
    assert sorted(row.batch_position for row in rows) == [0, 1]
    assert [row["dataset_id"] for row in detail["rows"]] == dataset_ids

    # One task per row, all on the single-slot comparison queue, so the runs stay
    # sequential on one machine.
    assert len(captured_dispatch) == 2
    assert {call["queue"] for call in captured_dispatch} == {"solve_compare"}


# CONTRACT-TEST: every cell of the matrix was solved on the same terms. A grid
# whose rows had different time limits compares settings, not solvers.
def test_every_row_of_the_matrix_gets_the_same_terms(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, _dataset_ids, detail = _seed_matrix(
        authenticated_client,
        db_session,
        settings={"time_limit_seconds": 12, "gap_tolerance": 0.05},
    )

    assert detail["settings"]["time_limit_seconds"] == 12
    assert detail["settings"]["gap_tolerance"] == 0.05
    for row in db_session.query(SolverComparison).all():
        assert row.time_limit_seconds == 12
        assert row.gap_tolerance == 0.05
        assert row.threads == detail["settings"]["threads"]
        assert row.problem_data["options"]["time_limit_seconds"] == 12


def test_each_row_names_its_dataset_and_its_compiled_size(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, _dataset_ids, detail = _seed_matrix(authenticated_client, db_session)

    by_name = {row["dataset_name"]: row for row in detail["rows"]}
    assert set(by_name) == {"January", "February"}
    # The same source grounds to a different size per dataset, which is often the
    # answer to why one row took longer than the one above it.
    assert by_name["January"]["variable_count"] == 2
    assert by_name["February"]["variable_count"] == 3
    assert by_name["January"]["problem_class"] == "BIP"


# CONTRACT-TEST: every cell carries the dataset it was compiled against. The run
# history has a dataset column, and a matrix run that leaves it empty reads as a
# run of the model with no data behind it.
def test_every_cell_records_the_dataset_it_solved(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, dataset_ids, _detail = _seed_matrix(authenticated_client, db_session)

    executions = db_session.query(ModelExecution).all()
    assert len(executions) == 4
    assert {execution.dataset_id for execution in executions} == set(dataset_ids)
    assert {execution.dataset_name for execution in executions} == {"January", "February"}


def test_the_columns_are_the_solvers_asked_for(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, _dataset_ids, detail = _seed_matrix(authenticated_client, db_session)

    assert detail["solver_names"] == ["scip", "highs"]
    for row in detail["rows"]:
        assert [cell["solver_name"] for cell in row["results"]] == ["scip", "highs"]
        assert all(cell["status"] == "pending" for cell in row["results"])


def test_the_same_dataset_twice_is_one_row(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    project_id = _seed_project(authenticated_client, db_session)
    dataset_id = _seed_dataset(authenticated_client, project_id, "January", _JANUARY)

    response = authenticated_client.post(
        _URL,
        json={
            "project_id": project_id,
            "dataset_ids": [dataset_id, dataset_id],
            "solver_names": ["scip"],
        },
    )

    assert response.status_code == 202, response.text
    assert len(response.json()["rows"]) == 1


# ──────────────────────────────────────────────────────────────
# Refusing
# ──────────────────────────────────────────────────────────────


# CONTRACT-TEST: one dataset that does not compile stops the WHOLE launch and
# names it. Running the rest would drop a row silently, and the dataset the model
# cannot express is the one a reader most needs to see.
def test_a_dataset_that_does_not_compile_rejects_the_whole_matrix(
    authenticated_client: TestClient,
    db_session: Session,
) -> None:
    project_id = _seed_project(authenticated_client, db_session)
    good = _seed_dataset(authenticated_client, project_id, "January", _JANUARY)
    broken = _seed_dataset(authenticated_client, project_id, "Incomplete", _BROKEN)

    response = authenticated_client.post(
        _URL,
        json={
            "project_id": project_id,
            "dataset_ids": [good, broken],
            "solver_names": ["scip"],
        },
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "dataset_did_not_compile"
    assert detail["dataset_name"] == "Incomplete"
    # Nothing was written: no half-built matrix left behind.
    assert db_session.query(SolverComparison).count() == 0
    assert db_session.query(ModelExecution).count() == 0


def test_a_model_without_a_jmodel_source_cannot_be_a_matrix(
    authenticated_client: TestClient,
    db_session: Session,
) -> None:
    project_id = _seed_project(authenticated_client, db_session, source=None)

    response = authenticated_client.post(
        _URL,
        json={"project_id": project_id, "dataset_ids": ["ds_nope"], "solver_names": ["scip"]},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "project_has_no_jmodel_source"


def test_a_dataset_of_another_project_is_not_found(
    authenticated_client: TestClient,
    db_session: Session,
) -> None:
    project_id = _seed_project(authenticated_client, db_session)
    other_project = _seed_project(authenticated_client, db_session)
    foreign_dataset = _seed_dataset(authenticated_client, other_project, "January", _JANUARY)

    response = authenticated_client.post(
        _URL,
        json={
            "project_id": project_id,
            "dataset_ids": [foreign_dataset],
            "solver_names": ["scip"],
        },
    )

    assert response.status_code == 404, response.text


def test_a_matrix_no_solver_can_run_is_refused(
    authenticated_client: TestClient,
    db_session: Session,
) -> None:
    project_id = _seed_project(authenticated_client, db_session)
    dataset_id = _seed_dataset(authenticated_client, project_id, "January", _JANUARY)

    response = authenticated_client.post(
        _URL,
        json={
            "project_id": project_id,
            "dataset_ids": [dataset_id],
            "solver_names": ["hexaly"],
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "no_solver_can_run_this_model"


# CONTRACT-TEST: the quota is charged per CELL, not per row. Five datasets by
# four solvers is twenty solves, and a matrix that cannot afford all of them is
# refused whole rather than run down to where the quota stops.
def test_a_matrix_the_quota_cannot_cover_is_refused_whole(
    authenticated_client: TestClient,
    db_session: Session,
    real_rate_limiter,
    monkeypatch,
) -> None:
    project_id = _seed_project(authenticated_client, db_session)
    dataset_ids = [
        _seed_dataset(authenticated_client, project_id, "January", _JANUARY),
        _seed_dataset(authenticated_client, project_id, "February", _FEBRUARY),
    ]
    limits = dict(comparison_api.PSS.get_instance_limits(db_session))
    limits["max_daily_solves"] = 3  # two datasets by two solvers needs four
    monkeypatch.setattr(comparison_api.PSS, "get_instance_limits", lambda _db: limits)

    response = authenticated_client.post(
        _URL,
        json={
            "project_id": project_id,
            "dataset_ids": dataset_ids,
            "solver_names": ["scip", "highs"],
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["error"] == "daily_solve_quota_exceeded"
    assert db_session.query(SolverComparison).count() == 0


# CONTRACT-TEST: a row that never reached the queue closes its own cells. Left
# pending they would spin forever, and the page polls for as long as one cell has
# no verdict — waiting on a worker nobody ever told to start.
def test_a_row_that_could_not_be_queued_closes_its_cells(
    authenticated_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    project_id = _seed_project(authenticated_client, db_session)
    dataset_ids = [
        _seed_dataset(authenticated_client, project_id, "January", _JANUARY),
        _seed_dataset(authenticated_client, project_id, "February", _FEBRUARY),
    ]

    calls: list[dict] = []

    def _broker_is_down(*_args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise RuntimeError("broker unreachable")

        class _Result:
            id = "task_matrix_ok"

        return _Result()

    monkeypatch.setattr(comparison_tasks_mod.run_solver_comparison, "apply_async", _broker_is_down)

    response = authenticated_client.post(
        _URL,
        json={
            "project_id": project_id,
            "dataset_ids": dataset_ids,
            "solver_names": ["scip"],
        },
    )

    assert response.status_code == 202, response.text
    rows = response.json()["rows"]
    # The first row was queued; the second says it failed, and its cell says so
    # too rather than waiting for a run that will never happen.
    assert rows[0]["status"] == ComparisonStatus.PENDING.value
    assert rows[0]["results"][0]["status"] == ExecutionStatus.PENDING.value
    assert rows[1]["status"] == ComparisonStatus.FAILED.value
    assert rows[1]["error_message"]
    assert rows[1]["results"][0]["status"] == ExecutionStatus.CANCELLED.value


# ──────────────────────────────────────────────────────────────
# Reading it back
# ──────────────────────────────────────────────────────────────


def test_the_matrix_status_is_derived_from_its_rows(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, _dataset_ids, detail = _seed_matrix(authenticated_client, db_session)
    batch_id = detail["batch_id"]
    assert detail["status"] == ComparisonStatus.PENDING.value

    rows = db_session.query(SolverComparison).order_by(SolverComparison.batch_position).all()
    rows[0].status = ComparisonStatus.RUNNING.value
    db_session.commit()
    assert _get(authenticated_client, batch_id)["status"] == ComparisonStatus.RUNNING.value

    # One row done and one still queued is still a running matrix.
    rows[0].status = ComparisonStatus.COMPLETED.value
    db_session.commit()
    assert _get(authenticated_client, batch_id)["status"] == ComparisonStatus.RUNNING.value

    rows[1].status = ComparisonStatus.COMPLETED.value
    db_session.commit()
    assert _get(authenticated_client, batch_id)["status"] == ComparisonStatus.COMPLETED.value


def test_a_row_can_be_opened_as_the_comparison_it_is(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, _dataset_ids, detail = _seed_matrix(authenticated_client, db_session)
    comparison_id = detail["rows"][0]["comparison_id"]

    response = authenticated_client.get(f"/api/v2/solvers/compare/{comparison_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    # And it knows the matrix it belongs to, so the page can offer the way back.
    assert body["batch_id"] == detail["batch_id"]
    assert body["dataset_name"] == detail["rows"][0]["dataset_name"]


def test_the_history_lists_this_organizations_matrices(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    project_id, _dataset_ids, detail = _seed_matrix(authenticated_client, db_session)

    listing = authenticated_client.get(_URL, params={"project_id": project_id}).json()

    assert listing["total"] == 1
    entry = listing["batches"][0]
    assert entry["batch_id"] == detail["batch_id"]
    assert entry["dataset_count"] == 2
    assert entry["solver_names"] == ["scip", "highs"]


# ──────────────────────────────────────────────────────────────
# Cancelling
# ──────────────────────────────────────────────────────────────


def test_cancelling_a_matrix_stops_every_row_that_had_not_started(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, _dataset_ids, detail = _seed_matrix(authenticated_client, db_session)

    response = authenticated_client.post(f"{_URL}/{detail['batch_id']}/cancel")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == ComparisonStatus.CANCELLED.value
    db_session.expire_all()
    for row in db_session.query(SolverComparison).all():
        assert row.status == ComparisonStatus.CANCELLED.value
    for execution in db_session.query(ModelExecution).all():
        assert execution.status == ExecutionStatus.CANCELLED.value


def test_cancelling_leaves_a_finished_row_alone(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    _project_id, _dataset_ids, detail = _seed_matrix(authenticated_client, db_session)
    rows = db_session.query(SolverComparison).order_by(SolverComparison.batch_position).all()
    rows[0].status = ComparisonStatus.COMPLETED.value
    db_session.commit()

    authenticated_client.post(f"{_URL}/{detail['batch_id']}/cancel")

    db_session.expire_all()
    rows = db_session.query(SolverComparison).order_by(SolverComparison.batch_position).all()
    assert rows[0].status == ComparisonStatus.COMPLETED.value
    assert rows[1].status == ComparisonStatus.CANCELLED.value


# ──────────────────────────────────────────────────────────────
# Access
# ──────────────────────────────────────────────────────────────


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.get(_URL).status_code in (401, 403)
    assert client.post(_URL, json={}).status_code in (401, 403)


# CONTRACT-TEST: a matrix is org-scoped. Another organization's id must read as
# absent, not as forbidden-but-there.
def test_another_organizations_matrix_is_not_found(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization_2: Organization,
) -> None:
    from app.shared.utils.datetime_helpers import utcnow
    from app.shared.utils.id_generator import generate_id

    foreign = SolverComparison(
        id=generate_id("cmp_"),
        organization_id=test_organization_2.id,
        problem_data={"name": "theirs"},
        time_limit_seconds=60,
        gap_tolerance=0.0001,
        threads=1,
        solver_names=["scip"],
        status=ComparisonStatus.PENDING.value,
        batch_id="cmb_theirs",
        batch_position=0,
        created_at=utcnow(),
    )
    db_session.add(foreign)
    db_session.commit()

    assert authenticated_client.get(f"{_URL}/cmb_theirs").status_code == 404
    assert authenticated_client.post(f"{_URL}/cmb_theirs/cancel").status_code == 404
    assert authenticated_client.get(_URL).json()["total"] == 0


def _get(client: TestClient, batch_id: str) -> dict:
    response = client.get(f"{_URL}/{batch_id}")
    assert response.status_code == 200, response.text
    return response.json()
