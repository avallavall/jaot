"""Celery integration tests using a real worker.

Tests the actual async pipeline: submit via API, poll for result,
verify timeout/failure behavior with a real Celery worker.

IMPORTANT: These tasks have NO retry logic. solve_async and solve_model_async
fail permanently on any exception (no max_retries, no self.retry() calls).

Requires a Celery worker that (a) consumes the ``solve_scip`` queue — the
queue ``POST /api/v2/solve/async`` routes SCIP solves to via
``resolve_queue('scip')`` — and (b) is bound to the SAME ``jaot_test``
database the test process writes to, so the refund assertion in
``test_async_solve_refund_on_failure`` observes the worker's credit refund.

The dev worker (``jaot_celery``) does NOT satisfy either requirement: it
consumes only ``jaot_default`` and is bound to the dev ``jaot`` database, so
tasks submitted by these tests would sit unconsumed forever (status stays
``pending``) and any refund would land in the wrong DB. Start the dedicated
test-profile worker instead:

    docker compose --profile test up -d celery-worker-test-scip

(see ``docker-compose.yml`` services ``celery-worker-test-*`` — each is bound
to ``jaot_test`` and pinned to one queue via ``-Q``). The
``celery_worker_available`` fixture below SKIPS (not fails) the whole class
when no worker is consuming ``solve_scip``, so a plain ``pytest`` run without
the test worker is a clean skip — never a false timeout.
"""

import time

import pytest

from app.domains.solver.queue_routing import resolve_queue
from app.shared.core.celery_app import celery_app

POLL_INTERVAL = 1  # seconds
POLL_TIMEOUT = 60  # seconds


