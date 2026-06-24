"""Periodic reaper for stale async ModelExecution rows (W1 / W15 / F-01).

``/solve/async`` creates ``ModelExecution(status='pending')`` rows whose
status truth historically lived ONLY in the Celery result backend
(``result_expires`` = 7 days). A hung solver, a task enqueued to a
consumer-less queue (the Phase 9 ~37-day incident), or a hard-killed worker
leaves the row 'pending'/'running' forever — polluting user-visible
execution history and silently losing the pre-paid credits.

Every beat run (~15 min):

1. Select rows with status in (pending, running) older than the smaller
   threshold (``EXECUTION_REAPER_PENDING_MAX_SECONDS``).
2. Consult the Celery result backend for ground truth (best-effort — a
   backend outage degrades to DB-age-only reaping, never crashes the sweep).
3. Reconcile each row:

   - SUCCESS with a success payload  -> mark completed, NO refund.
   - SUCCESS with an error payload   -> mark failed + idempotent refund.
   - FAILURE / REVOKED               -> mark failed + idempotent refund.
   - STARTED / PROGRESS / RETRY      -> actively running; reap only past
     ``EXECUTION_REAPER_RUNNING_MAX_SECONDS`` (hung worker), then refund.
   - PENDING / unknown               -> task lost or backend expired; reap
     past the threshold for the row's DB status, then refund.

Refunds reuse the EXACT idempotency keys of the task-side refund paths so a
reaped task that later resolves (acks_late redelivery) can never
double-refund:

- ``solve_async`` rows:       ``(org, REFUND, 'solve_task', celery_task_id)``
  — same scope as ``solve_tasks._refund_prepaid_credits`` and DB-enforced by
  the ``ux_credit_txn_refund_solve_task`` partial unique index.
- ``solve_model_async`` rows: ``(org, REFUND, 'execution', execution_id)``
  — same scope as the task's failure-path refund.

Refund amounts come from what was actually pre-paid (the
``_prepaid_credits`` payload marker for solve rows; the recorded EXECUTION
deduction for model rows) — never from a guess, so legacy non-prepaid
dispatch sites cannot be minted free credits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.domains.solver.prepaid import get_prepaid_credits
from app.models import (
    CreditTransaction,
    ExecutionStatus,
    ModelExecution,
    TransactionType,
)
from app.services.credits_service import CreditsService
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core.celery_app import celery_app
from app.shared.core.prometheus_metrics import CREDITS_REFUNDED, RefundReason
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


def _resolve_refund(db: Session, execution: ModelExecution) -> tuple[int, str, str] | None:
    """Return ``(credits, reference_type, reference_id)`` for the row's prepay.

    ``None`` when nothing was pre-paid — refunding a non-prepaid execution
    would mint credits out of thin air.
    """
    if execution.organization_model_id is None:
        # /solve/async path: amount travels in the payload (D-19 contract);
        # the cancel endpoint zeroes it, so cancelled rows refund nothing.
        prepaid = get_prepaid_credits(execution.input_data)
        if prepaid > 0 and execution.celery_task_id:
            return prepaid, "solve_task", execution.celery_task_id
        return None

    # Model-execution path: only refund what an EXECUTION deduction with the
    # task-side idempotency key actually took (legacy dispatch sites did not
    # pre-pay).
    prepay_tx = (
        db.query(CreditTransaction)
        .filter(
            CreditTransaction.organization_id == execution.organization_id,
            CreditTransaction.transaction_type == TransactionType.EXECUTION.value,
            CreditTransaction.reference_type == "execution",
            CreditTransaction.reference_id == execution.id,
            CreditTransaction.credits_amount < 0,
        )
        .first()
    )
    if prepay_tx is None:
        return None
    return abs(prepay_tx.credits_amount), "execution", execution.id


def _refund_if_owed(db: Session, execution: ModelExecution, detail: str) -> int:
    """Refund the row's prepay exactly once. Returns credits refunded (0 if none).

    Runs BEFORE the row is mutated so a refund failure (e.g. frozen org)
    can roll back cleanly and still let the caller mark the row failed.
    """
    resolved = _resolve_refund(db, execution)
    if resolved is None:
        return 0
    credits, ref_type, ref_id = resolved

    # Pre-check so the CREDITS_REFUNDED metric only counts NEW refunds —
    # record_transaction's own idempotency would silently return the
    # existing row and double-count the metric otherwise.
    existing = (
        db.query(CreditTransaction)
        .filter(
            CreditTransaction.organization_id == execution.organization_id,
            CreditTransaction.transaction_type == TransactionType.REFUND.value,
            CreditTransaction.reference_type == ref_type,
            CreditTransaction.reference_id == ref_id,
        )
        .first()
    )
    if existing is not None:
        return 0

    CreditsService(db).refund_credits(
        organization_id=execution.organization_id,
        credits=credits,
        description=(f"{RefundReason.EXECUTION_REAPED.value} ({execution.id}): {detail[:160]}"),
        reference_type=ref_type,
        reference_id=ref_id,
    )
    CREDITS_REFUNDED.labels(reason=RefundReason.EXECUTION_REAPED.value).inc(credits)
    logger.info(
        "Reaper refunded %d credits for execution %s (ref=%s/%s)",
        credits,
        execution.id,
        ref_type,
        ref_id,
    )
    return credits


def _fail_and_refund(db: Session, execution: ModelExecution, error_message: str) -> int:
    """Refund (idempotently) then mark the row failed. Returns credits refunded."""
    refunded = 0
    try:
        refunded = _refund_if_owed(db, execution, error_message)
    except Exception as exc:
        # Refund failure (frozen org, transient DB error) must not leave the
        # zombie row in place — roll back the partial refund work and still
        # mark the row failed below. The next sweep retries the refund via
        # the idempotent key.
        logger.error("Reaper refund failed for execution %s: %s", execution.id, exc)
        db.rollback()

    execution.status = ExecutionStatus.FAILED.value
    execution.error_message = error_message[:2000]
    execution.completed_at = execution.completed_at or utcnow()
    return refunded


def _mark_completed(db: Session, execution: ModelExecution, result: Any) -> None:
    """Reconcile a Celery-SUCCESS row the task never wrote back (W1 gap)."""
    execution.status = ExecutionStatus.COMPLETED.value
    execution.completed_at = execution.completed_at or utcnow()
    execution.error_message = None
    inner = result.get("result") if isinstance(result, dict) else None
    if isinstance(inner, dict):
        solver_status = inner.get("status")
        if isinstance(solver_status, str):
            execution.solver_status = solver_status[:32]
        objective = inner.get("objective_value")
        if isinstance(objective, (int, float)):
            execution.objective_value = float(objective)


def _reap_one(
    db: Session,
    execution: ModelExecution,
    now: datetime,
    pending_max: int,
    running_max: int,
) -> tuple[str, int]:
    """Reconcile one stale candidate.

    Returns ``(outcome, credits_refunded)`` with outcome one of
    'completed' | 'failed' | 'skipped'.
    """
    age_base = execution.started_at or execution.created_at
    age_seconds = (now - age_base).total_seconds()

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
            return "failed", _fail_and_refund(db, execution, error)
        _mark_completed(db, execution, result)
        return "completed", 0

    if state in _ACTIVE_STATES:
        if age_seconds <= running_max:
            return "skipped", 0  # legitimately long solve, still alive
        refunded = _fail_and_refund(
            db,
            execution,
            (
                f"Reaped: worker still reported active after {int(age_seconds)}s "
                f"(running limit {running_max}s) — assuming a hung solver. "
                "Pre-paid credits refunded."
            ),
        )
        return "failed", refunded

    if state in _FAILED_STATES:
        refunded = _fail_and_refund(
            db,
            execution,
            (
                "Reaped: the solve task failed without updating this execution "
                "(worker killed or task revoked). Pre-paid credits refunded."
            ),
        )
        return "failed", refunded

    # PENDING / unknown backend state / no celery_task_id at all.
    threshold = running_max if execution.status == ExecutionStatus.RUNNING.value else pending_max
    if age_seconds <= threshold:
        return "skipped", 0
    refunded = _fail_and_refund(
        db,
        execution,
        (
            f"Reaped: stuck in '{execution.status}' for {int(age_seconds)}s with no "
            "result in the task backend (lost task or expired result). "
            "Pre-paid credits refunded."
        ),
    )
    return "failed", refunded


def reap_stale_executions(db: Session) -> dict[str, Any]:
    """Sweep stale pending/running ModelExecution rows. Commits per row.

    Per-row commit isolation: one poisoned row (e.g. concurrent lock, frozen
    org) is rolled back and logged without aborting the rest of the sweep.
    """
    pending_max = PSS.get_int(db, "EXECUTION_REAPER_PENDING_MAX_SECONDS")
    running_max = PSS.get_int(db, "EXECUTION_REAPER_RUNNING_MAX_SECONDS")
    now = utcnow().replace(tzinfo=None)
    min_age = min(pending_max, running_max)

    candidates = (
        db.query(ModelExecution)
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
        "refunded_credits": 0,
    }

    for execution in candidates:
        try:
            outcome, refunded = _reap_one(db, execution, now, pending_max, running_max)
            db.commit()
            summary[outcome] += 1
            summary["refunded_credits"] += refunded
        except Exception as exc:
            db.rollback()
            summary["errors"] += 1
            logger.error("Reaper failed on execution %s: %s", execution.id, exc, exc_info=True)

    if summary["failed"] or summary["completed"] or summary["errors"]:
        logger.info("Execution reaper sweep: %s", summary)
    return summary


@celery_app.task(bind=True, name="reap_stale_executions", acks_late=True)  # type: ignore[misc]
def reap_stale_executions_task(self: Any) -> dict[str, Any]:
    """Thin Celery wrapper — owns the session lifecycle, delegates to the impl."""
    db = SessionLocal()
    try:
        return reap_stale_executions(db)
    except Exception as exc:
        logger.error("Execution reaper task failed: %s", exc, exc_info=True)
        raise
    finally:
        db.close()


__all__ = [
    "reap_stale_executions",
    "reap_stale_executions_task",
]
