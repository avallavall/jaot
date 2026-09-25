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

from app.domains.solver.services.problem_validation import (
    InvalidProblemError,
    extract_variable_names,
    validate_problem as domain_validate_problem,
)
from app.domains.solver.warm_start import load_warm_start_solution
from app.schemas.optimization import (
    OptimizationProblem,
)
from app.shared.constants.execution_provenance import ExecutionSource
from app.shared.core.http_errors import CodedHTTPException

__all__ = [
    "ExecutionSource",
    "extract_variable_names",
    "invalid_problem_http",
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
        raise invalid_problem_http(exc) from exc


def invalid_problem_http(exc: InvalidProblemError) -> HTTPException:
    """The 400 for an invalid problem: the English detail, plus the issue's code.

    ``detail`` is unchanged for API and MCP clients. The code is what a page
    renders, in the reader's language, instead of a message that prints a
    Python set or the parser's own diagnostic.
    """
    if exc.code:
        return CodedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.detail,
            code=exc.code,
            params=exc.params,
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.detail)


# Re-exported, not reimplemented. This module used to carry a second copy of the
# loader, and the copy the solve task actually calls carried a third; both read
# the wrong key. One implementation lives in the solver domain now.
