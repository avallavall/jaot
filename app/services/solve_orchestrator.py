"""Solve support module — validation and warm-start helpers.

The in-request orchestrator class died with ADR-007 (async-only executions);
what remains here are the shared pieces the async pipeline itself imports:
``validate_problem``, variable name extraction and warm-start loading.

Provenance (``ExecutionSource``/``ORIGIN_*``) moved to
``app.shared.constants.execution_provenance``: the solver domain's own routes
label the solves they start, and importing two string constants from a service
module made them depend upward on the platform (D-16).
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.domains.solver.services.problem_validation import (
    InvalidProblemError,
    extract_variable_names,
    validate_problem as domain_validate_problem,
)
from app.models import ModelExecution
from app.schemas.optimization import (
    OptimizationProblem,
)
from app.shared.constants.execution_provenance import ExecutionSource

__all__ = [
    "ExecutionSource",
    "extract_variable_names",
    "load_warm_start_solution",
    "validate_problem",
]

logger = logging.getLogger(__name__)

_DEFAULT_SOURCE = ExecutionSource()

# Variable name tokens excluded from expression parsing
_EXCLUDED_TOKENS = {
    "sin",
    "cos",
    "tan",
    "exp",
    "log",
    "sqrt",
    "abs",
    "min",
    "max",
    "sum",
}


# Standalone validation helpers (importable without instantiating class)


def validate_problem(problem: OptimizationProblem) -> None:
    """Validate an optimization problem. Raises HTTPException 400 if invalid.

    The checks themselves are the solver domain's — a malformed problem is
    malformed whoever is asked to solve it. This is the HTTP face of them, kept
    here so every API caller keeps the same status and the same message.
    """
    try:
        domain_validate_problem(problem)
    except InvalidProblemError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail) from exc


def load_warm_start_solution(
    db: Session,
    execution_id: str,
    org_id: str,
) -> dict[str, float] | None:
    """Load a warm start solution from a previous execution.

    Returns the solution dict if valid, else None. Never raises.
    """
    try:
        execution = db.query(ModelExecution).filter(ModelExecution.id == execution_id).first()
        if not execution:
            logger.warning("Warm start execution not found: %s", execution_id)
            return None
        if execution.organization_id != org_id:
            logger.warning("Warm start execution %s belongs to different org", execution_id)
            return None
        if execution.status not in ("completed",):
            logger.warning(
                "Warm start execution %s not completed (status=%s)",
                execution_id,
                execution.status,
            )
            return None
        if execution.solver_status not in ("optimal", "feasible"):
            logger.warning(
                "Warm start execution %s has no valid solution (solver_status=%s)",
                execution_id,
                execution.solver_status,
            )
            return None
        result_data = execution.result_data or {}
        solution = result_data.get("solution")
        if not solution or not isinstance(solution, dict):
            logger.warning("Warm start execution %s has no solution dict", execution_id)
            return None
        logger.info("Loaded warm start solution from execution %s", execution_id)
        return {k: float(v) for k, v in solution.items()}
    except Exception as e:
        logger.warning("Failed to load warm start solution: %s", e)
        return None
