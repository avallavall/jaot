"""POST/GET/cancel /solvers/compare — one problem, several solvers, identical terms.

The contract this surface has to keep is narrower than "it returns results". A
comparison table is read as evidence, so what matters is that every column got
the same deal, that a column which could not run says so instead of going blank,
and that the seconds in it came from one machine running one solve at a time.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.domains.solver.tasks.comparison_tasks as comparison_tasks_mod
import app.services.solver_comparison_setup as comparison_setup
from app.models import ModelExecution, Organization, SolverComparison
from app.models.optimization_model import ExecutionStatus
from app.models.solver_comparison import DEFAULT_COMPARISON_THREADS, ComparisonStatus
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

pytestmark = pytest.mark.contract

_URL = "/api/v2/solvers/compare"

_PROBLEM = {
    "name": "compare-me",
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

_INTEGER_PROBLEM = {
    "name": "integers-please",
    "variables": [
        {"name": "a", "type": "integer", "lower_bound": 0, "upper_bound": 5},
        {"name": "b", "type": "binary"},
    ],
    "objective": {"sense": "maximize", "expression": "2*a + 3*b"},
    "constraints": [{"name": "cap", "expression": "a + b <= 4"}],
}


@pytest.fixture
def captured_dispatch(monkeypatch):
    """Capture the enqueue instead of dialling a broker."""
    calls: list[dict] = []

    class _Result:
        id = "task_comparison_1"

    def _fake_apply_async(*args, **kwargs):
        calls.append(kwargs)
        return _Result()

    monkeypatch.setattr(
        comparison_tasks_mod.run_solver_comparison, "apply_async", _fake_apply_async
    )
    return calls


class _NoCloseSession:
    """The test session, wrapped so the task's ``close()`` does not end the
    SAVEPOINT the whole test is running inside."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self) -> None:
        return None


@pytest.fixture
def task_runs_on_the_test_session(db_session: Session, monkeypatch):
    """Let the comparison task use the session the test can see.

    The task opens a session of its own, which under the SAVEPOINT harness would
    see none of the rows this test created.
    """
    wrapped = _NoCloseSession(db_session)
    monkeypatch.setattr(comparison_tasks_mod, "_own_session", lambda: wrapped)
    return wrapped


def _create(client: TestClient, **overrides) -> dict:
    body = {"problem": _PROBLEM, "solver_names": ["scip", "highs"]}
    body.update(overrides)
    response = client.post(_URL, json=body)
    assert response.status_code == 202, response.text
    return response.json()


def _rows_by_solver(detail: dict) -> dict[str, dict]:
    return {row["solver_name"]: row for row in detail["results"]}


# ──────────────────────────────────────────────────────────────
# Creating
# ──────────────────────────────────────────────────────────────


# CONTRACT-TEST: a comparison is ONE task on the single-slot comparison queue.
# Fanning it out to the per-solver queues would let two solvers share a CPU and
# every second in the table would stop meaning anything.
def test_a_comparison_is_one_task_on_the_comparison_queue(
    authenticated_client: TestClient,
    captured_dispatch: list[dict],
) -> None:
    _create(authenticated_client)

    assert len(captured_dispatch) == 1
    assert captured_dispatch[0]["queue"] == "solve_compare"
    assert captured_dispatch[0]["kwargs"]["comparison_id"].startswith("cmp_")


# CONTRACT-TEST: every solver receives the same time limit, gap and thread count.
# A table whose columns ran on different terms compares settings, not solvers.
def test_every_solver_receives_identical_settings(
    authenticated_client: TestClient,
    db_session: Session,
    captured_dispatch: list[dict],
) -> None:
    detail = _create(
        authenticated_client,
        settings={"time_limit_seconds": 12, "gap_tolerance": 0.01},
    )

    assert detail["settings"] == {
        "time_limit_seconds": 12.0,
        "gap_tolerance": 0.01,
        "threads": DEFAULT_COMPARISON_THREADS,
    }
    children = (
        db_session.query(ModelExecution).filter(ModelExecution.comparison_id == detail["id"]).all()
    )
    assert len(children) == 2
    for child in children:
        options = child.input_data["options"]
        assert options["time_limit_seconds"] == 12.0
        assert options["gap_tolerance"] == 0.01
        assert options["threads"] == DEFAULT_COMPARISON_THREADS
        # Chatter costs time, and one solver logging while another does not
        # would land in the seconds column.
        assert options["verbose"] is False


