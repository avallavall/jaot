"""Celery task for a solver comparison: the same problem, one solver at a time.

One task drives the whole comparison rather than one task per solver. That is the
only way the seconds in the table mean anything: the task runs on
``solve_compare``, whose worker has ``--concurrency=1``, so exactly one solve is
running on that machine at any moment. Fanning out to the per-solver queues would
be faster and would measure how busy each worker happened to be.

Two numbers are recorded per solver, and they are not the same number:

- ``ModelExecution.execution_time_ms`` — wall time around the whole call,
  translating the problem into that solver's own model included. It is what the
  user waits for, so it is what the table shows.
- ``result_data.solve_time_seconds`` — the adapter's own measure of the search.
  Kept because a solver that is slow to build and fast to search is a different
  story from one that is slow at both.

Cancellation is checked between solves, not during one. A solve already inside
the solver cannot be interrupted from here, so a cancelled comparison finishes
the solve in flight and stops before the next one.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from app.domains.solver import execution_writer
from app.domains.solver.services import get_solver_service
from app.models import ModelExecution, SolverComparison
from app.models.optimization_model import ExecutionStatus
from app.models.solver_comparison import ComparisonStatus
from app.schemas.optimization import OptimizationProblem
from app.shared.core.celery_app import celery_app
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


def _own_session() -> Any:
    """A session of this module's own, resolved at call time.

    Deliberately not a name bound at import, for the reason
    ``execution_writer._own_session`` gives: the test harness swaps
    ``SessionLocal`` on the session module, and an import-time binding keeps
    pointing at a database the suite never created.
    """
    from app.shared.db.session import SessionLocal  # noqa: PLC0415

    return SessionLocal()


@celery_app.task(bind=True, name="run_solver_comparison")  # type: ignore[misc]
def run_solver_comparison(
    self: Any,
    comparison_id: str,
    organization_id: str,
) -> dict[str, Any]:
    """Solve one comparison's problem with each of its solvers, in order."""
    task_id = self.request.id
    logger.info("Starting solver comparison %s (task %s)", comparison_id, task_id)

    db = _own_session()
    try:
        comparison = _load(db, comparison_id, organization_id)
        if comparison is None:
            raise ValueError(f"Comparison {comparison_id} not found")

        if comparison.status == ComparisonStatus.CANCELLED.value:
            # Cancelled between enqueue and pickup. Nothing ran, so there is
            # nothing to unwind; the children are already cancelled by the API.
            logger.info("Comparison %s was cancelled before it started", comparison_id)
            return {"status": "cancelled", "comparison_id": comparison_id, "solved": 0}

        comparison.status = ComparisonStatus.RUNNING.value
        comparison.started_at = utcnow()
        comparison.machine_note = _machine_note()
        db.commit()

        problem = OptimizationProblem.model_validate(comparison.problem_data)
        solved = 0

        for solver_name in comparison.solver_names:
            execution = _pending_child(db, comparison_id, solver_name)
            if execution is None:
                # Either it was planned as unsupported (already terminal) or a
                # previous attempt of this task finished it. Both mean skip.
                continue

            if _is_cancelled(db, comparison_id, organization_id):
                _cancel_remaining(db, comparison_id)
                _finish(db, comparison, ComparisonStatus.CANCELLED)
                logger.info("Comparison %s cancelled after %d solves", comparison_id, solved)
                return {"status": "cancelled", "comparison_id": comparison_id, "solved": solved}

            _run_one(db, execution, problem, solver_name)
            solved += 1

        _finish(db, comparison, ComparisonStatus.COMPLETED)
        logger.info("Comparison %s finished: %d solves", comparison_id, solved)
        return {"status": "success", "comparison_id": comparison_id, "solved": solved}

    except Exception as exc:
        detail = (
            "The comparison exceeded its time budget and was stopped."
            if isinstance(exc, SoftTimeLimitExceeded)
            else str(exc)
        )
        logger.error("Comparison %s failed: %s", comparison_id, detail)
        _mark_failed(db, comparison_id, organization_id, detail)
        return {"status": "error", "comparison_id": comparison_id, "error": detail}
    finally:
        db.close()