def _poll_until_done(client, task_id, timeout=POLL_TIMEOUT):
    """Poll GET /api/v2/solve/async/{task_id} until terminal status.

    Returns the final response dict when status is terminal
    (completed/failed/cancelled) or raises TimeoutError.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/v2/solve/async/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("completed", "failed", "cancelled"):
            return data
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(
        f"Task {task_id} did not reach terminal state within {timeout}s. "
        f"Last status: {data['status']}"
    )


# All problems in this class omit solver_name, so /api/v2/solve/async routes
# them to the SCIP queue via resolve_queue(None) -> resolve_queue('scip').
# The fixture must confirm a worker is actually CONSUMING this queue — a bare
# ping() would be satisfied by the dev worker (jaot_celery on jaot_default),
# which never picks up these tasks, producing a 60s timeout that masquerades
# as a product bug. resolve_queue is the single source of truth for the name.
_REQUIRED_QUEUE = resolve_queue(None)


@pytest.fixture(scope="class")
def celery_worker_available():
    """Skip the class unless a worker consumes the SCIP solve queue.

    Pinging any worker is not enough: the queue these tests dispatch to
    (``solve_scip``) must have a live consumer bound to the ``jaot_test``
    database, otherwise the submitted task sits unconsumed and the poll
    helper times out at 60s. We inspect ``active_queues()`` and require at
    least one worker advertising ``_REQUIRED_QUEUE`` before running. When
    absent we ``skip`` (not fail) with the exact command to bring it up.
    """
    skip_msg = (
        f"No Celery worker consuming the '{_REQUIRED_QUEUE}' queue. Start the "
        f"test-profile worker: docker compose --profile test up -d celery-worker-test-scip"
    )
    try:
        inspector = celery_app.control.inspect(timeout=5)
        active_queues = inspector.active_queues()
        if not active_queues:
            pytest.skip(skip_msg)
        consumes_required = any(
            queue.get("name") == _REQUIRED_QUEUE
            for queues in active_queues.values()
            for queue in (queues or [])
        )
        if not consumes_required:
            pytest.skip(skip_msg)
    except Exception as exc:
        pytest.skip(f"Cannot reach Celery worker ({exc}). {skip_msg}")


# A small valid optimization problem (2 vars, 1 constraint)
SMALL_VALID_PROBLEM = {
    "name": "test_small",
    "description": "Small test problem",
    "objective": {
        "sense": "maximize",
        "expression": "3*x + 2*y",
    },
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
        {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
    ],
    "constraints": [
        {"name": "c1", "expression": "x + y <= 15"},
    ],
    "options": {"time_limit_seconds": 30},
}

# Infeasible problem: contradictory constraints (x >= 10 AND x <= 5)
INFEASIBLE_PROBLEM = {
    "name": "test_infeasible",
    "description": "Infeasible problem with contradictory constraints",
    "objective": {
        "sense": "minimize",
        "expression": "x",
    },
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 100},
    ],
    "constraints": [
        {"name": "c_low", "expression": "x >= 10"},
        {"name": "c_high", "expression": "x <= 5"},
    ],
    "options": {"time_limit_seconds": 30},
}


@pytest.mark.integration
class TestCeleryAsyncSolve:
    """Integration tests for async solve pipeline via real Celery worker."""

    @pytest.fixture(autouse=True)
    def _require_worker(self, celery_worker_available):
        """Ensure worker is available for all tests in this class."""

    def test_async_solve_completes_successfully(
        self, authenticated_client, test_organization, db_session
    ):
        """Submit a small valid problem and poll until completed."""
        resp = authenticated_client.post(
            "/api/v2/solve/async",
            json=SMALL_VALID_PROBLEM,
        )
        assert resp.status_code == 200
        body = resp.json()
        task_id = body["task_id"]
        assert body["status"] == "pending"

        result = _poll_until_done(authenticated_client, task_id)
        assert result["status"] == "completed"
        assert "result" in result

    def test_async_solve_fails_permanently_on_exception(
        self, authenticated_client, test_organization, db_session
    ):
        """Submit a problem that fails in the solver and verify NO retry.

        The solve_async task catches all exceptions and returns
        {"status": "error", ...}. There is no max_retries and no
        self.retry() call. Once a task fails, it stays failed permanently.
        """
        # Problem with abs(x) in the objective: passes API validation
        # (validate_problem only checks variable names) but fails during
        # solving because the expression parser rejects abs() of a variable.
        bad_problem = {
            "name": "test_bad_expr",
            "description": "Will fail during solving",
            "objective": {
                "sense": "maximize",
                "expression": "abs(x)",
            },
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": -10, "upper_bound": 10},
            ],
            "constraints": [
                {"name": "c1", "expression": "x <= 10"},
            ],
            "options": {"time_limit_seconds": 10},
        }

        resp = authenticated_client.post("/api/v2/solve/async", json=bad_problem)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        result = _poll_until_done(authenticated_client, task_id)
        assert result["status"] == "failed"
        assert "error" in result or (
            "result" in result and result["result"].get("status") == "error"
        )

        # Verify no retry: poll a few extra times and confirm status stays "failed"
        for _ in range(3):
            time.sleep(POLL_INTERVAL)
            check = authenticated_client.get(f"/api/v2/solve/async/{task_id}")
            assert check.json()["status"] == "failed", (
                "Task was re-queued after failure -- this should not happen "
                "(solve_async has no retry logic)"
            )

    def test_async_solve_refund_on_failure(
        self, authenticated_client, test_organization, db_session
    ):
        """Async solve refunds pre-paid credits on Celery task failure (D-19).

        Production fix: app/api/v2/solve.py now sets problem_data["_prepaid_credits"]
        before queueing the Celery task, so solve_async's exception handler can
        read the amount and call CreditsService.refund_credits() to restore the
        balance. Without that field, the refund branch silently no-ops and
        credits are lost on every async failure.

        This test verifies the END-TO-END refund: balance after the failed
        async solve must equal the balance BEFORE the request.

        (Renamed from test_async_solve_credits_lost_on_failure, which was a
        "documents the bug" baseline. Once the fix landed, the assertion was
        flipped from credits_after < credits_before to credits_after == before.)
        """
        db_session.refresh(test_organization)
        credits_before = test_organization.credits_balance

        # Submit a problem that will fail: abs(x) passes API validation
        # but the expression parser rejects it during solving.
        bad_problem = {
            "name": "test_credits_refunded",
            "description": "Will fail, credits MUST be refunded",
            "objective": {
                "sense": "maximize",
                "expression": "abs(x)",
            },
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": -10, "upper_bound": 10},
            ],
            "constraints": [
                {"name": "c1", "expression": "x <= 10"},
            ],
            "options": {"time_limit_seconds": 10},
        }

        resp = authenticated_client.post("/api/v2/solve/async", json=bad_problem)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # Wait for failure
        result = _poll_until_done(authenticated_client, task_id)
        assert result["status"] == "failed"

        # Refresh org to get updated balance
        db_session.expire(test_organization)
        db_session.refresh(test_organization)
        credits_after = test_organization.credits_balance

        # The refund MUST restore the balance to its starting value.
        # If the production fix is reverted, this assertion catches it.
        assert credits_after == credits_before, (
            f"Pre-paid credits must be refunded on async failure, "
            f"but balance changed from {credits_before} to {credits_after}"
        )

    def test_async_solve_timeout_returns_failed(
        self, authenticated_client, test_organization, db_session
    ):
        """Submit a problem with an extremely tight time limit.

        The solver should time out and the task should eventually be marked
        as failed or completed with a time_limit solver status.
        """
        # A problem complex enough that it won't solve in 0.001 seconds
        timeout_problem = {
            "name": "test_timeout",
            "description": "Should time out",
            "objective": {
                "sense": "maximize",
                "expression": "x1 + x2 + x3 + x4 + x5",
            },
            "variables": [
                {"name": f"x{i}", "type": "integer", "lower_bound": 0, "upper_bound": 100}
                for i in range(1, 6)
            ],
            "constraints": [
                {"name": "c1", "expression": "x1 + x2 + x3 + x4 + x5 <= 50"},
                {"name": "c2", "expression": "2*x1 + 3*x2 + x3 <= 80"},
            ],
            "options": {"time_limit_seconds": 1},
        }

        resp = authenticated_client.post("/api/v2/solve/async", json=timeout_problem)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        result = _poll_until_done(authenticated_client, task_id)
        # Solver may complete with time_limit status or fail
        assert result["status"] in ("completed", "failed"), (
            f"Expected completed or failed, got {result['status']}"
        )

    def test_async_solve_infeasible_returns_failed(
        self, authenticated_client, test_organization, db_session
    ):
        """Submit an infeasible problem (contradictory constraints)."""
        resp = authenticated_client.post(
            "/api/v2/solve/async",
            json=INFEASIBLE_PROBLEM,
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        result = _poll_until_done(authenticated_client, task_id)
        # Infeasible problems may be "completed" with infeasible solver_status
        # or "failed" depending on how the solver reports the result
        assert result["status"] in ("completed", "failed")
        if result["status"] == "completed" and "result" in result:
            inner = result["result"]
            if isinstance(inner, dict) and "result" in inner:
                solver_result = inner["result"]
                if isinstance(solver_result, dict) and "status" in solver_result:
                    assert solver_result["status"] in (
                        "infeasible",
                        "error",
                        "time_limit",
                    )

    def test_async_solve_cancel_running_task(
        self, authenticated_client, test_organization, db_session
    ):
        """Submit a long-running problem, wait for running state, then cancel."""
        # A larger problem that should take longer to solve
        long_problem = {
            "name": "test_cancel",
            "description": "Long running for cancellation test",
            "objective": {
                "sense": "maximize",
                "expression": " + ".join(f"x{i}" for i in range(1, 21)),
            },
            "variables": [
                {"name": f"x{i}", "type": "integer", "lower_bound": 0, "upper_bound": 1000}
                for i in range(1, 21)
            ],
            "constraints": [
                {
                    "name": "c1",
                    "expression": " + ".join(f"x{i}" for i in range(1, 21)) + " <= 500",
                },
                {
                    "name": "c2",
                    "expression": " + ".join(f"{i}*x{i}" for i in range(1, 21)) + " <= 2000",
                },
            ],
            "options": {"time_limit_seconds": 300},
        }

        resp = authenticated_client.post("/api/v2/solve/async", json=long_problem)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # Brief wait for the task to start running
        time.sleep(2)

        # Cancel the task
        cancel_resp = authenticated_client.post(f"/api/v2/solve/async/{task_id}/cancel")
        # Cancel endpoint may return 200 (success) or 403 (no ModelExecution
        # record for this task_id -- async solve uses celery task ID, not
        # a ModelExecution). Either outcome is valid for this test.
        if cancel_resp.status_code == 200:
            cancel_body = cancel_resp.json()
            assert "cancelled" in cancel_body or "task_id" in cancel_body
        else:
            # 403 means no ModelExecution row for this task -- expected for
            # tasks submitted via POST /api/v2/solve/async which doesn't
            # create a ModelExecution record
            assert cancel_resp.status_code == 403

        # Poll until terminal state (task may have completed before cancel)
        result = _poll_until_done(authenticated_client, task_id, timeout=30)
        assert result["status"] in ("completed", "failed", "cancelled")


# Fast refund-on-failure verification (no Celery worker required)
#
# The @pytest.mark.integration class above requires
# `docker-compose --profile test up -d` to run. These tests below verify the
# same production fix (app/api/v2/solve.py setting _prepaid_credits on the
# task payload so solve_async's exception handler can refund) using
# solve_async.apply() for in-process synchronous execution — no broker
# required. Runs on every local pytest invocation.


class TestAsyncSolvePrepaidRefund:
    """In-process verification that the /solve/async refund contract holds.

    The production fix in app/api/v2/solve.py passes the pre-paid credits
    amount through to the Celery task via problem_data["_prepaid_credits"].
    Without that field, solve_async's exception handler short-circuits the
    refund path and credits are lost on every async failure.
    """

    def test_solve_async_endpoint_sets_prepaid_credits_on_task_payload(
        self,
        authenticated_client,
        test_organization,
        db_session,
        monkeypatch,
    ) -> None:
        """POST /solve/async must include _prepaid_credits in the queued payload.

        Captures the kwargs passed to ``solve_async.apply_async`` by patching
        at the task module, then asserts the ``kwargs["problem_data"]`` dict
        contains ``_prepaid_credits`` equal to the deducted amount. This is
        the endpoint-side half of the D-19 refund contract.

        Phase 6 plan 02 migrated the producer from ``.delay(**kwargs)`` to
        ``.apply_async(kwargs=..., queue=...)`` so the assertion reads from
        the ``kwargs`` sub-dict now.
        """
        captured: dict[str, object] = {}

        class _FakeAsyncResult:
            id = "fake_task_id"

        def _capture_apply_async(*args, **kwargs):
            captured.update(kwargs)
            return _FakeAsyncResult()

        from app.domains.solver.tasks import solve_tasks

        monkeypatch.setattr(solve_tasks.solve_async, "apply_async", _capture_apply_async)

        db_session.refresh(test_organization)
        initial_balance = test_organization.credits_balance

        small_problem = {
            "name": "prepaid_fix_verification",
            "description": "Verify _prepaid_credits is set on task payload",
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

        resp = authenticated_client.post("/api/v2/solve/async", json=small_problem)
        assert resp.status_code == 200, resp.text
        estimated = resp.json()["estimated_credits"]
        assert estimated > 0

        # The endpoint must have passed a kwargs dict containing problem_data,
        # with _prepaid_credits set to the estimated (pre-paid) amount.
        assert "kwargs" in captured, (
            f"solve_async.apply_async was not called with a kwargs arg: {captured}"
        )
        task_kwargs = captured["kwargs"]
        assert isinstance(task_kwargs, dict)
        assert "problem_data" in task_kwargs, (
            f"solve_async.apply_async kwargs missing problem_data: {task_kwargs}"
        )
        payload = task_kwargs["problem_data"]
        assert isinstance(payload, dict)
        assert "_prepaid_credits" in payload, (
            "_prepaid_credits missing from queued payload — "
            "solve_tasks.solve_async cannot refund on failure"
        )
        assert payload["_prepaid_credits"] == estimated, (
            f"_prepaid_credits={payload['_prepaid_credits']} does not match "
            f"estimated_credits={estimated}"
        )

        # Dispatch must carry an explicit queue kwarg — producer is the single
        # source of truth for routing (D-01).
        assert captured.get("queue") in {"solve_scip", "solve_highs"}, (
            f"apply_async must be called with a resolved queue kwarg, got {captured!r}"
        )

        # And the pre-payment deduction actually happened on the org balance.
        db_session.expire(test_organization)
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == initial_balance - estimated, (
            f"expected balance {initial_balance - estimated}, "
            f"got {test_organization.credits_balance}"
        )

    def test_solve_async_task_refunds_when_prepaid_credits_present(
        self,
        db_session,
        test_organization,
    ) -> None:
        """solve_async.apply() synchronously refunds on exception when _prepaid_credits is set.

        Invokes the task in-process via apply() with a deliberately malformed
        problem_data (missing 'variables'/'objective'). The task's
        Pydantic OptimizationProblem(**problem_data) call raises, the outer
        except catches it, and the refund branch fires because
        _prepaid_credits > 0.
        """
        from app.domains.solver.tasks.solve_tasks import solve_async as solve_async_task
        from app.models import CreditTransaction, TransactionType
        from app.services.credits_service import CreditsService

        prepaid = 9
        org_id = test_organization.id

        # Pre-pay credits the same way the endpoint does
        CreditsService.deduct_credits(
            db=db_session,
            organization_id=org_id,
            credits=prepaid,
            description="Pre-pay for async refund unit test",
            reference_type="solve",
            reference_id="unit_async_prepay_refund",
        )
        db_session.commit()
        db_session.refresh(test_organization)
        starting_balance = test_organization.credits_balance

        # Malformed payload: OptimizationProblem(**...) will raise inside the
        # task, triggering the exception handler. The refund condition reads
        # _prepaid_credits from the payload — same shape as the production
        # fix sets in app/api/v2/solve.py.
        bad_payload = {
            "name": "unit_async_bad",
            "description": "Will fail during parsing",
            "_prepaid_credits": prepaid,
        }

        result = solve_async_task.apply(args=[bad_payload, org_id, None, None, None])
        task_result = result.get(disable_sync_subtasks=False)
        assert task_result["status"] == "error"
        task_id = task_result["task_id"]

        # Refund transaction must exist with the exact credit amount
        refund_tx = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org_id,
                CreditTransaction.reference_type == "solve_task",
                CreditTransaction.reference_id == task_id,
            )
            .one_or_none()
        )
        # The refund runs in its own SessionLocal() inside the task, so our
        # test session may not see it without a fresh query. Refresh and retry.
        if refund_tx is None:
            db_session.expire_all()
            refund_tx = (
                db_session.query(CreditTransaction)
                .filter(
                    CreditTransaction.organization_id == org_id,
                    CreditTransaction.reference_type == "solve_task",
                    CreditTransaction.reference_id == task_id,
                )
                .one_or_none()
            )
        assert refund_tx is not None, (
            f"No refund transaction for failed task {task_id}. Production fix may have regressed."
        )
        assert refund_tx.credits_amount == prepaid
        assert refund_tx.transaction_type == TransactionType.REFUND.value

        # End-to-end balance reconciliation: balance is restored above
        # starting_balance by exactly `prepaid`.
        db_session.expire(test_organization)
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == starting_balance + prepaid


# Producer-side queue routing contract:
#  1. celery_app.conf has worker_send_task_events + task_send_sent_event
#     enabled (required for celery-exporter D-27 metrics / D-28 alerts).
#  2. No static task_routes for solve_async / solve_model_async — producer
#     apply_async(queue=...) is the single source of truth (D-03).
#  3. /api/v2/solve/async dispatches via apply_async(queue=resolve_queue(
#     solver_name)): SCIP -> solve_scip, HiGHS -> solve_highs (D-01, D-02).


class TestProducerRoutingWiring:
    """Wiring contract: event flags, cleaned task_routes, queue-aware dispatch."""

    def test_celery_conf_enables_worker_send_task_events(self) -> None:
        """worker_send_task_events must be True so celery-exporter sees events.

        Without this flag, the exporter cannot populate
        celery_task_runtime_seconds (D-27 metric) or celery_task_failed_total
        (D-28 alert). This is Pitfall 1 (BLOCKING) in 06-RESEARCH.
        """
        from app.shared.core.celery_app import celery_app

        assert celery_app.conf.worker_send_task_events is True, (
            "celery_app.conf.worker_send_task_events must be True for "
            "celery-exporter to emit task-runtime metrics (D-27)"
        )

    def test_celery_conf_enables_task_send_sent_event(self) -> None:
        """task_send_sent_event must be True so producers stamp task-sent.

        task-sent events give celery-exporter a complete picture of the
        task lifecycle (sent -> received -> started -> succeeded/failed)
        and therefore accurate queue-depth latency.
        """
        from app.shared.core.celery_app import celery_app

        assert celery_app.conf.task_send_sent_event is True, (
            "celery_app.conf.task_send_sent_event must be True for "
            "celery-exporter to track task_sent timestamps"
        )

    def test_no_static_route_for_solve_tasks(self) -> None:
        """D-03: solve tasks route via apply_async(queue=...) at call site.

        Static task_routes entries are removed so there is a single
        source of truth for the queue decision — the producer.
        """
        from app.shared.core.celery_app import celery_app

        routes = celery_app.conf.task_routes or {}
        assert "app.domains.solver.tasks.solve_tasks.solve_async" not in routes, (
            "solve_async must not have a static task_routes entry — "
            "the producer decides the queue via resolve_queue()"
        )
        assert "app.domains.solver.tasks.solve_tasks.solve_model_async" not in routes, (
            "solve_model_async must not have a static task_routes entry — "
            "the producer decides the queue via resolve_queue()"
        )

    def test_async_solve_highs_dispatches_to_solve_highs_queue(
        self,
        authenticated_client,
        test_organization,
        db_session,
        monkeypatch,
    ) -> None:
        """POST /solve/async with solver_name=highs -> queue='solve_highs'.

        Captures the apply_async kwargs to verify the producer asked
        RabbitMQ for the HiGHS queue.
        """
        captured: dict[str, object] = {}

        class _FakeAsyncResult:
            id = "fake_task_id_highs"

        def _capture_apply_async(*args, **kwargs):
            captured.update(kwargs)
            return _FakeAsyncResult()

        from app.domains.solver.tasks import solve_tasks

        monkeypatch.setattr(solve_tasks.solve_async, "apply_async", _capture_apply_async)

        small_problem = {
            "name": "routing_highs",
            "description": "Dispatch to solve_highs",
            "solver_name": "highs",
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

        resp = authenticated_client.post("/api/v2/solve/async", json=small_problem)
        assert resp.status_code == 200, resp.text
        assert captured.get("queue") == "solve_highs", (
            f"expected queue=solve_highs, got {captured!r}"
        )

    def test_async_solve_defaults_to_solve_scip_queue(
        self,
        authenticated_client,
        test_organization,
        db_session,
        monkeypatch,
    ) -> None:
        """POST /solve/async with no solver_name -> queue='solve_scip' (default).

        D-02: solver_name=None resolves to 'scip' -> queue 'solve_scip'.
        Backward-compatibility contract (HIGH-04 propagation chain).
        """
        captured: dict[str, object] = {}

        class _FakeAsyncResult:
            id = "fake_task_id_scip"

        def _capture_apply_async(*args, **kwargs):
            captured.update(kwargs)
            return _FakeAsyncResult()

        from app.domains.solver.tasks import solve_tasks

        monkeypatch.setattr(solve_tasks.solve_async, "apply_async", _capture_apply_async)

        small_problem = {
            "name": "routing_default_scip",
            "description": "Default dispatches to solve_scip",
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

        resp = authenticated_client.post("/api/v2/solve/async", json=small_problem)
        assert resp.status_code == 200, resp.text
        assert captured.get("queue") == "solve_scip", (
            f"expected queue=solve_scip (default), got {captured!r}"
        )
