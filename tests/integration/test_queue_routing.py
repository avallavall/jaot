"""End-to-end integration tests for INF-05 queue routing.

Covers the full producer -> routing -> consumer-guard pipeline:

1. SCIP route: POST /solve/async with solver_name='scip' -> queue='solve_scip'
2. HiGHS route: POST /solve/async with solver_name='highs' -> queue='solve_highs'
3. Unknown solver: POST /solve/async with solver_name='gurobi' -> HTTP 422,
   pre-paid credits refunded, no broker/env leak in error message.
4. Manual misroute: direct invocation of solve_async.run() with
   SOLVER_QUEUE=solve_scip and solver_name='highs' -> consumer-side
   guard raises SolverQueueMismatchError, caught by outer try/except,
   returns {"status": "error", ...}.

The integration tests do NOT require a live broker — producer-side
apply_async is stubbed (mirroring plan 06-02 TestProducerRoutingWiring
pattern) and consumer-side guard is exercised via ``.run()`` (Celery's
"call the wrapped function directly" API).

Related tests:
- tests/unit/test_queue_routing.py — pure routing helper (plan 06-01)
- tests/unit/test_solve_tasks_queue_guard.py — unit coverage of the
  _assert_queue_match helper (plan 06-03 RED / GREEN)
- tests/integration/test_celery_integration.py::TestProducerRoutingWiring
  — 5 producer-side wiring tests (plan 06-02)
"""

from __future__ import annotations

import pytest


class _FakeAsyncResult:
    """Minimal stand-in for Celery's AsyncResult — only ``.id`` is read."""

    id = "fake_task_id_routing"


