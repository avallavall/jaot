"""Solve support module — validation, provenance and warm-start helpers.

The in-request orchestrator class died with ADR-007 (async-only executions);
what remains here are the shared pieces the async pipeline itself imports:
``validate_problem``, ``ExecutionSource``/``ORIGIN_*`` provenance, variable
name extraction and warm-start loading.
"""

import logging
import re
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import ModelExecution
from app.schemas.optimization import (
    OptimizationProblem,
)

logger = logging.getLogger(__name__)

# Execution provenance — how a solve was created and the object it traces back
# to. This is a platform concern, deliberately kept OUT of the solver-agnostic
# OptimizationProblem/Result schemas. Persisted on ModelExecution.origin /
# source_kind / source_id (see the 20260628_exec_provenance migration).
ORIGIN_MANUAL = "manual"
ORIGIN_VISUAL_BUILDER = "visual_builder"
ORIGIN_AI_BUILDER = "ai_builder"
ORIGIN_TEMPLATE = "template"
ORIGIN_IMPORT = "import"
ORIGIN_MARKETPLACE = "marketplace"
# "triggered" (not "trigger") to match the value triggers already write — avoids
# splitting historical rows across two slugs.
ORIGIN_TRIGGER = "triggered"
ORIGIN_API = "api"
ORIGIN_MCP = "mcp"

VALID_ORIGINS = frozenset(
    {
        ORIGIN_MANUAL,
        ORIGIN_VISUAL_BUILDER,
        ORIGIN_AI_BUILDER,
        ORIGIN_TEMPLATE,
        ORIGIN_IMPORT,
        ORIGIN_MARKETPLACE,
        ORIGIN_TRIGGER,
        ORIGIN_API,
        ORIGIN_MCP,
    }
)

# The object an execution can navigate back to. Generic (not FKs) because
# builder_document / llm_conversation / template have no FK on model_executions.
VALID_SOURCE_KINDS = frozenset(
    {
        "builder_document",
        "llm_conversation",
        "template",
        "organization_model",
        "trigger",
        "imported_file",
        # P1a: a solve launched from a first-class ModelProject. Code-only addition
        # — the source_kind column is already VARCHAR(32), so no DB change is needed.
        "model_project",
    }
)

_SOURCE_ID_MAX_LEN = 64  # matches ModelExecution.source_id column width


@dataclass(frozen=True)
class ExecutionSource:
    """Provenance of a solve: its creation channel and the object it came from.

    ``origin`` is the channel (``visual_builder``, ``ai_builder``, ``template``…).
    ``source_kind``/``source_id`` point at the object the execution can navigate
    back to. All fields default so callers without provenance fall back to a
    plain manual solve.
    """

    origin: str = ORIGIN_MANUAL
    source_kind: str | None = None
    source_id: str | None = None

    @classmethod
    def from_request(
        cls,
        origin: str | None,
        source_kind: str | None = None,
        source_id: str | None = None,
    ) -> "ExecutionSource":
        """Build from untrusted query params, sanitising unknown values.

        Unknown origins collapse to ``manual`` and unknown source kinds to
        ``None`` so a client cannot write arbitrary strings into the executions
        table; ``source_id`` is dropped when there is no valid kind and capped
        to the column width.
        """
        clean_origin = origin if origin in VALID_ORIGINS else ORIGIN_MANUAL
        clean_kind = source_kind if source_kind in VALID_SOURCE_KINDS else None
        clean_id = None
        if clean_kind and source_id:
            clean_id = source_id[:_SOURCE_ID_MAX_LEN]
        return cls(origin=clean_origin, source_kind=clean_kind, source_id=clean_id)


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
    """Validate optimization problem before solving. Raises HTTPException if invalid."""
    variable_names = {v.name for v in problem.variables}

    obj_vars = extract_variable_names(problem.objective.expression)
    invalid_obj_vars = obj_vars - variable_names
    if invalid_obj_vars:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Objective references undefined variables: {invalid_obj_vars}",
        )

    for i, constraint in enumerate(problem.constraints):
        constraint_vars = extract_variable_names(constraint.expression)
        invalid_vars = constraint_vars - variable_names
        if invalid_vars:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Constraint {constraint.name or i} references "
                    f"undefined variables: {invalid_vars}"
                ),
            )

    for var in problem.variables:
        if var.lower_bound is not None and var.upper_bound is not None:
            if var.lower_bound > var.upper_bound:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Variable {var.name} has invalid bounds: "
                        f"{var.lower_bound} > {var.upper_bound}"
                    ),
                )

        if var.type.value == "binary":
            if var.lower_bound is not None and var.lower_bound < 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Binary variable {var.name} cannot have lower bound < 0",
                )
            if var.upper_bound is not None and var.upper_bound > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Binary variable {var.name} cannot have upper bound > 1",
                )


def extract_variable_names(expression: str) -> set[str]:
    """Extract variable names from a mathematical expression."""
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expression)
    return {t for t in tokens if t not in _EXCLUDED_TOKENS}


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
