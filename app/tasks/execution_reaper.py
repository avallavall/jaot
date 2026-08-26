"""Periodic reaper for stale async ModelExecution rows (W1 / W15 / F-01).

``/solve/async`` creates ``ModelExecution(status='pending')`` rows whose
status truth historically lived ONLY in the Celery result backend
(``result_expires`` = 7 days). A hung solver, a task enqueued to a
consumer-less queue (the Phase 9 ~37-day incident), or a hard-killed worker
leaves the row 'pending'/'running' forever — polluting user-visible
execution history.

Every beat run (~15 min):

1. Select rows with status in (pending, running) older than the smaller
   threshold (``EXECUTION_REAPER_PENDING_MAX_SECONDS``).
2. Consult the Celery result backend for ground truth (best-effort — a
   backend outage degrades to DB-age-only reaping, never crashes the sweep).
3. Reconcile each row:

   - SUCCESS with a success payload  -> mark completed.
   - SUCCESS with an error payload   -> mark failed.
   - FAILURE / REVOKED               -> mark failed.
   - STARTED / PROGRESS / RETRY      -> actively running; reap only past
     ``EXECUTION_REAPER_RUNNING_MAX_SECONDS`` (hung worker).
   - PENDING / unknown               -> task lost or backend expired; reap
     past the threshold for the row's DB status.

A column of a solver comparison is the exception. Those rows have no Celery task
of their own: one task solves them all in turn on a single-slot worker, so a
column can sit 'pending' for as long as the columns ahead of it take, plus
however long other comparisons are queued in front. Judged by its own age it
looks exactly like the lost task this reaper exists to clean up. It is judged by
its PARENT's age and its parent's own time budget instead — see
``_comparison_still_alive``.

The same sweep also settles stale ``TriggerRun`` rows (D-36). There the stakes
are higher than a wrong-looking history row: ``cron_fire_task`` refuses to fire
while any run of that trigger is 'pending' or 'running', so one run nobody will
ever finish stops that schedule for good — and every later tick records
``skipped_overlap``, which is what normal overlap protection looks like.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, defer

from app.domains.solver import execution_writer
from app.models import ExecutionStatus, ModelExecution, SolverComparison
from app.models.solver_comparison import ComparisonStatus
from app.models.trigger import TriggerRun
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core.celery_app import celery_app
from app.shared.db.session import SessionLocal
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

# Celery states meaning "a worker is actively processing the task".
# PROGRESS is the custom state set by solve_tasks.update_task_progress().
_ACTIVE_STATES = frozenset({"STARTED", "PROGRESS", "RETRY"})
# Terminal-failure states: the task will never deliver a result.
_FAILED_STATES = frozenset({"FAILURE", "REVOKED"})

# Safety valve: cap rows per sweep so a pathological backlog cannot turn a
# 15-minute beat tick into an hours-long transaction storm. The next tick
# picks up the remainder (oldest first).
_MAX_ROWS_PER_SWEEP = 500

# The name the broker reports for a trigger's solve, and how long to wait for
# the fleet to answer. Short: this runs on a beat tick, not a request, but a
# silent broker must not hold the tick open.
_TRIGGER_SOLVE_TASK_NAME = "app.tasks.trigger_tasks.trigger_solve_task"
_BROKER_INSPECT_TIMEOUT_SECONDS = 2.0


def _get_celery_state(task_id: str) -> tuple[str | None, Any]:
    """Best-effort ``(state, result)`` lookup in the Celery result backend.

    Returns ``(None, None)`` when the backend is unreachable so the sweep
    degrades to DB-age-only reaping instead of crashing.
    """
    try:
        from celery.result import AsyncResult

        res = AsyncResult(task_id, app=celery_app)
        state: str = res.state
        result = res.result if state == "SUCCESS" else None
        return state, result
    except Exception as exc:
        logger.warning("Reaper: Celery state lookup failed for task %s: %s", task_id, exc)
        return None, None


def _result_is_error(result: Any) -> bool:
    """Mirror GET /solve/async's two-level error detection on a SUCCESS payload.

    Task-level: ``{"status": "error", ...}`` (exception caught by the task).
    Solver-level: ``{"status": "success", "result": {"status": "error"}}``.
    """
    if not isinstance(result, dict):
        return False
    if result.get("status") == "error":
        return True
    inner = result.get("result")
    return isinstance(inner, dict) and str(inner.get("status", "")).lower() == "error"


def _mark_failed(db: Session, execution: ModelExecution, error_message: str) -> None:
    """Mark the row failed under a row lock (terminal-wins, ADR-007 S3/S6b).

    A row the worker completed (or the user cancelled) between this sweep's
    UNLOCKED SELECT and now must not be overwritten. Lock + refresh the row so
    the terminal check sees its CURRENT state: this serializes against the
    worker's FOR-UPDATE terminal write — whichever commits first wins, and the
    loser bails here.
    """
    db.refresh(execution, with_for_update={"of": ModelExecution})
    if execution_writer.is_terminal(execution):
        return
    execution_writer.apply_failed(execution, error=error_message, preserve_completed_at=True)


def _mark_completed(db: Session, execution: ModelExecution, result: Any) -> None:
    """Reconcile a Celery-SUCCESS row the task never wrote back (W1 gap).

    Only the result envelope is available (not the ``OptimizationResult`` object),
    so ``result_data`` cannot be reconstructed here — the single writer records
    the loose solver_status/objective fields it can recover.
    """
    # ADR-007 S6b: lock + refresh so apply_completed_fields' terminal-wins guard below
    # sees the row's CURRENT state — a worker that just wrote the terminal row wins and
    # this reconcile becomes a no-op (serialized against the worker's FOR-UPDATE write).
    db.refresh(execution, with_for_update={"of": ModelExecution})
    if execution_writer.is_terminal(execution):
        return
    inner = result.get("result") if isinstance(result, dict) else None
    solver_status: str | None = None
    objective: float | None = None
    if isinstance(inner, dict):
        raw_status = inner.get("status")
        if isinstance(raw_status, str):
            solver_status = raw_status
        raw_objective = inner.get("objective_value")
        if isinstance(raw_objective, (int, float)):
            objective = float(raw_objective)
    execution_writer.apply_completed_fields(
        execution, solver_status=solver_status, objective_value=objective
    )


def _comparison_still_alive(
    db: Session,
    execution: ModelExecution,
    now: datetime,
    running_max: int,
) -> bool:
    """Whether this row is a column of a comparison that is still legitimately running.

    Returns False for every ordinary solve, so the sweep is unchanged for them.

    A row of a MATRIX waits longer still: its siblings were launched with it and
    run before it on the same worker, so its bound is the whole matrix.

    For a comparison column, the row's own age says nothing: the comparison task
    solves its solvers one at a time on a worker that runs one comparison at a
    time, so a column can be 'pending' for the whole run ahead of it and for
    every comparison queued in front. The parent's budget is the honest bound —
    every solver it plans to run, each capped at the shared time limit, plus
    ``running_max`` of slack for queueing and startup. Past that the parent is
    genuinely stuck and its columns are reaped like anything else.
    """
    if not execution.comparison_id:
        return False

    comparison = (
        db.query(SolverComparison).filter(SolverComparison.id == execution.comparison_id).first()
    )
    if comparison is None:
        return False
    if comparison.status not in (
        ComparisonStatus.PENDING.value,
        ComparisonStatus.RUNNING.value,
    ):
        return False

    planned = max(1, len(comparison.solver_names or []))
    budget = planned * float(comparison.time_limit_seconds) + running_max

    if comparison.batch_id:
        # A row of a matrix waits for every row before it: they were launched
        # together and they run one after another on the same single-slot worker.
        # Judged by its own row's budget, the last row of a twelve-row matrix
        # looks abandoned for most of the run and would be reaped mid-queue.
        rows = (
            db.query(SolverComparison)
            .filter(SolverComparison.batch_id == comparison.batch_id)
            .count()
        )
        budget = max(1, rows) * planned * float(comparison.time_limit_seconds) + running_max

    parent_age = (now - (comparison.started_at or comparison.created_at)).total_seconds()
    return parent_age <= budget


def _reap_one(
    db: Session,
    execution: ModelExecution,
    now: datetime,
    pending_max: int,
    running_max: int,
) -> str:
    """Reconcile one stale candidate.

    Returns an outcome: 'completed' | 'failed' | 'skipped'.
    """
    age_base = execution.started_at or execution.created_at
    age_seconds = (now - age_base).total_seconds()

    if _comparison_still_alive(db, execution, now, running_max):
        return "skipped"

    state: str | None = None
    result: Any = None
    if execution.celery_task_id:
        state, result = _get_celery_state(execution.celery_task_id)

    if state == "SUCCESS":
        if _result_is_error(result):
            error = "Reaped: task reported an error but never updated this execution."
            if isinstance(result, dict):
                detail = result.get("error")
                if isinstance(detail, str) and detail:
                    error = f"Reaped: {detail[:500]}"
            _mark_failed(db, execution, error)
            return "failed"
        _mark_completed(db, execution, result)
        return "completed"

    if state in _ACTIVE_STATES:
        if age_seconds <= running_max:
            return "skipped"  # legitimately long solve, still alive
        _mark_failed(
            db,
            execution,
            (
                f"Reaped: worker still reported active after {int(age_seconds)}s "
                f"(running limit {running_max}s) — assuming a hung solver."
            ),
        )
        return "failed"

    if state in _FAILED_STATES:
        _mark_failed(
            db,
            execution,
            (
                "Reaped: the solve task failed without updating this execution "
                "(worker killed or task revoked)."
            ),
        )
        return "failed"

    # PENDING / unknown backend state / no celery_task_id at all.
    threshold = running_max if execution.status == ExecutionStatus.RUNNING.value else pending_max
    if age_seconds <= threshold:
        return "skipped"
    _mark_failed(
        db,
        execution,
        (
            f"Reaped: stuck in '{execution.status}' for {int(age_seconds)}s with no "
            "result in the task backend (lost task or expired result)."
        ),
    )
    return "failed"


def reap_stale_executions(db: Session) -> dict[str, Any]:
    """Sweep stale pending/running ModelExecution rows. Commits per row.

    Per-row commit isolation: one poisoned row (e.g. concurrent lock) is
    rolled back and logged without aborting the rest of the sweep.
    """
    pending_max = PSS.get_int(db, "EXECUTION_REAPER_PENDING_MAX_SECONDS")
    running_max = PSS.get_int(db, "EXECUTION_REAPER_RUNNING_MAX_SECONDS")
    now = utcnow()
    min_age = min(pending_max, running_max)

    candidates = (
        db.query(ModelExecution)
        # The sweep reads four fields per row and writes a handful more. Without
        # this it loaded the whole entity, payloads included: 113 kB per row on
        # average on the development database, so a full sweep of 500 read about
        # 55 MB to decide whether a run had gone quiet. Deferred, not
        # `load_only`, so every scalar the writers touch stays loaded.
        .options(
            defer(ModelExecution.input_data),
            defer(ModelExecution.result_data),
            defer(ModelExecution.progress_data),
            defer(ModelExecution.scenario_analysis),
        )
        .filter(
            ModelExecution.status.in_(
                [ExecutionStatus.PENDING.value, ExecutionStatus.RUNNING.value]
            ),
            ModelExecution.created_at < now - timedelta(seconds=min_age),
        )
        .order_by(ModelExecution.created_at)
        .limit(_MAX_ROWS_PER_SWEEP)
        .all()
    )

    summary: dict[str, Any] = {
        "scanned": len(candidates),
        "completed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
    }

    for execution in candidates:
        try:
            outcome = _reap_one(db, execution, now, pending_max, running_max)
            db.commit()
            summary[outcome] += 1
        except Exception as exc:
            db.rollback()
            summary["errors"] += 1
            logger.error("Reaper failed on execution %s: %s", execution.id, exc, exc_info=True)

    if summary["failed"] or summary["completed"] or summary["errors"]:
        logger.info("Execution reaper sweep: %s", summary)
    return summary


_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled", "skipped_overlap"})


def _runs_a_worker_still_holds() -> frozenset[str] | None:
    """The ``run_id`` of every ``trigger_solve_task`` the fleet has in hand.

    A ``TriggerRun`` stores no Celery task id, so there is no backend to ask
    the way the execution sweep asks ``AsyncResult``. The broker knows anyway:
    one broadcast returns every task each worker is running, has reserved, or
    has scheduled, arguments included, and the run id is the first one
    (``trigger_solve_task(self, run_id, trigger_id, override_data)`` is bound,
    so ``self`` is not in ``args``).

    This matters because 'pending' does not mean lost. It also means queued,
    and the pending threshold is 30 minutes by default while a solve is allowed
    to run for 48 hours — so a busy solve queue would have its live jobs reaped,
    and reaping one releases the overlap gate that stops the cron firing a
    second run of the same trigger.

    Returns None when the broker cannot be reached, which is evidence absent,
    not evidence of nothing. The caller reaps anyway in that case: refusing to
    would put the sweep back to where D-36 found it, with an abandoned run
    blocking its cron for good and every tick logging an ordinary-looking
    overlap skip. The cost of being wrong is bounded on the other side —
    ``trigger_solve_task`` refuses to run a row that is already settled, so a
    reaped-but-queued job stops instead of running as a second live run.
    """
    try:
        inspector = celery_app.control.inspect(timeout=_BROKER_INSPECT_TIMEOUT_SECONDS)
        held: set[str] = set()
        seen_any = False
        for probe in (inspector.active, inspector.reserved, inspector.scheduled):
            by_worker = probe()
            if by_worker is None:
                continue
            seen_any = True
            for tasks in by_worker.values():
                for task in tasks or []:
                    inner = task.get("request", task)
                    if inner.get("name") != _TRIGGER_SOLVE_TASK_NAME:
                        continue
                    args = inner.get("args") or []
                    if args and isinstance(args[0], str):
                        held.add(args[0])
        return frozenset(held) if seen_any else None
    except Exception as exc:  # noqa: BLE001 — no broker means no evidence, not a crash
        logger.warning("Reaper: could not ask the broker which runs are held: %s", exc)
        return None


def _reap_one_trigger_run(
    db: Session, run_id: str, now: datetime, pending_max: int, running_max: int
) -> str:
    """Settle one stale trigger run. Returns 'failed' or 'skipped'.

    Reads three columns and writes three, through Core rather than the ORM. A
    ``TriggerRun`` also holds a whole solver result and a whole override set,
    and the sweep commits once per row: under ``expire_on_commit`` — which is
    what ``SessionLocal`` uses and the test harness does not — that commit
    expires every remaining instance, so the next attribute touch reloads the
    full row and undoes any ``defer`` on the candidate query. Never holding an
    instance is the only version of this that stays true.

    ``FOR UPDATE`` and a re-read of the status first. The sweep selected without
    a lock, and the worker may have finished the run in between: writing
    'failed' over a completed run reports a finished solve as a failure and
    orphans its result. ``_mark_failed`` carries the same guard for
    ``ModelExecution``.

    No webhook and no notification go out. The reaper knows the run stopped, not
    what happened to it, and the same is true of every ``ModelExecution`` it
    settles. What it restores is the history and the schedule.
    """
    row = db.execute(
        select(TriggerRun.status, TriggerRun.created_at)
        .where(TriggerRun.id == run_id)
        .with_for_update()
    ).first()
    if row is None or row.status in _TERMINAL_RUN_STATUSES:
        return "skipped"

    threshold = running_max if row.status == "running" else pending_max
    age_seconds = (now - row.created_at).total_seconds()
    if age_seconds <= threshold:
        return "skipped"

    db.execute(
        update(TriggerRun)
        .where(TriggerRun.id == run_id)
        .values(
            status="failed",
            completed_at=now,
            error_message=(
                f"Reaped: stuck in '{row.status}' for {int(age_seconds)}s "
                f"(limit {threshold}s) — the task was lost or its worker was killed."
            ),
        )
    )
    return "failed"


def reap_stale_trigger_runs(db: Session) -> dict[str, Any]:
    """Sweep stale pending/running ``TriggerRun`` rows. Commits per row.

    Runs after the execution sweep on purpose: they share a session, and a
    poisoned row must not take the rest of the sweep down with it.
    """
    pending_max = PSS.get_int(db, "EXECUTION_REAPER_PENDING_MAX_SECONDS")
    running_max = PSS.get_int(db, "EXECUTION_REAPER_RUNNING_MAX_SECONDS")
    now = utcnow()

    held = _runs_a_worker_still_holds()
    broker_answered = held is not None
    if held is None:
        held = frozenset()

    candidate_ids = [
        r.id
        for r in db.execute(
            # Ids only. See _reap_one_trigger_run: an ORM instance would be
            # expired by the first per-row commit and reload its payloads.
            select(TriggerRun.id)
            .where(
                # One floor per status, in SQL. A single
                # min(pending_max, running_max) floor let every 'running' row
                # older than 30 minutes into the window to be judged against the
                # 48-hour limit and skipped; ordered oldest first and capped at
                # 500 rows, those skips crowd out the 'pending' rows the sweep
                # exists to rescue — silently, because the summary log only
                # fired on a failure or an error.
                or_(
                    and_(
                        TriggerRun.status == "pending",
                        TriggerRun.created_at < now - timedelta(seconds=pending_max),
                    ),
                    and_(
                        TriggerRun.status == "running",
                        TriggerRun.created_at < now - timedelta(seconds=running_max),
                    ),
                )
            )
            .order_by(TriggerRun.created_at)
            .limit(_MAX_ROWS_PER_SWEEP)
        ).all()
    ]

    summary: dict[str, Any] = {
        "scanned": len(candidate_ids),
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "broker_answered": broker_answered,
    }

    for run_id in candidate_ids:
        if run_id in held:
            summary["skipped"] += 1
            continue
        try:
            outcome = _reap_one_trigger_run(db, run_id, now, pending_max, running_max)
            db.commit()
            summary[outcome] += 1
        except Exception as exc:
            db.rollback()
            summary["errors"] += 1
            logger.error("Reaper failed on trigger run %s: %s", run_id, exc, exc_info=True)

    if summary["scanned"]:
        logger.info("Trigger run reaper sweep: %s", summary)
    return summary


@celery_app.task(bind=True, name="reap_stale_executions", acks_late=True)  # type: ignore[misc]
def reap_stale_executions_task(self: Any) -> dict[str, Any]:
    """Thin Celery wrapper — owns the session lifecycle, delegates to the impls.

    Both sweeps ride one beat tick and one session. They are separate functions
    because they settle different tables, and a failure in either is contained
    per row, so neither can stop the other from running.
    """
    db = SessionLocal()
    executions: dict[str, Any] = {"scanned": 0, "failed": 0, "completed": 0, "errors": 0}
    trigger_runs: dict[str, Any] = {"scanned": 0, "failed": 0, "skipped": 0, "errors": 0}
    try:
        # One try each. Per-row containment covers only the loops; everything
        # before them — the settings reads, the candidate query over a 216 MB
        # table — is unprotected, and sharing a try meant one unparseable
        # EXECUTION_REAPER_* row switched off the trigger-run sweep as well.
        # That sweep is what stops an abandoned run blocking its cron for good,
        # and its absence looks exactly like ordinary overlap protection.
        try:
            executions = reap_stale_executions(db)
        except Exception as exc:
            logger.error("Execution sweep failed: %s", exc, exc_info=True)
            db.rollback()
            executions["errors"] += 1

        try:
            trigger_runs = reap_stale_trigger_runs(db)
        except Exception as exc:
            logger.error("Trigger run sweep failed: %s", exc, exc_info=True)
            db.rollback()
            trigger_runs["errors"] += 1

        return {**executions, "trigger_runs": trigger_runs}
    finally:
        db.close()


__all__ = [
    "reap_stale_executions",
    "reap_stale_trigger_runs",
    "reap_stale_executions_task",
]