def _make_small_problem(
    name: str,
    solver_name: str | None = None,
) -> dict[str, object]:
    """Build a minimal valid OptimizationProblem payload for the API."""
    payload: dict[str, object] = {
        "name": name,
        "description": f"INF-05 routing test: {name}",
        "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
        "variables": [
            {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
            {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
        ],
        "constraints": [
            {"name": "c1", "expression": "x + y <= 15"},
        ],
        "options": {"time_limit_seconds": 30},
    }
    if solver_name is not None:
        payload["solver_name"] = solver_name
    return payload


@pytest.mark.integration
class TestQueueRoutingE2E:
    """INF-05 end-to-end coverage: producer routing + consumer guard."""

    def test_scip_routes_to_solve_scip_queue(
        self,
        authenticated_client,
        test_organization,
        db_session,
        monkeypatch,
    ) -> None:
        """POST /solve/async with solver_name='scip' -> queue='solve_scip'.

        Producer resolves the queue via resolve_queue(solver_name) and
        passes it to apply_async. The worker that drains solve_scip is
        guaranteed to handle SCIP tasks only.
        """
        captured: dict[str, object] = {}

        def _capture_apply_async(*_args: object, **kwargs: object) -> _FakeAsyncResult:
            captured.update(kwargs)
            return _FakeAsyncResult()

        from app.domains.solver.tasks import solve_tasks

        monkeypatch.setattr(solve_tasks.solve_async, "apply_async", _capture_apply_async)

        small_problem = _make_small_problem("inf05_scip", solver_name="scip")
        resp = authenticated_client.post("/api/v2/solve/async", json=small_problem)

        assert resp.status_code == 200, resp.text
        assert captured.get("queue") == "solve_scip", f"expected queue=solve_scip, got {captured!r}"

    def test_highs_routes_to_solve_highs_queue(
        self,
        authenticated_client,
        test_organization,
        db_session,
        monkeypatch,
    ) -> None:
        """POST /solve/async with solver_name='highs' -> queue='solve_highs'.

        Mirrors the SCIP test for the HiGHS branch.
        """
        captured: dict[str, object] = {}

        def _capture_apply_async(*_args: object, **kwargs: object) -> _FakeAsyncResult:
            captured.update(kwargs)
            return _FakeAsyncResult()

        from app.domains.solver.tasks import solve_tasks

        monkeypatch.setattr(solve_tasks.solve_async, "apply_async", _capture_apply_async)

        small_problem = _make_small_problem("inf05_highs", solver_name="highs")
        resp = authenticated_client.post("/api/v2/solve/async", json=small_problem)

        assert resp.status_code == 200, resp.text
        assert captured.get("queue") == "solve_highs", (
            f"expected queue=solve_highs, got {captured!r}"
        )

    def test_unknown_solver_returns_422_and_refunds(
        self,
        authenticated_client,
        test_organization,
        db_session,
        monkeypatch,
    ) -> None:
        """Unknown solver_name -> HTTP 422, balance restored, no broker leak.

        The producer calls resolve_queue(solver_name) before apply_async;
        a KeyError becomes SolverNotFoundError which the endpoint maps to
        HTTP 422. The pre-paid credits are refunded so an invalid
        submission never leaves the user charged (plan 06-02 D-03).

        Security: the 422 response body must not leak the broker URI,
        filesystem paths, or internal env var names.
        """

        # Ensure apply_async is never reached — the endpoint should reject
        # before queueing. If it did reach the dispatch, the test fails
        # loudly.
        def _fail_if_called(*_args: object, **_kwargs: object) -> _FakeAsyncResult:
            raise AssertionError(
                "solve_async.apply_async must not be called when solver_name "
                "is unknown — endpoint must reject with 422 first."
            )

        from app.domains.solver.tasks import solve_tasks

        monkeypatch.setattr(solve_tasks.solve_async, "apply_async", _fail_if_called)

        db_session.refresh(test_organization)
        initial_balance = test_organization.credits_balance

        small_problem = _make_small_problem("inf05_unknown", solver_name="gurobi")
        resp = authenticated_client.post("/api/v2/solve/async", json=small_problem)

        # HTTP 422 for unknown solver (SolverNotFoundError).
        assert resp.status_code == 422, resp.text
        detail = resp.json().get("detail", "")
        assert isinstance(detail, str)
        assert "gurobi" in detail
        # Whitelist-safe message: no broker URI, no filesystem path, no
        # env var leak.
        assert "amqp://" not in detail
        assert "redis://" not in detail
        assert "CELERY_BROKER" not in detail
        assert "SOLVER_QUEUE" not in detail
        assert "/app/" not in detail

        # Balance must be restored (pre-pay + refund = net zero).
        db_session.expire(test_organization)
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == initial_balance, (
            f"expected refund to restore balance={initial_balance}, "
            f"got {test_organization.credits_balance}"
        )

    def test_unknown_solver_422_body_does_not_leak_solver_list(
        self,
        authenticated_client,
        test_organization,
        db_session,
        monkeypatch,
    ) -> None:
        """WR-03 regression lock: 422 response body for an unknown solver
        must not enumerate installed solvers.

        Prevents re-introduction of the supported-solver list leak in
        SolverNotFoundError at the HTTP layer. Phase 7 will add commercial
        solvers (hexaly, gurobi, cplex) to SOLVER_QUEUE_MAP — a "Supported:"
        list in the error body would leak which ones are installed on this
        deployment.

        Locks in the fix at app/domains/solver/queue_routing.py:35, which
        propagates to HTTP via app/api/v2/solve.py:500-503 (detail=str(exc)).
        """

        # Endpoint must reject before queueing — apply_async MUST NOT be called.
        def _fail_if_called(*_args: object, **_kwargs: object) -> _FakeAsyncResult:
            raise AssertionError(
                "solve_async.apply_async must not be called when solver_name "
                "is unknown — endpoint must reject with 422 first."
            )

        from app.domains.solver.tasks import solve_tasks

        monkeypatch.setattr(solve_tasks.solve_async, "apply_async", _fail_if_called)

        # Chosen to (a) be ≤ 32 chars (Pydantic `max_length` on solver_name
        # would otherwise short-circuit with a schema validation error
        # before resolve_queue runs, yielding a different 422 body shape)
        # and (b) contain none of the real solver names (scip, highs,
        # hexaly, gurobi, cplex) so the negative assertions cleanly
        # separate "bad input is echoed back" from "installed solvers
        # leaked".
        bad_solver_name = "bogus_commercial_xyz"
        small_problem = _make_small_problem(
            "wr03_regression",
            solver_name=bad_solver_name,
        )
        resp = authenticated_client.post("/api/v2/solve/async", json=small_problem)

        assert resp.status_code == 422, (
            f"Expected 422 for unknown solver, got {resp.status_code}: {resp.text}"
        )

        # FastAPI-wrapped HTTPException stores the message under "detail".
        # The endpoint (app/api/v2/solve.py:500-503) passes detail=str(exc),
        # so detail is a plain string here. Kept list-handling for
        # robustness in case a future Pydantic validation path shows up
        # with the same 422 but a list-of-errors body.
        body = resp.json()
        detail = body.get("detail")
        if isinstance(detail, list):
            detail_text = " ".join(str(item) for item in detail)
        else:
            detail_text = str(detail)

        # Client must see what they asked for and a generic rejection.
        assert "Unknown solver" in detail_text, (
            f"Expected 'Unknown solver' in 422 body, got: {detail_text!r}"
        )
        assert bad_solver_name in detail_text, (
            f"Expected rejected name {bad_solver_name!r} echoed in 422 body, got: {detail_text!r}"
        )

        # Must NOT enumerate installed solvers via the 422 body.
        lowered = detail_text.lower()
        assert "supported:" not in lowered, (
            f"WR-03 regressed: 422 body leaks 'Supported:' list: {detail_text!r}"
        )
        assert "scip" not in lowered, (
            f"WR-03 regressed: 422 body leaks installed solver 'scip': {detail_text!r}"
        )
        assert "highs" not in lowered, (
            f"WR-03 regressed: 422 body leaks installed solver 'highs': {detail_text!r}"
        )

    def test_manual_misroute_raises_queue_mismatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Consumer-side guard catches a HiGHS task landing on solve_scip.

        Simulates the D-05/D-06/D-07 worst-case: the producer would
        already route correctly, but a manual queue poke, routing bug,
        or misconfigured worker puts a HiGHS task into the SCIP worker's
        queue. The consumer-side _assert_queue_match raises
        SolverQueueMismatchError, which the task's outer try/except
        catches and turns into ``{"status": "error", ...}``.

        Does NOT require the broker — uses Celery's ``.apply(kwargs=...)``
        API which executes the task synchronously in-process with a real
        TaskRequest bound to ``self`` (so ``self.request.id`` resolves).
        """
        # Simulate a SCIP worker.
        monkeypatch.setenv("SOLVER_QUEUE", "solve_scip")

        from app.domains.solver.tasks.solve_tasks import solve_async

        # Minimal problem_data — we never reach the solver, the guard
        # raises immediately. _prepaid_credits=0 so the refund branch is
        # a no-op (no DB session needed).
        problem_data: dict[str, object] = {
            "name": "misroute_test",
            "description": "Misroute test",
            "objective": {"sense": "maximize", "expression": "x"},
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
            ],
            "constraints": [],
            "_prepaid_credits": 0,
        }

        # ``solve_async.apply(kwargs=...)`` is Celery's official
        # synchronous-in-process execution API. It builds a real
        # TaskRequest, binds ``self``, and runs the wrapped function.
        # The outer try/except in solve_async catches the guard's
        # SolverQueueMismatchError and returns {"status": "error", ...}.
        async_result = solve_async.apply(
            kwargs={
                "problem_data": problem_data,
                "organization_id": "org_fake_test",
                "user_id": None,
                "workspace_id": None,
                "warm_start_execution_id": None,
                "solver_name": "highs",
            }
        )
        result = async_result.get()

        assert isinstance(result, dict)
        assert result["status"] == "error", f"expected status=error, got {result!r}"
        error_message = result.get("error", "")
        assert isinstance(error_message, str)
        # Guard message contains both the worker queue and the requested
        # solver — BUT NOT broker URIs, filesystem paths, or env values.
        assert "solve_scip" in error_message
        assert "highs" in error_message
        assert "amqp://" not in error_message
        assert "redis://" not in error_message
        assert "CELERY_BROKER" not in error_message
        assert "SOLVER_QUEUE=" not in error_message
