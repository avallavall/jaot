"""Execution reaper — stale-row reconciliation (W1 / W15 / F-01, ADR-008).

The reaper is a pure STATUS reconciler: stale pending/running rows are marked
failed with a clear error; Celery-SUCCESS rows the task never wrote back are
reconciled to completed; fresh/terminal/actively-running rows are never
touched. (The credit-refund half of the old reaper died with ADR-008.)
"""

from datetime import timedelta

import pytest

from app.models import (
    ExecutionStatus,
    ModelExecution,
    ModelProject,
    Organization,
)
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.tasks.execution_reaper import reap_stale_executions

# Default thresholds seeded from the settings registry by the
# _seed_platform_settings autouse fixture.
PENDING_MAX = 1800
RUNNING_MAX = 172800


@pytest.fixture
def reaper_org(db_session):
    org = Organization(
        id=generate_id("org_"),
        name="Reaper Test Org",
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


def _make_solve_execution(
    db_session,
    org,
    *,
    age_seconds: int,
    status: str = ExecutionStatus.PENDING.value,
    task_id: str | None = None,
):
    """Create a /solve/async-style row (no organization_model_id)."""
    execution_id = generate_id("exe_")
    task_id = task_id or f"task_{execution_id}"
    execution = ModelExecution(
        id=execution_id,
        organization_id=org.id,
        celery_task_id=task_id,
        is_async=True,
        status=status,
        input_data={"name": "reaper-test"},
        created_at=utcnow() - timedelta(seconds=age_seconds),
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
):
    """Create an execute-model-async-style row (model_project_id set, P1.5)."""
    project = ModelProject(
        id=generate_id("mp_"),
        organization_id=org.id,
        name="Reaper model",
        status="active",
    )
    db_session.add(project)
    db_session.flush()

    execution_id = generate_id("exe_")
    execution = ModelExecution(
        id=execution_id,
        model_project_id=project.id,
        organization_id=org.id,
        celery_task_id=f"task_{execution_id}",
        is_async=True,
        status=status,
        input_data={"x": 1},
        created_at=utcnow() - timedelta(seconds=age_seconds),
        started_at=utcnow() - timedelta(seconds=age_seconds),
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


# CONTRACT-TEST: execution-reaper-invariants
#   Stale pending/running executions are marked failed with a clear error;
#   fresh/completed/actively-running rows are never touched; Celery-SUCCESS
#   rows reconcile to completed; terminal-wins holds against a racing worker.
class TestExecutionReaper:
    def test_stale_pending_marked_failed(self, db_session, reaper_org, monkeypatch):
        """A pending row past the threshold with no Celery result is reaped."""
        execution = _make_solve_execution(db_session, reaper_org, age_seconds=PENDING_MAX + 600)

        _patch_celery_state(monkeypatch, "PENDING")
        summary = reap_stale_executions(db_session)

        assert summary["failed"] == 1

        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.FAILED.value
        assert execution.error_message and "Reaped" in execution.error_message
        assert execution.completed_at is not None

    def test_fresh_pending_row_is_not_touched(self, db_session, reaper_org, monkeypatch):
        """Rows younger than the pending threshold are never candidates."""
        execution = _make_solve_execution(db_session, reaper_org, age_seconds=60)
        _patch_celery_state(monkeypatch, "PENDING")

        summary = reap_stale_executions(db_session)

        assert summary["scanned"] == 0
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.PENDING.value

    def test_completed_row_is_not_touched(self, db_session, reaper_org, monkeypatch):
        """Terminal rows are excluded from the sweep regardless of age."""
        execution = _make_solve_execution(
            db_session,
            reaper_org,
            age_seconds=PENDING_MAX * 10,
            status=ExecutionStatus.COMPLETED.value,
        )
        _patch_celery_state(monkeypatch, "PENDING")

        summary = reap_stale_executions(db_session)

        assert summary["scanned"] == 0
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.COMPLETED.value

    def test_celery_success_reconciles_completed(self, db_session, reaper_org, monkeypatch):
        """A task that succeeded but never wrote back reconciles to completed."""
        execution = _make_solve_execution(db_session, reaper_org, age_seconds=PENDING_MAX + 600)
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
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.COMPLETED.value
        assert execution.solver_status == "optimal"
        assert execution.objective_value == 42.5

    def test_celery_success_with_error_payload_marks_failed(
        self, db_session, reaper_org, monkeypatch
    ):
        """Task-level error payloads (status='error') are failures, not successes."""
        execution = _make_solve_execution(db_session, reaper_org, age_seconds=PENDING_MAX + 600)
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

    def test_actively_running_within_threshold_is_skipped(
        self, db_session, reaper_org, monkeypatch
    ):
        """A long solve that the worker still reports as PROGRESS is left alone."""
        execution = _make_solve_execution(db_session, reaper_org, age_seconds=PENDING_MAX + 600)
        _patch_celery_state(monkeypatch, "PROGRESS")

        summary = reap_stale_executions(db_session)

        assert summary["skipped"] == 1
        assert summary["failed"] == 0
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.PENDING.value

    def test_actively_running_beyond_running_threshold_is_reaped(
        self, db_session, reaper_org, monkeypatch
    ):
        """PROGRESS older than running-max means a hung worker: mark failed."""
        execution = _make_solve_execution(db_session, reaper_org, age_seconds=RUNNING_MAX + 600)
        _patch_celery_state(monkeypatch, "PROGRESS")

        summary = reap_stale_executions(db_session)

        assert summary["failed"] == 1
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.FAILED.value
        assert "hung" in (execution.error_message or "")

    def test_running_row_between_thresholds_with_unknown_state_is_skipped(
        self, db_session, reaper_org, monkeypatch
    ):
        """DB-status 'running' rows use the (larger) running threshold."""
        execution = _make_model_execution(
            db_session,
            reaper_org,
            age_seconds=PENDING_MAX + 600,  # past pending-max, within running-max
            status=ExecutionStatus.RUNNING.value,
        )
        _patch_celery_state(monkeypatch, None)  # backend unreachable

        summary = reap_stale_executions(db_session)

        assert summary["skipped"] == 1
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.RUNNING.value

    def test_reaper_bails_when_worker_completes_row_mid_sweep(
        self, db_session, reaper_org, monkeypatch
    ):
        """# CONTRACT-TEST: the worker-reaper terminal-wins race (ADR-007 S6b).

        The sweep loaded a pending row, but the worker committed it COMPLETED
        before the reaper acted on it. The reaper must lock + refresh, see the
        terminal status, and BAIL — no overwrite to failed. Without the
        FOR-UPDATE refresh the reaper would clobber the worker's verdict.
        """
        from sqlalchemy import update as sa_update

        from app.tasks.execution_reaper import _mark_failed

        execution = _make_solve_execution(db_session, reaper_org, age_seconds=3600)

        # Worker completes the SAME row via a Core UPDATE with
        # synchronize_session=False, so the DB row is COMPLETED while the ORM
        # `execution` stays stale (pending) in memory — exactly the TOCTOU the
        # fix must close.
        db_session.execute(
            sa_update(ModelExecution)
            .where(ModelExecution.id == execution.id)
            .values(status=ExecutionStatus.COMPLETED.value)
            .execution_options(synchronize_session=False)
        )
        assert execution.status == ExecutionStatus.PENDING.value  # in-memory still stale

        _mark_failed(db_session, execution, "reaper stale message")
        db_session.commit()

        # Refreshed under lock, saw COMPLETED, bailed: verdict preserved.
        db_session.refresh(execution)
        assert execution.status == ExecutionStatus.COMPLETED.value


class TestSoftTimeLimitHandling:
    """W15/F-01 (c): the soft-limit exception inside solve_async must mark the
    execution failed with a clear reason."""

    def test_soft_time_limit_marks_failed(self, db_session, reaper_org, monkeypatch):
        from celery.exceptions import SoftTimeLimitExceeded

        from app.domains.solver.tasks.solve_tasks import solve_async as solve_async_task

        task_id = f"task_{generate_id('exe_')}"
        execution = _make_solve_execution(db_session, reaper_org, age_seconds=10, task_id=task_id)

        # Simulate Celery's soft kill firing mid-solve. Patching the solver
        # factory is the only way to raise SoftTimeLimitExceeded
        # deterministically without a live worker + wall-clock timeout.
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


class TestCeleryTimeLimitDerivation:
    """W15: producers derive worker soft/hard limits from the request's own limit."""

    def test_limits_derived_from_request_time_limit(self, db_session):
        from app.api.v2._solver_limits import compute_celery_time_limits
        from app.domains.solver.time_limits import HARD_GRACE_SECONDS, SOFT_MARGIN_SECONDS

        soft, hard = compute_celery_time_limits(db_session, 120.0)
        assert soft == 120 + SOFT_MARGIN_SECONDS
        assert hard == soft + HARD_GRACE_SECONDS

    def test_fallback_uses_solver_default_timeout_setting(self, db_session):
        """W9 cleanup: the previously dead SOLVER_DEFAULT_TIMEOUT key is the fallback."""
        from app.api.v2._solver_limits import compute_celery_time_limits
        from app.domains.solver.time_limits import HARD_GRACE_SECONDS, SOFT_MARGIN_SECONDS
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