def _run_one(
    db: Any,
    execution: ModelExecution,
    problem: OptimizationProblem,
    solver_name: str,
) -> None:
    """Solve one column and write its verdict. Never raises.

    A solver that blows up must not take the rest of the table with it: the row
    is marked failed with the error, and the comparison moves to the next solver.
    A comparison where three of four columns worked is still worth reading.
    """
    execution_writer.apply_running(execution)
    db.commit()

    started = time.monotonic()
    try:
        result = get_solver_service(solver_name=solver_name).solve(problem)
    except Exception as exc:  # noqa: BLE001 — one column failing is not a task failure
        elapsed = time.monotonic() - started
        logger.warning("Comparison solve failed on %s: %s", solver_name, exc)
        db.rollback()
        execution = db.merge(execution)
        execution_writer.apply_failed(execution, error=str(exc))
        execution.execution_time_ms = int(elapsed * 1000)
        db.commit()
        return

    elapsed = time.monotonic() - started
    execution_writer.apply_completed(
        execution,
        result=result,
        execution_time_seconds=elapsed,
        solver_name=solver_name,
    )
    # A solver can report an error instead of raising one, and
    # ``to_result_data()`` does not carry ``error_message``. Without this the
    # table would show a column that says "error" and nothing about why.
    if getattr(result, "error_message", None):
        execution.error_message = str(result.error_message)[:2000]
    db.commit()


def _load(db: Any, comparison_id: str, organization_id: str) -> SolverComparison | None:
    return (
        db.query(SolverComparison)
        .filter(
            SolverComparison.id == comparison_id,
            SolverComparison.organization_id == organization_id,
        )
        .first()
    )


def _pending_child(db: Any, comparison_id: str, solver_name: str) -> ModelExecution | None:
    """The not-yet-run execution for this solver, or None if there is nothing to do."""
    return (
        db.query(ModelExecution)
        .filter(
            ModelExecution.comparison_id == comparison_id,
            ModelExecution.solver_name == solver_name,
            ModelExecution.status.in_(
                [ExecutionStatus.PENDING.value, ExecutionStatus.RUNNING.value]
            ),
        )
        .first()
    )


def _is_cancelled(db: Any, comparison_id: str, organization_id: str) -> bool:
    """Re-read the parent's status. Expires the identity map first so a cancel
    written by the API in another process is actually seen."""
    db.expire_all()
    comparison = _load(db, comparison_id, organization_id)
    return comparison is not None and comparison.status == ComparisonStatus.CANCELLED.value


def _cancel_remaining(db: Any, comparison_id: str) -> None:
    """Mark every column that never got its turn as cancelled."""
    remaining = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.comparison_id == comparison_id,
            ModelExecution.status.in_(
                [ExecutionStatus.PENDING.value, ExecutionStatus.RUNNING.value]
            ),
        )
        .all()
    )
    for execution in remaining:
        execution_writer.apply_cancelled(execution, message="Comparison cancelled")
    db.commit()


def _finish(db: Any, comparison: SolverComparison, status: ComparisonStatus) -> None:
    comparison.status = status.value
    comparison.completed_at = utcnow()
    db.commit()


def _machine_note() -> str:
    """Which machine produced these seconds.

    Times are only comparable within one comparison on one machine, so the
    machine travels with them instead of being left for the reader to assume.
    """
    return f"{socket.gethostname()} (queue solve_compare, concurrency 1)"[:255]


def _mark_failed(db: Any, comparison_id: str, organization_id: str, error: str) -> None:
    """Best-effort terminal write so a comparison never stays 'running' forever."""
    try:
        db.rollback()
        comparison = _load(db, comparison_id, organization_id)
        if comparison is None:
            return
        comparison.status = ComparisonStatus.FAILED.value
        comparison.error_message = str(error)[:2000]
        comparison.completed_at = utcnow()
        _cancel_remaining(db, comparison_id)
        db.commit()
    except Exception as exc:  # pragma: no cover - the failure path's own failure
        logger.warning("Could not record comparison failure for %s: %s", comparison_id, exc)