# CONTRACT-TEST: the thread count is the platform's to set, never the caller's.
# HiGHS sizes one scheduler per worker process on its first solve, so a
# per-request count could not be honoured on the second comparison and would
# silently produce a failed column instead.
def test_the_caller_cannot_choose_the_thread_count(
    authenticated_client: TestClient, captured_dispatch: list[dict]
) -> None:
    detail = _create(
        authenticated_client,
        solver_names=["scip"],
        settings={"time_limit_seconds": 30, "gap_tolerance": 0.001, "threads": 8},
    )
    assert detail["settings"]["threads"] == DEFAULT_COMPARISON_THREADS


# CONTRACT-TEST: a solver that cannot run gets a ROW with a reason, never a
# missing row. A blank cell in a comparison is read as zero.
def test_a_solver_that_cannot_run_still_gets_a_row_with_a_reason(
    authenticated_client: TestClient,
    captured_dispatch: list[dict],
) -> None:
    detail = _create(authenticated_client, solver_names=["scip", "hexaly", "nosuchsolver"])

    rows = _rows_by_solver(detail)
    assert set(rows) == {"scip", "hexaly", "nosuchsolver"}

    # Hexaly needs its own image and licence; the comparison worker runs the
    # base image, so it can never take part.
    assert rows["hexaly"]["solver_status"] == "unsupported"
    assert rows["hexaly"]["unsupported_reason"] == "not_available"
    assert rows["hexaly"]["error_message"]

    assert rows["nosuchsolver"]["solver_status"] == "unsupported"
    assert rows["nosuchsolver"]["unsupported_reason"] == "not_registered"

    # And the one that can run is still queued.
    assert rows["scip"]["status"] == "pending"
    assert len(captured_dispatch) == 1


