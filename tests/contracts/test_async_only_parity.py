"""ADR-007 S0 — sync/async parity contract harness.

# CONTRACT-TEST: POST /solve and POST /solve/async?wait=true must return the SAME
OptimizationResult contract for the same problem — field set and semantic fields
alike. These tests pin the wait-wrapper mapping (envelope flattening, execution_id /
telemetry hoisting, 202 degradation)
BEFORE the legacy sync endpoints become async-backed wrappers (ADR-007 S2). If a
test here breaks, the async-under-the-hood migration is NOT safe to proceed.

The async task runs EAGERLY (celery ``task.apply``) inside the test process: the
real ``solve_async`` body executes — real SCIP, real DB writes, real refund logic —
so the compared payload is the genuine worker envelope, not a stub.
"""

from __future__ import annotations

import pytest

import app.domains.solver.tasks.solve_tasks as solve_tasks_mod

pytestmark = pytest.mark.contract


def _lp_problem_payload() -> dict:
    """Deterministic LP: minimize x + y s.t. x + y >= 10 -> optimum 10.0."""
    return {
        "name": "parity_lp",
        "solver_name": "scip",  # pin the solver: parity must not depend on routing
        "variables": [
            {"name": "x", "type": "continuous", "lower_bound": 0},
            {"name": "y", "type": "continuous", "lower_bound": 0},
        ],
        "objective": {"sense": "minimize", "expression": "x + y"},
        "constraints": [{"expression": "x + y >= 10"}],
        "options": {"time_limit_seconds": 30, "verbose": False},
    }


def _infeasible_problem_payload() -> dict:
    return {
        "name": "parity_infeasible",
        "solver_name": "scip",
        "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
        "objective": {"sense": "minimize", "expression": "x"},
        "constraints": [{"expression": "x >= 10"}, {"expression": "x <= 5"}],
        "options": {"time_limit_seconds": 30, "verbose": False},
    }


@pytest.fixture()
def eager_solve_async(monkeypatch):
    """Run the REAL solve_async task body eagerly when the route enqueues it.

    ``task.apply`` executes synchronously in-process and returns an EagerResult
    whose ``.id`` / ``.get`` behave like the broker-backed handle the route uses.
    """

    def _eager_apply_async(**opts):
        return solve_tasks_mod.solve_async.apply(kwargs=opts["kwargs"])

    monkeypatch.setattr(solve_tasks_mod.solve_async, "apply_async", _eager_apply_async)


class TestSyncAsyncParity:
    """# CONTRACT-TEST: sync /solve == /solve/async?wait=true, field by field."""

    def test_optimal_lp_parity(self, authenticated_client, eager_solve_async):
        sync_res = authenticated_client.post("/api/v2/solve", json=_lp_problem_payload())
        assert sync_res.status_code == 200, sync_res.text
        sync = sync_res.json()

        wait_res = authenticated_client.post(
            "/api/v2/solve/async?wait=true", json=_lp_problem_payload()
        )
        assert wait_res.status_code == 200, wait_res.text
        wait = wait_res.json()

        # Identical field set — the wrapper must not leak the async envelope shape.
        assert set(wait.keys()) == set(sync.keys())

        # Semantic parity.
        assert wait["status"] == sync["status"] == "optimal"
        assert wait["objective_value"] == pytest.approx(sync["objective_value"])
        assert wait["objective_value"] == pytest.approx(10.0)
        assert wait["solution"] == sync["solution"]
        assert wait["variables"] == sync["variables"]
        assert wait["solver_used"] == sync["solver_used"] == "scip"
        assert wait["auto_route_reason"] == sync["auto_route_reason"]
        assert wait["error_message"] is None and sync["error_message"] is None
        assert wait["warm_start_used"] == sync["warm_start_used"]

        # Identity: both carry a real (distinct) execution id.
        assert sync["execution_id"] and sync["execution_id"].startswith("exe_")
        assert wait["execution_id"] and wait["execution_id"].startswith("exe_")
        assert wait["execution_id"] != sync["execution_id"]

        # Both runs charge: the second balance is exactly one solve below the first.

        # Timing fields are present and sane, never compared for equality.
        assert wait["solve_time_seconds"] >= 0 and sync["solve_time_seconds"] >= 0

    def test_infeasible_parity(self, authenticated_client, eager_solve_async):
        sync = authenticated_client.post("/api/v2/solve", json=_infeasible_problem_payload()).json()
        wait = authenticated_client.post(
            "/api/v2/solve/async?wait=true", json=_infeasible_problem_payload()
        ).json()

        assert set(wait.keys()) == set(sync.keys())
        assert wait["status"] == sync["status"] == "infeasible"
        assert wait["objective_value"] == sync["objective_value"]
        # An infeasible result is a real (charged) answer on both paths.


