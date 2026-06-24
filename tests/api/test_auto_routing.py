"""Phase 7.4 / D-13 / INT-01 — auto-routing observability + DB persistence.

Validation IDs: V-12 (structured log), V-13 (counter), V-14 (DB col),
V-15 (async hoist).
"""

from __future__ import annotations

import logging

import pytest


def _quadratic_problem_payload(*, solver_name: str = "auto") -> dict:
    """Minimal quadratic problem payload (forces auto → hexaly branch).

    Note: /api/v2/solve takes OptimizationProblem fields at the top level
    (not nested under a "problem" key). solver_name is also top-level.
    """
    return {
        "name": "qp_for_auto_route_test",
        "variables": [{"name": "x", "type": "continuous", "lower_bound": 0.0, "upper_bound": 10.0}],
        "constraints": [{"name": "c1", "expression": "x >= 1"}],
        "objective": {"expression": "x*x", "sense": "minimize"},
        "options": {"time_limit_seconds": 10.0, "verbose": False},
        "solver_name": solver_name,
    }


def test_structured_log(authenticated_client, caplog: pytest.LogCaptureFixture) -> None:
    """V-12: 'auto_route_decision' log emitted on auto-routed sync solve, with
    fields {solver_used, auto_route_reason, execution_id, organization_id,
    fallback_triggered}. (Phase 7.4 / Plan 05 Task 3)"""
    caplog.set_level(logging.INFO)
    response = authenticated_client.post("/api/v2/solve", json=_quadratic_problem_payload())
    assert response.status_code == 200
    matches = [r for r in caplog.records if r.message == "auto_route_decision"]
    assert matches, "structured log auto_route_decision not emitted"
    extra = matches[0].__dict__
    for key in (
        "solver_used",
        "auto_route_reason",
        "execution_id",
        "organization_id",
        "fallback_triggered",
    ):
        assert key in extra


def test_counter_increments(authenticated_client) -> None:
    """V-13: Counter jaot_solver_auto_route_decisions_total increments per route.
    (Phase 7.4 / Plan 05 Task 3)

    Checks the two routes that a quadratic problem can take depending on
    Hexaly worker availability:
      - Hexaly available   → solver_used="hexaly",  reason="quadratic_routed_to_hexaly"
      - Hexaly unavailable → solver_used="scip",    reason="hexaly_unavailable_fallback"

    Both are valid at test time (CI has no Hexaly worker; local dev may or may
    not have one). The assertion is that the appropriate counter increments by
    exactly 1 — not which specific counter.
    """
    from app.shared.core.prometheus_metrics import SOLVER_AUTO_ROUTE_DECISIONS

    before_hexaly = SOLVER_AUTO_ROUTE_DECISIONS.labels(
        solver_used="hexaly", reason="quadratic_routed_to_hexaly"
    )._value.get()
    before_scip_fallback = SOLVER_AUTO_ROUTE_DECISIONS.labels(
        solver_used="scip", reason="hexaly_unavailable_fallback"
    )._value.get()
    before_total = before_hexaly + before_scip_fallback

    response = authenticated_client.post("/api/v2/solve", json=_quadratic_problem_payload())
    assert response.status_code == 200

    after_hexaly = SOLVER_AUTO_ROUTE_DECISIONS.labels(
        solver_used="hexaly", reason="quadratic_routed_to_hexaly"
    )._value.get()
    after_scip_fallback = SOLVER_AUTO_ROUTE_DECISIONS.labels(
        solver_used="scip", reason="hexaly_unavailable_fallback"
    )._value.get()
    after_total = after_hexaly + after_scip_fallback

    assert after_total == before_total + 1, (
        f"Expected SOLVER_AUTO_ROUTE_DECISIONS to increment by 1 "
        f"(hexaly: {before_hexaly}→{after_hexaly}, "
        f"scip_fallback: {before_scip_fallback}→{after_scip_fallback})"
    )