def test_a_comparison_no_solver_can_run_is_refused(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        _URL, json={"problem": _PROBLEM, "solver_names": ["hexaly"]}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "no_solver_can_run_this_model"


def test_the_same_solver_twice_is_one_column(
    authenticated_client: TestClient, captured_dispatch: list[dict]
) -> None:
    detail = _create(authenticated_client, solver_names=["scip", "SCIP", " scip "])
    assert [row["solver_name"] for row in detail["results"]] == ["scip"]


def test_a_source_must_be_given_and_only_one(authenticated_client: TestClient) -> None:
    neither = authenticated_client.post(_URL, json={"solver_names": ["scip"]})
    assert neither.status_code == 422

    both = authenticated_client.post(
        _URL,
        json={"problem": _PROBLEM, "project_id": "prj_nope", "solver_names": ["scip"]},
    )
    assert both.status_code == 422


# ──────────────────────────────────────────────────────────────
# Running
# ──────────────────────────────────────────────────────────────


# CONTRACT-TEST: the task solves every runnable column and leaves each one with a
# verdict. A column left pending is a comparison nobody can finish reading.
def test_the_task_solves_every_runnable_column(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    captured_dispatch: list[dict],
    task_runs_on_the_test_session,
) -> None:
    created = _create(authenticated_client, solver_names=["scip", "highs", "hexaly"])

    outcome = comparison_tasks_mod.run_solver_comparison.apply(
        kwargs={
            "comparison_id": created["id"],
            "organization_id": test_organization.id,
        }
    ).get()

    assert outcome["status"] == "success"
    assert outcome["solved"] == 2  # hexaly never ran

    detail = authenticated_client.get(f"{_URL}/{created['id']}").json()
    assert detail["status"] == ComparisonStatus.COMPLETED.value
    rows = _rows_by_solver(detail)

    for name in ("scip", "highs"):
        assert rows[name]["status"] == "completed", rows[name]
        assert rows[name]["solver_status"] == "optimal", rows[name]
        assert rows[name]["objective_value"] == pytest.approx(24.0)
        # Wall time is recorded even when the solve is instant: the column is
        # the wait, and a missing number would read as "not measured".
        assert rows[name]["wall_time_ms"] is not None
    assert rows["hexaly"]["solver_status"] == "unsupported"

    # The machine the seconds came from travels with them.
    assert detail["machine_note"]

    # CONTRACT: so does the version of each solver that produced them. A table
    # stored today cannot be reproduced or explained once the images have been
    # rebuilt, and seconds measured against one version say nothing about
    # another. A solver that ran must therefore name its own build.
    for name in ("scip", "highs"):
        assert rows[name]["solver_version"], f"{name} recorded no version"
    # A solver that never ran has no version to record, and inventing one would
    # claim a build took part in a comparison it sat out.
    assert rows["hexaly"]["solver_version"] is None


# CONTRACT-TEST: two solvers that both reach the optimum must be reported as
# agreeing. Silence here would leave a reader comparing numbers by eye.
def test_agreement_is_reported_for_the_columns_that_finished(
    authenticated_client: TestClient,
    test_organization: Organization,
    captured_dispatch: list[dict],
    task_runs_on_the_test_session,
) -> None:
    created = _create(authenticated_client, solver_names=["scip", "highs"])
    comparison_tasks_mod.run_solver_comparison.apply(
        kwargs={"comparison_id": created["id"], "organization_id": test_organization.id}
    ).get()

    detail = authenticated_client.get(f"{_URL}/{created['id']}").json()
    assert [(r["solver_status"], r["error_message"]) for r in detail["results"]] == [
        ("optimal", None),
        ("optimal", None),
    ]
    agreement = detail["agreement"]
    assert agreement is not None
    assert sorted(agreement["compared_solvers"]) == ["highs", "scip"]
    assert agreement["objectives_agree"] is True


def test_an_integer_model_runs_on_both_solvers(
    authenticated_client: TestClient,
    test_organization: Organization,
    captured_dispatch: list[dict],
    task_runs_on_the_test_session,
) -> None:
    created = _create(
        authenticated_client, problem=_INTEGER_PROBLEM, solver_names=["scip", "highs"]
    )
    comparison_tasks_mod.run_solver_comparison.apply(
        kwargs={"comparison_id": created["id"], "organization_id": test_organization.id}
    ).get()

    rows = _rows_by_solver(authenticated_client.get(f"{_URL}/{created['id']}").json())
    for name in ("scip", "highs"):
        assert rows[name]["solver_status"] == "optimal", rows[name]
        assert rows[name]["unsupported_reason"] is None


# ──────────────────────────────────────────────────────────────
# Cancelling
# ──────────────────────────────────────────────────────────────


# CONTRACT-TEST: cancelling marks the columns that never ran, and the task stops
# before the next solve rather than spending a worker slot on a dead comparison.
def test_cancelling_stops_the_run_and_marks_the_untouched_columns(
    authenticated_client: TestClient,
    test_organization: Organization,
    captured_dispatch: list[dict],
    task_runs_on_the_test_session,
) -> None:
    created = _create(authenticated_client, solver_names=["scip", "highs"])

    cancelled = authenticated_client.post(f"{_URL}/{created['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == ComparisonStatus.CANCELLED.value

    outcome = comparison_tasks_mod.run_solver_comparison.apply(
        kwargs={"comparison_id": created["id"], "organization_id": test_organization.id}
    ).get()
    assert outcome["status"] == "cancelled"
    assert outcome["solved"] == 0

    rows = _rows_by_solver(authenticated_client.get(f"{_URL}/{created['id']}").json())
    assert {row["status"] for row in rows.values()} == {"cancelled"}


# CONTRACT-TEST: a comparison the user stopped keeps saying stopped
# The solve already inside a solver cannot be interrupted, so the worker finishes
# it, finds every remaining column already cancelled and reaches the end of its
# loop. It used to write COMPLETED there, over the cancel — a run the user
# stopped ended up labelled "Finished" over a table three quarters of which said
# "Stopped".
def test_a_comparison_cancelled_mid_solve_is_not_relabelled_as_finished(
    authenticated_client: TestClient,
    test_organization: Organization,
    captured_dispatch: list[dict],
    task_runs_on_the_test_session,
    monkeypatch,
) -> None:
    created = _create(authenticated_client, solver_names=["scip", "highs"])
    real_run_one = comparison_tasks_mod._run_one

    def cancel_while_the_first_column_is_in_flight(db, execution, problem, solver_name):
        real_run_one(db, execution, problem, solver_name)
        # What the user's click does: cancel the parent and close the columns
        # that never started. The one just finished keeps its real verdict.
        comparison = db.query(SolverComparison).filter(SolverComparison.id == created["id"]).one()
        comparison_setup.cancel_comparison_rows(db, comparison)
        db.commit()

    monkeypatch.setattr(
        comparison_tasks_mod, "_run_one", cancel_while_the_first_column_is_in_flight
    )

    comparison_tasks_mod.run_solver_comparison.apply(
        kwargs={"comparison_id": created["id"], "organization_id": test_organization.id}
    ).get()

    detail = authenticated_client.get(f"{_URL}/{created['id']}").json()
    assert detail["status"] == ComparisonStatus.CANCELLED.value
    # The API's cancel does not stamp it, so the worker is the only one who can.
    assert detail["completed_at"] is not None
    rows = _rows_by_solver(detail)
    assert rows["scip"]["status"] == ExecutionStatus.COMPLETED.value
    assert rows["highs"]["status"] == ExecutionStatus.CANCELLED.value


def test_cancelling_a_finished_comparison_changes_nothing(
    authenticated_client: TestClient,
    test_organization: Organization,
    captured_dispatch: list[dict],
    task_runs_on_the_test_session,
) -> None:
    created = _create(authenticated_client, solver_names=["scip"])
    comparison_tasks_mod.run_solver_comparison.apply(
        kwargs={"comparison_id": created["id"], "organization_id": test_organization.id}
    ).get()

    response = authenticated_client.post(f"{_URL}/{created['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == ComparisonStatus.COMPLETED.value


# ──────────────────────────────────────────────────────────────
# Quota
# ──────────────────────────────────────────────────────────────


# CONTRACT-TEST: a comparison the quota cannot cover is refused WHOLE. Running
# the affordable half would invite a conclusion the missing half might contradict.
def test_a_comparison_the_quota_cannot_cover_is_refused_whole(
    authenticated_client: TestClient,
    db_session: Session,
    real_rate_limiter,
    monkeypatch,
) -> None:
    limits = dict(comparison_setup.PSS.get_instance_limits(db_session))
    limits["max_daily_solves"] = 1
    monkeypatch.setattr(comparison_setup.PSS, "get_instance_limits", lambda _db: limits)

    response = authenticated_client.post(
        _URL, json={"problem": _PROBLEM, "solver_names": ["scip", "highs"]}
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == "daily_solve_quota_exceeded"
    # CONTRACT-TEST: the refusal is written for whoever hit the limit.
    #
    # It used to read "…ask an administrator to raise the limit in Settings
    # (instance_max_daily_solves; 0 means unlimited)" — a plain member being
    # sent to edit a setting they cannot see, and told it in English on a page
    # in their own language. The key still travels, in `setting_key`, where an
    # operator or an API client reads it.
    assert "instance_max_daily_solves" not in detail["message"]
    assert "Settings" not in detail["message"]
    assert detail["setting_key"] == "instance_max_daily_solves"
    # "This comparison needs 1 solves" was the other half of it.
    assert "1 solves" not in detail["message"]
    # Nothing was written: no half-built comparison left behind.
    assert db_session.query(SolverComparison).count() == 0


# CONTRACT-TEST (D-30): a refused comparison costs nothing. The quota used to be
# charged one solver at a time, so a two-solver comparison refused on its second
# had already spent the first — and a matrix could drain a day's quota on a
# table that never ran.
def test_a_refused_comparison_leaves_the_quota_untouched(
    authenticated_client: TestClient,
    db_session: Session,
    real_rate_limiter,
    captured_dispatch,
    monkeypatch,
) -> None:
    limits = dict(comparison_setup.PSS.get_instance_limits(db_session))
    limits["max_daily_solves"] = 1
    monkeypatch.setattr(comparison_setup.PSS, "get_instance_limits", lambda _db: limits)

    refused = authenticated_client.post(
        _URL, json={"problem": _PROBLEM, "solver_names": ["scip", "highs"]}
    )
    assert refused.status_code == 403
    # The one slot the day had is still there for a comparison that fits.
    assert refused.json()["detail"]["message"].startswith("This comparison needs 2 solves and 1 ")

    accepted = authenticated_client.post(_URL, json={"problem": _PROBLEM, "solver_names": ["scip"]})
    assert accepted.status_code in (200, 202), accepted.text


# CONTRACT-TEST: a comparison that could not be queued closes its columns. They
# are written before the enqueue, so without this they sit pending under a failed
# parent until the reaper's next sweep, and the page polls for the whole quarter
# of an hour.
def test_a_comparison_that_cannot_be_queued_closes_its_columns(
    authenticated_client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    def _broker_is_down(*_args, **_kwargs):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(comparison_tasks_mod.run_solver_comparison, "apply_async", _broker_is_down)

    response = authenticated_client.post(
        _URL, json={"problem": _PROBLEM, "solver_names": ["scip", "highs"]}
    )

    assert response.status_code == 503, response.text
    db_session.expire_all()
    comparison = db_session.query(SolverComparison).one()
    assert comparison.status == ComparisonStatus.FAILED.value
    for execution in db_session.query(ModelExecution).all():
        assert execution.status == ExecutionStatus.CANCELLED.value


# ──────────────────────────────────────────────────────────────
# Access
# ──────────────────────────────────────────────────────────────


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.post(_URL, json={"problem": _PROBLEM, "solver_names": ["scip"]}).status_code in (
        401,
        403,
    )
    assert client.get(_URL).status_code in (401, 403)


# CONTRACT-TEST: a comparison is org-scoped. Another organization's id must read
# as absent, not as forbidden-but-there.
def test_another_organizations_comparison_is_not_found(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization_2: Organization,
) -> None:
    foreign = SolverComparison(
        id=generate_id("cmp_"),
        organization_id=test_organization_2.id,
        problem_data=_PROBLEM,
        problem_name="not yours",
        time_limit_seconds=60.0,
        gap_tolerance=0.0001,
        threads=1,
        solver_names=["scip"],
        status=ComparisonStatus.PENDING.value,
        created_at=utcnow(),
    )
    db_session.add(foreign)
    db_session.commit()

    assert authenticated_client.get(f"{_URL}/{foreign.id}").status_code == 404
    assert authenticated_client.post(f"{_URL}/{foreign.id}/cancel").status_code == 404
    assert foreign.id not in {
        row["id"] for row in authenticated_client.get(_URL).json()["comparisons"]
    }


def test_the_history_lists_this_organizations_comparisons_newest_first(
    authenticated_client: TestClient,
    captured_dispatch: list[dict],
) -> None:
    first = _create(authenticated_client, solver_names=["scip"])
    second = _create(authenticated_client, solver_names=["highs"])

    listing = authenticated_client.get(_URL).json()
    ids = [row["id"] for row in listing["comparisons"]]
    assert ids[:2] == [second["id"], first["id"]]
    assert listing["total"] >= 2