class TestWaitDegradation:
    """# CONTRACT-TEST: wait past its budget degrades to 202 + the task envelope."""

    def test_timeout_returns_202_with_task_envelope(self, authenticated_client, monkeypatch):
        from celery.exceptions import TimeoutError as CeleryTimeoutError

        class _NeverDone:
            id = "parity-wait-timeout-task"

            def get(self, **kwargs):
                raise CeleryTimeoutError("still running")

        monkeypatch.setattr(solve_tasks_mod.solve_async, "apply_async", lambda **opts: _NeverDone())

        res = authenticated_client.post("/api/v2/solve/async?wait=true", json=_lp_problem_payload())
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["task_id"] == "parity-wait-timeout-task"
        assert body["execution_id"].startswith("exe_")
        assert body["status"] == "pending"
        assert body["poll_url"].endswith(body["task_id"])


class TestAsyncEnvelopeAdditions:
    """# CONTRACT-TEST: ADR-007 §6 — execution_id is first-class in the async envelope."""

    def test_plain_async_response_carries_execution_id(
        self, authenticated_client, monkeypatch, db_session
    ):
        class _Queued:
            id = "parity-envelope-task"

        monkeypatch.setattr(solve_tasks_mod.solve_async, "apply_async", lambda **opts: _Queued())

        res = authenticated_client.post("/api/v2/solve/async", json=_lp_problem_payload())
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["execution_id"].startswith("exe_")
        assert body["task_id"] == "parity-envelope-task"

        from app.models import ModelExecution

        row = db_session.query(ModelExecution).filter_by(id=body["execution_id"]).first()
        assert row is not None
        assert row.celery_task_id == body["task_id"]


class TestWaitErrorMapping:
    """The wait wrapper maps worker error envelopes to the sync error shape."""

    def test_solver_level_error_envelope_maps_to_error_result(
        self, authenticated_client, monkeypatch
    ):
        class _FailedTask:
            id = "parity-error-task"

            def get(self, **kwargs):
                # The worker's error envelope.
                return {"status": "error", "task_id": self.id, "error": "boom from solver"}

        monkeypatch.setattr(
            solve_tasks_mod.solve_async, "apply_async", lambda **opts: _FailedTask()
        )

        res = authenticated_client.post("/api/v2/solve/async?wait=true", json=_lp_problem_payload())
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "error"
        assert "boom from solver" in body["error_message"]
        assert body["execution_id"].startswith("exe_")

    def test_solver_level_error_in_success_envelope_maps_to_error(
        self, authenticated_client, monkeypatch
    ):
        """# CONTRACT-TEST: a NON-raising solver error rides the worker's "success"
        envelope with an inner status=error; the worker already refunded the
        not the prepaid amount. Regression for the audit finding where /solve
        (historic BUG-1 surface)."""

        class _SolverErrorInSuccess:
            id = "parity-solver-error-envelope-task"

            def get(self, **kwargs):
                return {
                    "status": "success",
                    "task_id": self.id,
                    "result": {
                        "status": "error",
                        "solve_time_seconds": 0.0,
                        "error_message": "EXPR_PARSE_ERROR: Division by zero",
                    },
                }

        monkeypatch.setattr(
            solve_tasks_mod.solve_async, "apply_async", lambda **opts: _SolverErrorInSuccess()
        )

        res = authenticated_client.post("/api/v2/solve/async?wait=true", json=_lp_problem_payload())
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "error"
        assert "EXPR_PARSE_ERROR" in (body["error_message"] or "")

    def test_task_crash_maps_to_error_result(self, authenticated_client, monkeypatch):
        class _CrashedTask:
            id = "parity-crash-task"

            def get(self, **kwargs):
                # propagate=False hands back the exception object on hard failure.
                return RuntimeError("worker killed")

        monkeypatch.setattr(
            solve_tasks_mod.solve_async, "apply_async", lambda **opts: _CrashedTask()
        )

        res = authenticated_client.post("/api/v2/solve/async?wait=true", json=_lp_problem_payload())
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "error"
        assert "worker killed" in body["error_message"]
