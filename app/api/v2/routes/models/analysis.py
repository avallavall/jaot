"""Post-solve analysis endpoints for an execution.

Split out of ``execution.py`` (backend audit D-19). That module is where the
marketplace execution flow lives — preview, execute, poll, cancel, list — and the
analysis endpoints kept accreting on the end of it as Sensitivity L1/L2 landed, taking
it past 800 lines of two unrelated concerns.

Routes, operation ids and tags are unchanged: this is a move, not a redesign. The
router is mounted after ``execution``'s in the package's router so ``/executions/all``
keeps matching before ``/executions/{execution_id}/…``.
"""

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v2.auth import get_current_user
from app.api.v2.routes.models._access import execution_or_404
from app.domains.solver import scenario_job
from app.domains.solver.adapters.base import SolverNotFoundError
from app.domains.solver.queue_routing import resolve_queue
from app.domains.solver.services.exact_analysis import compute_exact_analysis
from app.domains.solver.services.execution_payload import (
    ExecutionPayloadError,
    load_execution_payload,
)
from app.domains.solver.tasks.scenario_tasks import read_budget, scenario_analysis_async
from app.domains.solver.time_limits import compute_celery_time_limits
from app.models import User
from app.schemas.optimization import (
    ExactAnalysis,
    ScenarioAnalysis,
    ScenarioAnalysisJob,
)
from app.shared.db.base import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["execution"])


@router.get(
    "/executions/{execution_id}/exact-analysis",
    operation_id="get_execution_exact_analysis",
)
def get_execution_exact_analysis(  # sync ON PURPOSE -> threadpool (CPU-bound, no awaits)
    execution_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExactAnalysis:
    """Exact, solution-based analysis of a completed execution (A3).

    Computed on demand from the stored problem + solution — binding constraints,
    slack/utilization, objective contributions — all exact for the integer
    solution, unlike the LP-relaxation shadow prices. Off the solve path because
    it re-parses every constraint — and a sync ``def`` so that re-parse (up to
    thousands of constraints) runs in the threadpool, never on the event loop.
    """
    execution = execution_or_404(db, execution_id, current_user.organization_id)

    try:
        payload = load_execution_payload(execution.input_data, execution.result_data)
    except ExecutionPayloadError as exc:
        return ExactAnalysis(computed=False, note=exc.reason)

    return compute_exact_analysis(
        payload.problem, payload.solution, objective_value=payload.objective_value
    )


@router.post(
    "/executions/{execution_id}/scenario-analysis",
    operation_id="start_execution_scenario_analysis",
    status_code=status.HTTP_202_ACCEPTED,
)
def start_execution_scenario_analysis(
    execution_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScenarioAnalysisJob:
    """Queue the what-if batch for a completed execution (Sensitivity L2).

    Each scenario is a full re-solve, so the batch runs on the solver queue
    under a wall-clock budget, never in this request. Requesting it twice does
    NOT start two batches: the row is locked, and a batch already in flight is
    returned as-is. A finished batch is served from the cache.
    """
    # Validate what the batch would work on BEFORE claiming anything, so an
    # unanalysable execution is refused without leaving a "running" mark behind.
    execution = execution_or_404(db, execution_id, current_user.organization_id)

    try:
        payload = load_execution_payload(execution.input_data, execution.result_data)
    except ExecutionPayloadError as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc

    solver_name = execution.solver_name or payload.problem.solver_name
    try:
        queue = resolve_queue(solver_name)
    except SolverNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    budget = read_budget(db)
    # The batch's own budget derives the worker kill limits, exactly as a
    # solve's time limit does — a hung analysis must not pin a worker.
    soft_limit, hard_limit = compute_celery_time_limits(db, budget.total_seconds)

    # Pre-generate the task id (P1.5 F0 pattern) so the claim already carries it:
    # writing it back AFTER dispatch would race the worker, which on a small model
    # can finish the whole batch before this request returns — and that second
    # write would overwrite the finished result with a "running" envelope.
    celery_task_id = str(uuid4())

    # Claim under the row lock BEFORE dispatching: the lock is what makes two
    # simultaneous requests one batch, and a claim without a task (dispatch
    # failure) ages out via ``is_running`` instead of blocking the button.
    execution, job, claimed = scenario_job.claim_batch(
        db, execution_id, current_user.organization_id, budget.total_seconds, celery_task_id
    )
    db.commit()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    if not claimed:
        # Joining the batch in flight (or reading the cached answer) — either way
        # the caller gets the same envelope the GET would give it.
        return _scenario_job_response(job)

    scenario_analysis_async.apply_async(
        args=[execution_id, current_user.organization_id, solver_name],
        task_id=celery_task_id,
        queue=queue,
        soft_time_limit=soft_limit,
        time_limit=hard_limit,
    )
    return _scenario_job_response(job)


@router.get(
    "/executions/{execution_id}/scenario-analysis",
    operation_id="get_execution_scenario_analysis",
)
def get_execution_scenario_analysis(
    execution_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScenarioAnalysisJob:
    """Read the cached what-if batch of an execution (Sensitivity L2)."""
    execution = execution_or_404(db, execution_id, current_user.organization_id)

    return _scenario_job_response(execution.scenario_analysis or {})


def _scenario_job_response(job: dict[str, Any]) -> ScenarioAnalysisJob:
    """Envelope -> API job. A stale 'running' row reads as absent, so the UI
    offers the button again instead of spinning on a batch that died."""
    status_value = job.get("status")
    if status_value == scenario_job.STATUS_RUNNING and not scenario_job.is_running(job):
        status_value = None
    analysis = job.get("result")
    return ScenarioAnalysisJob(
        status=status_value or "absent",
        analysis=ScenarioAnalysis.model_validate(analysis) if analysis else None,
        error=job.get("error"),
        requested_at=job.get("requested_at"),
        completed_at=job.get("completed_at"),
        # The cached explanation MUST ride along: this read is what the page does
        # on load, and without it a reload would show no explanation and offer to
        # bill another one for text we already have.
        explanation=job.get("explanation"),
        explained_at=job.get("explained_at"),
    )
