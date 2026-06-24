"""Producer-side queue routing for Celery solver tasks.

Maps a ``solver_name`` string to the Celery queue its worker consumes from.
Pure function, no Celery import — enables fast unit tests.
"""

from app.domains.solver.adapters.base import DEFAULT_SOLVER_NAME, SolverNotFoundError

SOLVER_QUEUE_MAP: dict[str, str] = {
    "scip": "solve_scip",
    "highs": "solve_highs",
    # Phase 7 — D-17. WR-03 guard at resolve_queue below preserved:
    # the generic "Unknown solver" message never enumerates installed
    # commercial solvers, so landing "hexaly" here does NOT leak which
    # deployments have the commercial SDK installed.
    "hexaly": "solve_hexaly",
}


def resolve_queue(solver_name: str | None) -> str:
    """Map a solver name to the Celery queue its worker consumes from.

    Raises ``SolverNotFoundError`` when ``solver_name`` is unknown; callers
    let it propagate and the existing handler translates it to HTTP 422.

    WR-03 (Phase 6): the error message intentionally omits the list of
    supported solvers. Once commercial/licensed solvers (hexaly, gurobi,
    cplex) land in SOLVER_QUEUE_MAP, leaking the list via 422 responses
    would reveal which licensed solvers are installed on this deployment.
    Clients that need the list should hit GET /api/v2/solvers/available
    (authenticated) instead.
    """
    effective = solver_name or DEFAULT_SOLVER_NAME
    try:
        return SOLVER_QUEUE_MAP[effective]
    except KeyError as exc:
        raise SolverNotFoundError(f"Unknown solver '{effective}'.") from exc