def test_reason_persisted(authenticated_client, db_session) -> None:
    """V-14: ModelExecution.auto_route_reason is persisted (String(64), nullable).
    (Phase 7.4 / Plan 05 Task 3 + Plan 09 Task 1)"""
    response = authenticated_client.post("/api/v2/solve", json=_quadratic_problem_payload())
    assert response.status_code == 200
    execution_id = response.json()["execution_id"]

    from app.models.optimization_model import ModelExecution

    row = db_session.query(ModelExecution).filter_by(id=execution_id).first()
    assert row is not None
    assert row.auto_route_reason in (
        "quadratic_routed_to_hexaly",
        "hexaly_unavailable_fallback",
    )


def test_async_hoist(authenticated_client, monkeypatch) -> None:
    """V-15: GET /api/v2/solve/async/{task_id} hoists solver_used,
    auto_route_reason, warning to top-level of response.
    (Phase 7.4 / Plan 05 Task 3)

    CI has no RabbitMQ broker (CELERY_BROKER_URL=""), so apply_async always
    raises ConnectionRefusedError in CI — returning 503 before the test can
    reach the GET hoist assertion.  V-15's purpose is to verify the GET
    response *shape*, not end-to-end Celery integration (that is Plan 12).

    Fix strategy (Path A — broker-independent):
      1. Stub solve_async.apply_async so the POST succeeds and creates the
         ModelExecution row with celery_task_id=FAKE_TASK_ID.
      2. Stub celery.result.AsyncResult so the GET handler sees state=SUCCESS
         with auto-route telemetry in the result dict — exercising the hoist
         logic under test.
    """
    _FAKE_TASK_ID = "test-task-v15-async-hoist"
    _TELEMETRY = {
        "solver_used": "scip",
        "auto_route_reason": "hexaly_unavailable_fallback",
        "status": "completed",
        "result": {"status": "success", "objective_value": 1.0},
    }

    # --- stub 1: apply_async --------------------------------------------------
    # The POST handler does a local import:
    #   from app.domains.solver.tasks.solve_tasks import solve_async
    # and then calls solve_async.apply_async(...).
    # We patch the attribute on the already-imported task object so the local
    # import inside the handler picks up the stub.

    import app.domains.solver.tasks.solve_tasks as _solve_tasks_mod

    class _FakeAsyncResult:
        """Minimal stand-in for celery.result.AsyncResult returned by apply_async."""

        def __init__(self, task_id: str) -> None:
            self.id = task_id

    def _fake_apply_async(**kwargs: object) -> _FakeAsyncResult:  # noqa: ARG001
        return _FakeAsyncResult(_FAKE_TASK_ID)

    monkeypatch.setattr(_solve_tasks_mod.solve_async, "apply_async", _fake_apply_async)

    # --- stub 2: AsyncResult (GET handler) ------------------------------------
    # The GET handler does:
    #   from celery.result import AsyncResult
    #   result = AsyncResult(task_id, app=celery_app)
    # We replace the class in celery.result so the local import resolves to
    # our fake, giving state=SUCCESS with telemetry in result.result.

    import celery.result as _celery_result_mod

    class _FakeCeleryAsyncResult:
        """Minimal AsyncResult stub that reports a completed solve with telemetry."""

        def __init__(self, task_id: str, **kwargs: object) -> None:  # noqa: ARG002
            self._task_id = task_id

        @property
        def state(self) -> str:
            return "SUCCESS"

        @property
        def result(self) -> dict:
            return _TELEMETRY

    monkeypatch.setattr(_celery_result_mod, "AsyncResult", _FakeCeleryAsyncResult)

    # --- run the test ---------------------------------------------------------
    response = authenticated_client.post("/api/v2/solve/async", json=_quadratic_problem_payload())
    assert response.status_code in (200, 202), (
        f"POST /async returned {response.status_code}: {response.text}"
    )
    task_id = response.json()["task_id"]
    assert task_id == _FAKE_TASK_ID, f"Expected fake task id, got {task_id!r}"

    # Poll once — assertion is on shape, not on completion.
    poll = authenticated_client.get(f"/api/v2/solve/async/{task_id}")
    assert poll.status_code == 200, f"GET /async/{task_id} returned {poll.status_code}: {poll.text}"
    body = poll.json()
    for key in ("solver_used", "auto_route_reason"):
        assert key in body, f"async response missing top-level {key!r}"
