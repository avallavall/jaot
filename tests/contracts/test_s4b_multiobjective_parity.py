"""ADR-007 S4b — parity contracts for ``POST /solve/multi-objective`` now riding a
dedicated async task (``solve_multi_objective_async``).

# CONTRACT-TEST: the multi-objective endpoint keeps its synchronous
``MultiObjectiveResult`` contract (happy path + infeasible-stays-charged are pinned
in ``test_multi_objective_integration.py``), degrades to 202 past the wait budget,
maps a worker error to HTTP 422 (a Pareto front has no error status), and pre-pays a
pending ModelExecution row tagged ``scip``. If these break, the S4b conversion changed
the observable contract.

The task runs EAGERLY via the autouse ``eager_solve_async_pipeline`` fixture (real
SCIP, real DB, real refunds).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.domains.solver.tasks.solve_tasks as solve_tasks_mod
from app.models import ModelExecution, Organization

pytestmark = pytest.mark.contract


def _body(n_points: int = 3, mode: str = "epsilon") -> dict:
    return {
        "problem": {
            "name": "s4b-mo",
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 100},
                {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 100},
            ],
            "constraints": [{"expression": "x + y >= 10"}],
            "objective": {"expression": "x", "sense": "minimize"},
            "options": {"time_limit_seconds": 30},
        },
        "config": {
            "mode": mode,
            "objectives": [
                {"expression": "x", "sense": "minimize"},
                {"expression": "y", "sense": "minimize"},
            ],
            "n_points": n_points,
        },
    }


def _fund(db: Session, org: Organization) -> None:
    db.query(Organization).filter(Organization.id == org.id).update({"credits_balance": 1_000_000})
    db.commit()


class TestMultiObjectiveProvenance:
    # CONTRACT-TEST: multi-objective solves leave a navigable execution row in history
    # (re-encodes the invariant from the deleted sync-orchestrator test, ADR-007 S6). The
    # enqueue pre-pays a pending ModelExecution row tagged scip so the run is durable +
    # shows up in history from the start (parity with solve_async).
    def test_pending_row_persisted_with_scip_solver(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        _fund(db_session, test_organization)
        res = authenticated_client.post(
            "/api/v2/solve/multi-objective?origin=visual_builder", json=_body()
        )
        assert res.status_code == 200, res.text
        execution_id = res.json().get("execution_id") or None
        # The pending row is written by the enqueue in the request session (visible),
        # even though the eager worker's own-session completion write no-ops here.
        row = (
            db_session.query(ModelExecution)
            .filter(ModelExecution.organization_id == test_organization.id)
            .order_by(ModelExecution.created_at.desc())
            .first()
        )
        assert row is not None
        assert row.solver_name == "scip"
        assert row.is_async is True
        assert row.origin == "visual_builder"
        if execution_id:
            assert row.id == execution_id


class TestMultiObjectiveWaitContract:
    # CONTRACT-TEST: a slow multi-objective solve degrades to 202 + the task envelope.
    def test_degrades_to_202(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        monkeypatch,
    ):
        from celery.exceptions import TimeoutError as CeleryTimeoutError

        _fund(db_session, test_organization)

        class _NeverDone:
            id = "s4b-wait-timeout-task"

            def get(self, **kwargs):
                raise CeleryTimeoutError("still running")

        monkeypatch.setattr(
            solve_tasks_mod.solve_multi_objective_async,
            "apply_async",
            lambda **opts: _NeverDone(),
        )

        res = authenticated_client.post("/api/v2/solve/multi-objective", json=_body())
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["task_id"] == "s4b-wait-timeout-task"
        assert body["execution_id"].startswith("exe_")
        assert body["status"] == "pending"
        assert body["poll_url"].endswith(body["task_id"])

    # CONTRACT-TEST: multi-objective has no error result shape, so a worker error
    # envelope (prepay already refunded by the worker) surfaces as HTTP 422.
    def test_worker_error_maps_to_422(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        monkeypatch,
    ):
        _fund(db_session, test_organization)

        class _FailedTask:
            id = "s4b-error-task"

            def get(self, **kwargs):
                return {"status": "error", "task_id": self.id, "error": "scalarization blew up"}

        monkeypatch.setattr(
            solve_tasks_mod.solve_multi_objective_async,
            "apply_async",
            lambda **opts: _FailedTask(),
        )

        res = authenticated_client.post("/api/v2/solve/multi-objective", json=_body())
        assert res.status_code == 422, res.text
        assert "scalarization blew up" in res.text
