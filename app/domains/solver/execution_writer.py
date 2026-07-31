"""The single writer of ``ModelExecution`` state (ADR-007 S3).

Solving grew ``>=6`` independent ``ModelExecution`` writers (the orchestrator,
the two async workers, the marketplace ``execute_model``, the trigger task and
the reaper), each duplicating the insert-pending -> running -> completed/failed
/cancelled transitions with subtly divergent terminal-state guards. That is the
direct cause of the "pending zombie / empty detail / clobbered cancel" bug class
this codebase documents.

This module owns EVERY ``ModelExecution`` status/result/timing column
transition. Two layers:

* **Pure mutators** (``apply_*``) operate on an ALREADY-LOADED row inside the
  caller's transaction and DO NOT commit — the caller owns the session. They
  return ``True`` when the transition was applied, ``False`` when a terminal
  state won (terminal-state-wins is enforced in exactly one place). These are
  what the request-scoped writers (routes, reaper sweep, marketplace worker)
  use.
* **Own-session best-effort wrappers** (``mark_*_by_task``) open their own
  ``SessionLocal``, look the row up by ``celery_task_id`` + org, apply the
  transition, commit, and NEVER raise — a bookkeeping error must not disturb the
  task's own result path. These are what the ``solve_async`` worker uses,
  because it writes the terminal row AFTER its main solve transaction closed.
"""

from __future__ import annotations

import logging
from typing import Any

from app.domains.solver import ports
from app.models import ExecutionStatus, ModelExecution
from app.models.model_project import ModelProject
from app.shared.db.session import SessionLocal
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)

# A row in any of these states has reached a user-visible verdict; no automatic
# transition may overwrite it (a worker completing a row the user just cancelled,
# the reaper failing a row the worker just completed, an acks_late redelivery).
_TERMINAL_STATES = frozenset(
    {
        ExecutionStatus.CANCELLED.value,
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.FAILED.value,
    }
)


def is_terminal(execution: ModelExecution) -> bool:
    """Whether the row has already reached a terminal (verdict) state."""
    return execution.status in _TERMINAL_STATES


def insert_pending(
    db: Any,
    *,
    execution_id: str,
    organization_id: str,
    celery_task_id: str,
    input_data: dict[str, Any],
    solver_name: str,
    executed_by_user_id: str | None = None,
    auto_route_reason: str | None = None,
    origin: str | None = None,
    source_kind: str | None = None,
    source_id: str | None = None,
    model_project_id: str | None = None,
    model_project_version_id: str | None = None,
    dataset_id: str | None = None,
    dataset_name: str | None = None,
) -> ModelExecution:
    """Add (not commit) the pending row for a queued async solve.

    The caller owns the transaction: the enqueue path commits it best-effort so a
    failed history write never fails an already-queued, already-charged solve.
    """
    execution = ModelExecution(
        id=execution_id,
        organization_id=organization_id,
        executed_by_user_id=executed_by_user_id,
        celery_task_id=celery_task_id,
        is_async=True,
        status=ExecutionStatus.PENDING.value,
        input_data=input_data,
        created_at=utcnow(),
        solver_name=solver_name,
        auto_route_reason=auto_route_reason,
        origin=origin,
        source_kind=source_kind,
        source_id=source_id,
        model_project_id=model_project_id,
        model_project_version_id=model_project_version_id,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
    )
    db.add(execution)
    return execution


def apply_running(execution: ModelExecution) -> bool:
    """Move a loaded row to RUNNING (terminal-wins). No commit."""
    if is_terminal(execution):
        return False
    execution.status = ExecutionStatus.RUNNING.value
    if execution.started_at is None:
        execution.started_at = utcnow()
    return True


def apply_completed(
    execution: ModelExecution,
    *,
    result: Any,
    execution_time_seconds: float | None = None,
    solver_name: str | None = None,
) -> bool:
    """Persist a SUCCESSFUL solve onto a loaded row (terminal-wins). No commit.

    ``result`` is an ``OptimizationResult``-like object: ``result_data`` comes
    from ``to_result_data()``, ``solver_status`` from ``result.status``.
    """
    if is_terminal(execution):
        return False
    execution.status = ExecutionStatus.COMPLETED.value
    if hasattr(result, "to_result_data"):
        execution.result_data = result.to_result_data()
    result_status = getattr(result, "status", None)
    if result_status is not None:
        execution.solver_status = getattr(result_status, "value", str(result_status))
    execution.objective_value = getattr(result, "objective_value", None)
    if execution_time_seconds is not None:
        execution.execution_time_ms = int(execution_time_seconds * 1000)
    if solver_name:
        execution.solver_name = solver_name
    execution.completed_at = utcnow()
    return True


