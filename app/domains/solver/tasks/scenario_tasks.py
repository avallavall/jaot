"""Celery task for the on-demand what-if batch (Sensitivity L2).

The batch is minutes of solving — one full re-solve per scenario — so it never
runs inside a request. It runs here, on the solver queue of the execution's own
solver, writes its result onto the execution row, and is bounded by the platform
budget settings (which also derive this task's soft/hard kill limits).
"""

import logging
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from app.domains.solver import scenario_job
from app.domains.solver.services import get_solver_service
from app.domains.solver.services.execution_payload import (
    ExecutionPayloadError,
    load_execution_payload,
)
from app.domains.solver.services.scenario_analysis import (
    ScenarioBudget,
    compute_scenario_analysis,
)
from app.domains.solver.tasks.solve_tasks import _assert_queue_match
from app.models import ModelExecution
from app.schemas.optimization import OptimizationProblem, ScenarioAnalysis
from app.shared.core.celery_app import celery_app
from app.shared.db.session import SessionLocal

logger = logging.getLogger(__name__)


def read_budget(db: Any) -> ScenarioBudget:
    """Build the batch budget from the platform settings.

    Read at the producer AND consumer: the API needs the total to derive the
    task's kill limits, the worker needs the whole shape. Reading it twice is
    cheaper than threading a settings blob through the queue, and an admin edit
    between the two only changes the batch's own ceiling.
    """
    from app.services.platform_settings_service import PlatformSettingsService as PSS

    return ScenarioBudget(
        max_resolves=PSS.get_int(db, "SENSITIVITY_MAX_RESOLVES"),
        top_constraints=PSS.get_int(db, "SENSITIVITY_TOP_CONSTRAINTS"),
        top_decisions=PSS.get_int(db, "SENSITIVITY_TOP_DECISIONS"),
        per_solve_multiplier=PSS.get_float(db, "SENSITIVITY_PER_SOLVE_MULTIPLIER"),
        per_solve_cap_seconds=PSS.get_int(db, "SENSITIVITY_PER_SOLVE_CAP_SECONDS"),
        total_seconds=PSS.get_int(db, "SENSITIVITY_TOTAL_BUDGET_SECONDS"),
    )


@celery_app.task(bind=True, name="scenario_analysis_async")  # type: ignore[misc]
def scenario_analysis_async(
    self: Any,
    execution_id: str,
    organization_id: str,
    solver_name: str | None = None,
) -> dict[str, Any]:
    """Run the what-if batch for one completed execution and cache it on the row."""
    task_id = self.request.id
    logger.info("Starting scenario analysis %s for execution %s", task_id, execution_id)

    db = SessionLocal()
    try:
        _assert_queue_match(solver_name)

        execution = (
            db.query(ModelExecution)
            .filter(
                ModelExecution.id == execution_id,
                ModelExecution.organization_id == organization_id,
            )
            .first()
        )
        if not execution:
            raise ValueError(f"Execution {execution_id} not found")

        try:
            payload = load_execution_payload(execution.input_data, execution.result_data)
        except ExecutionPayloadError as exc:
            _persist(db, execution, analysis=ScenarioAnalysis(computed=False, note=exc.reason))
            return {"status": "success", "execution_id": execution_id, "computed": False}

        budget = read_budget(db)
        service = get_solver_service(solver_name=solver_name or execution.solver_name)

        def _solve(problem: OptimizationProblem, warm_start: dict[str, float] | None):
            return service.solve(problem, warm_start_solution=warm_start)

        base_seconds = (execution.execution_time_ms or 0) / 1000.0 or None
        started = time.monotonic()
        analysis = compute_scenario_analysis(
            payload.problem,
            payload.solution,
            solve=_solve,
            objective_value=payload.objective_value,
            base_solve_seconds=base_seconds,
            budget=budget,
        )
        logger.info(
            "Scenario analysis %s ran %d re-solves in %.1fs (partial=%s)",
            task_id,
            analysis.resolves_used,
            time.monotonic() - started,
            analysis.partial,
        )
        _persist(db, execution, analysis=analysis)
        return {
            "status": "success",
            "execution_id": execution_id,
            "computed": analysis.computed,
            "resolves_used": analysis.resolves_used,
            "partial": analysis.partial,
        }

    except Exception as exc:
        # SoftTimeLimitExceeded carries no message of its own; the budget is the
        # story, so say that instead of showing the user an empty error.
        detail = (
            "The what-if analysis exceeded its time budget and was stopped."
            if isinstance(exc, SoftTimeLimitExceeded)
            else str(exc)
        )
        logger.error("Scenario analysis %s failed: %s", task_id, detail)
        _mark_failed(db, execution_id, organization_id, detail)
        return {"status": "error", "execution_id": execution_id, "error": detail}
    finally:
        db.close()


def _persist(db: Any, execution: ModelExecution, *, analysis: ScenarioAnalysis) -> None:
    """Write the finished analysis into the execution's job envelope."""
    job = execution.scenario_analysis or scenario_job.running_job(None, 0.0)
    execution.scenario_analysis = scenario_job.completed_job(job, analysis)
    db.commit()


def _mark_failed(db: Any, execution_id: str, organization_id: str, error: str) -> None:
    """Best-effort terminal write so the row never stays 'running' forever."""
    try:
        db.rollback()
        execution = (
            db.query(ModelExecution)
            .filter(
                ModelExecution.id == execution_id,
                ModelExecution.organization_id == organization_id,
            )
            .first()
        )
        if execution is None:
            return
        job = execution.scenario_analysis or scenario_job.running_job(None, 0.0)
        execution.scenario_analysis = scenario_job.failed_job(job, error)
        db.commit()
    except Exception as exc:  # pragma: no cover - the failure path's own failure
        logger.warning("Could not record scenario-analysis failure for %s: %s", execution_id, exc)
