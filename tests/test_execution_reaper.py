"""Tests for the stale-execution reaper and Celery solve time limits (W1/W15/F-01).

The reaper (app/tasks/execution_reaper.py) sweeps ModelExecution rows stuck
in pending/running, marks them failed with a clear error_message, and
refunds pre-paid credits idempotently using the SAME reference keys the
task-side refund paths use — so a double sweep, or a sweep racing the task's
own refund, can never double-refund.

Celery state lookups go through ``_get_celery_state``; tests monkeypatch that
single seam to simulate backend states (PENDING / SUCCESS / FAILURE /
PROGRESS) because a real Celery result-backend round-trip needs a live
broker, which is out of scope for this suite. Everything else — executions,
credits, refunds, settings — runs against the real PostgreSQL database.
"""

from datetime import timedelta

import pytest

from app.models import (
    CreditTransaction,
    ExecutionStatus,
    ModelExecution,
    Organization,
    OrganizationModel,
    TransactionType,
)
from app.services.credits_service import CreditsService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.tasks.execution_reaper import reap_stale_executions

# Default thresholds seeded from the settings registry by the
# _seed_platform_settings autouse fixture.
PENDING_MAX = 1800
RUNNING_MAX = 7200


@pytest.fixture
def reaper_org(db_session):
    """Organization with a known balance for refund assertions."""
    org = Organization(
        id=generate_id("org_"),
        name="Reaper Test Org",
        credits_balance=1000,
        credits_earned=0,
        monthly_quota=100,
        currency="EUR",
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


def _naive(dt):
    return dt.replace(tzinfo=None)


def _make_solve_execution(
    db_session,
    org,
    *,
    age_seconds: int,
    status: str = ExecutionStatus.PENDING.value,
    prepaid: int = 7,
    task_id: str | None = None,
):
    """Create a /solve/async-style row (no organization_model_id) + its prepay.

    Mirrors app/api/v2/solve.py: deduct with ('solve', execution_id), then
    persist the row with _prepaid_credits embedded in input_data (D-19).
    """
    execution_id = generate_id("exe_")
    task_id = task_id or f"task_{execution_id}"
    if prepaid > 0:
        CreditsService.deduct_credits(
            db=db_session,
            organization_id=org.id,
            credits=prepaid,
            description=f"Async solve: {execution_id}",
            reference_type="solve",
            reference_id=execution_id,
        )
    execution = ModelExecution(
        id=execution_id,
        organization_id=org.id,
        celery_task_id=task_id,
        is_async=True,
        status=status,
        input_data={"name": "reaper-test", "_prepaid_credits": prepaid},
        created_at=_naive(utcnow() - timedelta(seconds=age_seconds)),
        solver_name="scip",
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    return execution


def _make_model_execution(
    db_session,
    org,
    *,
    age_seconds: int,
    status: str = ExecutionStatus.PENDING.value,
    prepaid: int = 5,
):
    """Create an execute-model-async-style row (organization_model_id set).

    Mirrors app/api/v2/routes/models/execution.py: prepay deducts with
    ('execution', execution_id) — the same key the task-side refund uses.
    ``prepaid=0`` models the legacy dispatch sites that never pre-paid.
    """
    model = OrganizationModel(
        id=generate_id("om_"),
        organization_id=org.id,
        private_definition={"generator_type": "generic", "input_fields": []},
        is_active=True,
    )
    db_session.add(model)
    db_session.flush()

    execution_id = generate_id("exe_")
    if prepaid > 0:
        CreditsService.deduct_credits(
            db=db_session,
            organization_id=org.id,
            credits=prepaid,
            description=f"Async model execution pre-pay: {execution_id}",
            reference_type="execution",
            reference_id=execution_id,
        )
    execution = ModelExecution(
        id=execution_id,
        organization_model_id=model.id,
        organization_id=org.id,
        celery_task_id=f"task_{execution_id}",
        is_async=True,
        status=status,
        input_data={"x": 1},
        created_at=_naive(utcnow() - timedelta(seconds=age_seconds)),
        started_at=_naive(utcnow() - timedelta(seconds=age_seconds)),
        credits_base=prepaid or 1,
        solver_name="scip",
    )
    db_session.add(execution)
    db_session.commit()
    db_session.refresh(execution)
    return execution


def _patch_celery_state(monkeypatch, state, result=None):
    """Simulate the Celery result backend at the reaper's single lookup seam."""
    monkeypatch.setattr(
        "app.tasks.execution_reaper._get_celery_state",
        lambda task_id: (state, result),
    )


def _refunds_for(db_session, org_id, ref_type, ref_id):
    return (
        db_session.query(CreditTransaction)
        .filter(
            CreditTransaction.organization_id == org_id,
            CreditTransaction.transaction_type == TransactionType.REFUND.value,
            CreditTransaction.reference_type == ref_type,
            CreditTransaction.reference_id == ref_id,
        )
        .all()
    )


# CONTRACT-TEST: execution-reaper-invariants
#   Stale pending/running executions are marked failed with a clear error and
#   pre-paid credits are refunded EXACTLY ONCE (idempotent across re-runs and
#   against the task-side refund); fresh/completed/actively-running rows are
#   never touched; Celery-SUCCESS rows reconcile WITHOUT a refund.
class TestExecutionReaper:
    def test_stale_pending_marked_failed_and_refunded_once(
        self, db_session, reaper_org, monkeypatch
    ):
        """A pending row past the threshold with no Celery result is reaped."""
        execution = _make_solve_execution(
            db_session, reaper_org, age_seconds=PENDING_MAX + 600, prepaid=7
        )
        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000 - 7

        _patch_celery_state(monkeypatch, "PENDING")
        summary = reap_stale_executions(db_session)

        assert summary["failed"] == 1
        assert summary["refunded_credits"] == 7

        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.FAILED.value
        assert execution.error_message and "Reaped" in execution.error_message
        assert execution.completed_at is not None

        refunds = _refunds_for(db_session, reaper_org.id, "solve_task", execution.celery_task_id)
        assert len(refunds) == 1
        assert refunds[0].credits_amount == 7

        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000

    def test_fresh_pending_row_is_not_touched(self, db_session, reaper_org, monkeypatch):
        """Rows younger than the pending threshold are never candidates."""
        execution = _make_solve_execution(db_session, reaper_org, age_seconds=60, prepaid=3)
        _patch_celery_state(monkeypatch, "PENDING")

        summary = reap_stale_executions(db_session)

        assert summary["scanned"] == 0
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.PENDING.value
        assert _refunds_for(db_session, reaper_org.id, "solve_task", execution.celery_task_id) == []

    def test_completed_row_is_not_touched(self, db_session, reaper_org, monkeypatch):
        """Terminal rows are excluded from the sweep regardless of age."""
        execution = _make_solve_execution(
            db_session,
            reaper_org,
            age_seconds=PENDING_MAX * 10,
            status=ExecutionStatus.COMPLETED.value,
            prepaid=3,
        )
        _patch_celery_state(monkeypatch, "PENDING")

        summary = reap_stale_executions(db_session)

        assert summary["scanned"] == 0
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.COMPLETED.value

    def test_double_run_does_not_double_refund(self, db_session, reaper_org, monkeypatch):
        """Re-running the sweep (or re-reaping a re-created zombie) refunds once."""
        execution = _make_solve_execution(
            db_session, reaper_org, age_seconds=PENDING_MAX + 600, prepaid=9
        )
        _patch_celery_state(monkeypatch, "PENDING")

        reap_stale_executions(db_session)
        # Simulate the pathological case where the row landed back in
        # 'pending' (e.g. operator reset) — the refund must still be unique.
        execution.status = ExecutionStatus.PENDING.value
        db_session.commit()
        summary2 = reap_stale_executions(db_session)

        assert summary2["refunded_credits"] == 0
        refunds = _refunds_for(db_session, reaper_org.id, "solve_task", execution.celery_task_id)
        assert len(refunds) == 1

        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000  # prepay refunded exactly once

    def test_reaper_does_not_double_refund_after_task_refund(
        self, db_session, reaper_org, monkeypatch
    ):
        """If the task's own except-branch already refunded, the reaper is a no-op.

        Same (org, REFUND, solve_task, task_id) idempotency scope as
        solve_tasks._refund_prepaid_credits.
        """
        execution = _make_solve_execution(
            db_session, reaper_org, age_seconds=PENDING_MAX + 600, prepaid=7
        )
        # Task-side refund (what _refund_prepaid_credits records on failure).
        CreditsService(db_session).refund_credits(
            organization_id=reaper_org.id,
            credits=7,
            description=f"task_exception (task {execution.celery_task_id}): boom",
            reference_type="solve_task",
            reference_id=execution.celery_task_id,
        )
        db_session.commit()

        _patch_celery_state(monkeypatch, "FAILURE")
        summary = reap_stale_executions(db_session)

        assert summary["failed"] == 1
        assert summary["refunded_credits"] == 0
        refunds = _refunds_for(db_session, reaper_org.id, "solve_task", execution.celery_task_id)
        assert len(refunds) == 1
        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000

    def test_celery_success_reconciles_completed_without_refund(
        self, db_session, reaper_org, monkeypatch
    ):
        """A task that succeeded but never wrote back must NOT be refunded."""
        execution = _make_solve_execution(
            db_session, reaper_org, age_seconds=PENDING_MAX + 600, prepaid=7
        )
        _patch_celery_state(
            monkeypatch,
            "SUCCESS",
            result={
                "status": "success",
                "result": {"status": "optimal", "objective_value": 42.5},
            },
        )

        summary = reap_stale_executions(db_session)

        assert summary["completed"] == 1
        assert summary["refunded_credits"] == 0
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.COMPLETED.value
        assert execution.solver_status == "optimal"
        assert execution.objective_value == 42.5
        assert _refunds_for(db_session, reaper_org.id, "solve_task", execution.celery_task_id) == []
        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000 - 7  # solve delivered: charge stands

    def test_celery_success_with_error_payload_marks_failed_and_refunds(
        self, db_session, reaper_org, monkeypatch
    ):
        """Task-level error payloads (status='error') are failures, not successes."""
        execution = _make_solve_execution(
            db_session, reaper_org, age_seconds=PENDING_MAX + 600, prepaid=7
        )
        _patch_celery_state(
            monkeypatch,
            "SUCCESS",
            result={"status": "error", "task_id": execution.celery_task_id, "error": "boom"},
        )

        summary = reap_stale_executions(db_session)

        assert summary["failed"] == 1
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.FAILED.value
        assert "boom" in (execution.error_message or "")
        # Refund is the same idempotent key the task itself would use.
        refunds = _refunds_for(db_session, reaper_org.id, "solve_task", execution.celery_task_id)
        assert len(refunds) == 1

    def test_actively_running_within_threshold_is_skipped(
        self, db_session, reaper_org, monkeypatch
    ):
        """A long solve that the worker still reports as PROGRESS is left alone."""
        execution = _make_solve_execution(
            db_session, reaper_org, age_seconds=PENDING_MAX + 600, prepaid=7
        )
        _patch_celery_state(monkeypatch, "PROGRESS")

        summary = reap_stale_executions(db_session)

        assert summary["skipped"] == 1
        assert summary["failed"] == 0
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.PENDING.value
        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000 - 7

    def test_actively_running_beyond_running_threshold_is_reaped(
        self, db_session, reaper_org, monkeypatch
    ):
        """PROGRESS older than running-max means a hung worker: fail + refund."""
        execution = _make_solve_execution(
            db_session, reaper_org, age_seconds=RUNNING_MAX + 600, prepaid=7
        )
        _patch_celery_state(monkeypatch, "PROGRESS")

        summary = reap_stale_executions(db_session)

        assert summary["failed"] == 1
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.FAILED.value
        assert "hung" in (execution.error_message or "")
        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000

    def test_model_execution_refund_uses_execution_reference(
        self, db_session, reaper_org, monkeypatch
    ):
        """Model-execution rows refund via ('execution', id) — task-side parity."""
        execution = _make_model_execution(
            db_session,
            reaper_org,
            age_seconds=RUNNING_MAX + 600,
            status=ExecutionStatus.RUNNING.value,
            prepaid=5,
        )
        _patch_celery_state(monkeypatch, "PENDING")

        summary = reap_stale_executions(db_session)

        assert summary["failed"] == 1
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.FAILED.value
        refunds = _refunds_for(db_session, reaper_org.id, "execution", execution.id)
        assert len(refunds) == 1
        assert refunds[0].credits_amount == 5
        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000

    def test_model_execution_without_prepay_gets_no_refund(
        self, db_session, reaper_org, monkeypatch
    ):
        """Legacy dispatch sites never pre-paid — reaping must not mint credits."""
        execution = _make_model_execution(
            db_session,
            reaper_org,
            age_seconds=RUNNING_MAX + 600,
            status=ExecutionStatus.RUNNING.value,
            prepaid=0,
        )
        _patch_celery_state(monkeypatch, "PENDING")

        summary = reap_stale_executions(db_session)

        assert summary["failed"] == 1
        assert summary["refunded_credits"] == 0
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.FAILED.value
        assert _refunds_for(db_session, reaper_org.id, "execution", execution.id) == []
        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000  # nothing taken, nothing given

    def test_running_row_between_thresholds_with_unknown_state_is_skipped(
        self, db_session, reaper_org, monkeypatch
    ):
        """DB-status 'running' rows use the (larger) running threshold."""
        execution = _make_model_execution(
            db_session,
            reaper_org,
            age_seconds=PENDING_MAX + 600,  # past pending-max, within running-max
            status=ExecutionStatus.RUNNING.value,
            prepaid=5,
        )
        _patch_celery_state(monkeypatch, None)  # backend unreachable

        summary = reap_stale_executions(db_session)

        assert summary["skipped"] == 1
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.RUNNING.value


class TestSoftTimeLimitHandling:
    """W15/F-01 (c): the soft-limit exception inside solve_async must mark the
    execution failed and refund through the same idempotent path."""

    def test_soft_time_limit_marks_failed_and_refunds(self, db_session, reaper_org, monkeypatch):
        from celery.exceptions import SoftTimeLimitExceeded

        from app.domains.solver.tasks.solve_tasks import solve_async as solve_async_task

        prepaid = 6
        task_id = f"task_{generate_id('exe_')}"
        execution = _make_solve_execution(
            db_session, reaper_org, age_seconds=10, prepaid=prepaid, task_id=task_id
        )

        # Simulate Celery's soft kill firing mid-solve. Patching the solver
        # factory is the only way to raise SoftTimeLimitExceeded
        # deterministically without a live worker + wall-clock timeout; the
        # refund/DB path under test runs fully against real PostgreSQL.
        def _raise_soft_limit(solver_name=None):
            raise SoftTimeLimitExceeded()

        monkeypatch.setattr(
            "app.domains.solver.tasks.solve_tasks.get_solver_service",
            _raise_soft_limit,
        )

        result = solve_async_task.apply(
            kwargs={
                "problem_data": dict(execution.input_data),
                "organization_id": reaper_org.id,
                "solver_name": "scip",
            },
            task_id=task_id,
        )
        payload = result.get(disable_sync_subtasks=False)
        assert payload["status"] == "error"

        db_session.expire_all()
        refreshed = db_session.get(ModelExecution, execution.id)
        assert refreshed.status == ExecutionStatus.FAILED.value
        assert "time limit" in (refreshed.error_message or "").lower()
        assert refreshed.completed_at is not None

        refunds = _refunds_for(db_session, reaper_org.id, "solve_task", task_id)
        assert len(refunds) == 1
        assert refunds[0].credits_amount == prepaid

        db_session.refresh(reaper_org)
        assert reaper_org.credits_balance == 1000

        # And the reaper later finds nothing left to refund (idempotent).
        _patch_celery_state(monkeypatch, "FAILURE")
        summary = reap_stale_executions(db_session)
        assert summary["refunded_credits"] == 0
        assert len(_refunds_for(db_session, reaper_org.id, "solve_task", task_id)) == 1


class TestCeleryTimeLimitDerivation:
    """W15: producers derive worker soft/hard limits from the request's own limit."""

    def test_limits_derived_from_request_time_limit(self, db_session):
        from app.domains.solver.time_limits import (
            HARD_GRACE_SECONDS,
            SOFT_MARGIN_SECONDS,
            compute_celery_time_limits,
        )

        soft, hard = compute_celery_time_limits(db_session, 120.0)
        assert soft == 120 + SOFT_MARGIN_SECONDS
        assert hard == soft + HARD_GRACE_SECONDS

    def test_fallback_uses_solver_default_timeout_setting(self, db_session):
        """W9 cleanup: the previously dead SOLVER_DEFAULT_TIMEOUT key is the fallback."""
        from app.domains.solver.time_limits import (
            HARD_GRACE_SECONDS,
            SOFT_MARGIN_SECONDS,
            compute_celery_time_limits,
        )
        from app.services.platform_settings_service import PlatformSettingsService as PSS

        default_timeout = PSS.get_int(db_session, "SOLVER_DEFAULT_TIMEOUT")
        for bad_value in (None, 0, -5):
            soft, hard = compute_celery_time_limits(db_session, bad_value)
            assert soft == default_timeout + SOFT_MARGIN_SECONDS
            assert hard == soft + HARD_GRACE_SECONDS

    def test_async_solve_endpoint_passes_time_limits_to_apply_async(
        self, authenticated_client, db_session, monkeypatch
    ):
        """POST /solve/async dispatches with soft_time_limit/time_limit set.

        Patches apply_async at the broker boundary (established pattern, see
        tests/integration/test_celery_integration.py) — no broker in the
        suite; the endpoint logic and credit pre-pay run for real.
        """
        from app.domains.solver.tasks import solve_tasks
        from app.domains.solver.time_limits import HARD_GRACE_SECONDS, SOFT_MARGIN_SECONDS

        captured: dict[str, object] = {}

        class _FakeAsyncResult:
            id = "fake_task_id"

        def _capture_apply_async(*args, **kwargs):
            captured.update(kwargs)
            return _FakeAsyncResult()

        monkeypatch.setattr(solve_tasks.solve_async, "apply_async", _capture_apply_async)

        problem = {
            "name": "time_limit_wiring",
            "description": "Verify Celery kill limits derive from the request",
            "objective": {"sense": "maximize", "expression": "x"},
            "variables": [
                {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
            ],
            "constraints": [{"name": "c1", "expression": "x <= 5"}],
            "options": {"time_limit_seconds": 45},
        }
        resp = authenticated_client.post("/api/v2/solve/async", json=problem)
        assert resp.status_code == 200, resp.text

        assert captured.get("soft_time_limit") == 45 + SOFT_MARGIN_SECONDS
        assert captured.get("time_limit") == 45 + SOFT_MARGIN_SECONDS + HARD_GRACE_SECONDS


class TestReaperBeatRegistration:
    """The reaper must actually be scheduled — a task nobody runs fixes nothing."""

    def test_reaper_registered_in_beat_schedule_and_includes(self):
        from app.shared.core.celery_app import celery_app

        entry = celery_app.conf.beat_schedule.get("reap-stale-executions")
        assert entry is not None, "reap-stale-executions missing from beat_schedule"
        assert entry["task"] == "reap_stale_executions"
        assert entry["schedule"] <= 1800, "reaper must run at least as often as the threshold"
        assert entry["options"]["queue"] == "jaot_default"
        assert "app.tasks.execution_reaper" in celery_app.conf.include