def apply_multi_objective_completed(
    execution: ModelExecution,
    *,
    result_data: dict[str, Any],
    execution_time_seconds: float | None = None,
) -> bool:
    """Persist a SUCCESSFUL multi-objective solve onto a loaded row (terminal-wins).

    Multi-objective yields a Pareto front, not a single ``OptimizationResult``, so the
    caller passes the already-shaped nested ``result_data`` — ``{"multi_objective": …,
    "objective_value": None, "solver_status": "optimal"}`` — directly instead of
    ``to_result_data()``. An empty front (infeasible) is still a completed run,
    matching the synchronous contract. No commit.
    """
    if is_terminal(execution):
        return False
    execution.status = ExecutionStatus.COMPLETED.value
    execution.result_data = result_data
    execution.solver_status = str(result_data.get("solver_status") or "optimal")[:32]
    execution.objective_value = result_data.get("objective_value")
    if execution_time_seconds is not None:
        execution.execution_time_ms = int(execution_time_seconds * 1000)
    execution.completed_at = utcnow()
    return True


def apply_completed_fields(
    execution: ModelExecution,
    *,
    solver_status: str | None = None,
    objective_value: float | None = None,
) -> bool:
    """Complete a loaded row from loose fields, not a result object (terminal-wins).

    The reaper reconciles a Celery-SUCCESS row the worker never wrote back and
    only has the result envelope, not the ``OptimizationResult`` object — so it
    cannot produce ``result_data``. No commit.
    """
    if is_terminal(execution):
        return False
    execution.status = ExecutionStatus.COMPLETED.value
    execution.completed_at = execution.completed_at or utcnow()
    execution.error_message = None
    if solver_status is not None:
        execution.solver_status = solver_status[:32]
    if objective_value is not None:
        execution.objective_value = objective_value
    return True


def apply_failed(
    execution: ModelExecution,
    *,
    error: str,
    preserve_completed_at: bool = False,
) -> bool:
    """Move a loaded row to FAILED (terminal-wins). No commit.

    ``preserve_completed_at`` keeps a pre-set ``completed_at`` (the reaper stamps
    it before the mutation).
    """
    if is_terminal(execution):
        return False
    execution.status = ExecutionStatus.FAILED.value
    execution.error_message = str(error)[:2000]
    if preserve_completed_at:
        execution.completed_at = execution.completed_at or utcnow()
    else:
        execution.completed_at = utcnow()
    return True


def apply_cancelled(execution: ModelExecution, *, message: str = "Cancelled by user") -> bool:
    """Move a loaded row to CANCELLED. No commit.

    Cancellation wins over a live (pending/running) row but never over an
    already-COMPLETED/FAILED verdict.
    """
    if execution.status in (
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.FAILED.value,
    ):
        return False
    execution.status = ExecutionStatus.CANCELLED.value
    execution.error_message = message
    execution.completed_at = utcnow()
    return True


def refresh_locked(db: Any, execution: ModelExecution) -> ModelExecution:
    """Re-read an already-loaded row under ``FOR UPDATE`` (ADR-007 S6b).

    BOTH sides of a terminal transition must lock — an unlocked read on one side
    lets a stale in-memory status slip past the terminal-wins guard (a user
    cancel landing as the worker commits COMPLETED would clobber the result).
    ``populate_existing`` forces the identity-mapped instance to reload, so the
    guard sees the winner's committed status; ``of=`` keeps the lock off the
    nullable eager-joined marketplace relations.
    """
    return (
        db.query(ModelExecution)
        .populate_existing()
        .with_for_update(of=ModelExecution)
        .filter(ModelExecution.id == execution.id)
        .one()
    )


def _lookup_by_task(
    db: Any, task_id: str, organization_id: str, *, lock: bool = False
) -> ModelExecution | None:
    """Load the execution for a task, optionally taking a row lock.

    ADR-007 S6b: the terminal writers (``mark_*_by_task`` + the reaper) load the row
    ``FOR UPDATE`` so the worker↔reaper terminal transition is serialized at the DB —
    the loser blocks, then reads the now-terminal status and its ``is_terminal`` guard
    correctly bails, instead of clobbering the winner (or issuing a stray refund). A
    lock on ONE side alone does not serialize against an unlocked read on the other,
    so BOTH sides lock.
    """
    query = db.query(ModelExecution).filter(
        ModelExecution.celery_task_id == task_id,
        ModelExecution.organization_id == organization_id,
    )
    if lock:
        # ``of=ModelExecution``: lock ONLY the executions row. ModelExecution eager-joins
        # its (nullable) marketplace relations, and a bare FOR UPDATE errors on the
        # nullable side of that outer join ("FOR UPDATE cannot be applied...").
        query = query.with_for_update(of=ModelExecution)
    return query.first()


