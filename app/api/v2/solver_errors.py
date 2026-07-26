"""One HTTP shape for every "you cannot have that solver" outcome (D-05 / WR-03).

``GET /solvers/available`` lists only adapters whose ``is_available()`` is true, so a
commercial solver that is registered but unlicensed is deliberately absent from it.
The exception messages gave that back: ``SolverNotFoundError`` says a name is not
registered while ``SolverUnavailableError`` says it *is* registered but unavailable,
and both reached the client verbatim through ``detail=str(exc)``. Probing names
therefore enumerated which commercial solvers the deployment carries — licensing
information about the operator, not about the caller's request.

Both now produce the same 422 body. The distinction survives in the server log,
where it is a diagnostic rather than an oracle.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app.domains.solver.adapters.base import SolverNotFoundError, SolverUnavailableError

logger = logging.getLogger(__name__)

# Deliberately says nothing about whether the name is registered.
_UNIFORM_DETAIL = "Solver '{name}' is not available."


def solver_unavailable(
    exc: SolverNotFoundError | SolverUnavailableError,
    solver_name: str | None,
) -> HTTPException:
    """Build the 422 to raise for an unusable solver, logging the real reason.

    Pass the name the caller asked for; it is echoed back because the caller
    already knows it, unlike the registry's contents.
    """
    name = solver_name or "unknown"
    logger.info(
        "Solver request refused: name=%r reason=%s",
        name,
        type(exc).__name__,
        exc_info=True,
    )
    # 422 as a literal: starlette deprecated HTTP_422_UNPROCESSABLE_ENTITY and the
    # replacement name is not in every version this runs against.
    return HTTPException(status_code=422, detail=_UNIFORM_DETAIL.format(name=name))