def _model_name_for(db: Any, execution: ModelExecution) -> str:
    """The name to put in the notification, or a neutral fallback.

    ``ModelExecution`` stores which project ran, not its name — and a run can
    have no project at all (a raw ``POST /solve`` carries only a problem).
    """
    if execution.model_project_id:
        name = (
            db.query(ModelProject.name)
            .filter(ModelProject.id == execution.model_project_id)
            .scalar()
        )
        if name:
            return str(name)
    return "Your model"


def _notify_completed(db: Any, execution: ModelExecution) -> None:
    """Tell the platform a run finished, so the bell hears about it.

    ``solve_model_async`` (running a marketplace/catalog model) emitted this and
    the other two workers never did, so every solve started from the studio —
    the common case, ``origin="visual_builder"`` — showed its toast and left no
    notification behind. Emitting from the writer instead of from one task means
    all three terminal paths report, and a fourth one cannot forget to.

    Best-effort by design, like its caller: a notification failure must never
    cost the execution row that was just committed.
    """
    if not execution.executed_by_user_id:
        return  # API-key runs have no person to notify.
    try:
        ports.solve_events().solve_completed(
            db,
            user_id=execution.executed_by_user_id,
            organization_id=execution.organization_id,
            execution_id=execution.id,
            model_name=_model_name_for(db, execution),
            objective_value=execution.objective_value,
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Failed to notify completion of execution %s: %s", execution.id, exc)


def mark_completed_by_task(
    task_id: str,
    organization_id: str,
    *,
    result: Any,
    execution_time_seconds: float,
    solver_name: str | None,
) -> None:
    """Own-session, best-effort COMPLETED write keyed by ``celery_task_id``.

    Used by the ``solve_async`` worker, which persists its terminal row after the
    main solve transaction closed. Preserves terminal states; never raises.
    """
    try:
        db = SessionLocal()
        try:
            execution = _lookup_by_task(db, task_id, organization_id, lock=True)
            if execution is None:
                return
            if apply_completed(
                execution,
                result=result,
                execution_time_seconds=execution_time_seconds,
                solver_name=solver_name,
            ):
                db.commit()
                _notify_completed(db, execution)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not disturb the task
        logger.warning("Failed to mark execution completed for task %s: %s", task_id, exc)


def mark_multi_objective_completed_by_task(
    task_id: str,
    organization_id: str,
    *,
    result_data: dict[str, Any],
    execution_time_seconds: float,
) -> None:
    """Own-session, best-effort COMPLETED write for a multi-objective run keyed by
    ``celery_task_id`` (the ``solve_multi_objective_async`` worker). Preserves terminal
    states; never raises."""
    try:
        db = SessionLocal()
        try:
            execution = _lookup_by_task(db, task_id, organization_id, lock=True)
            if execution is None:
                return
            if apply_multi_objective_completed(
                execution,
                result_data=result_data,
                execution_time_seconds=execution_time_seconds,
            ):
                db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not disturb the task
        logger.warning(
            "Failed to mark multi-objective execution completed for task %s: %s", task_id, exc
        )


def mark_failed_by_task(task_id: str, organization_id: str, error: str) -> None:
    """Own-session, best-effort FAILED write keyed by ``celery_task_id``.

    Used by the ``solve_async`` worker (solver-level error branch + except
    branch). Preserves terminal states (a user CANCELLED row is not a failure);
    never raises.
    """
    try:
        db = SessionLocal()
        try:
            execution = _lookup_by_task(db, task_id, organization_id, lock=True)
            if execution is None:
                return
            if apply_failed(execution, error=error):
                db.commit()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not disturb the task
        logger.warning("Failed to mark execution failed for task %s: %s", task_id, exc)


__all__ = [
    "apply_cancelled",
    "apply_completed",
    "apply_completed_fields",
    "apply_failed",
    "apply_multi_objective_completed",
    "apply_running",
    "insert_pending",
    "is_terminal",
    "mark_completed_by_task",
    "mark_failed_by_task",
    "mark_multi_objective_completed_by_task",
    "refresh_locked",
]
