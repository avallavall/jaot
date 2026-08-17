"""Loading a previous run's solution to seed the next one.

One implementation, called from the Celery task that solves and re-exported by
``app.services.solve_orchestrator`` for the callers that already import it from
there. It used to be two copies of the same twenty lines, and both of them read
the wrong key, so warm start had been silently dead: the solution is stored
under ``model`` (that is what ``OptimizationResult.to_result_data()`` writes),
and both copies asked for ``solution``.

Nothing failed visibly. The loader logs a warning and returns None, the solve
runs cold, and the response comes back with ``warm_start_used: false`` and no
explanation. It looked like "the solver chose not to use it".
"""

from __future__ import annotations

import logging
from typing import Any

from app.models import ExecutionStatus, ModelExecution

logger = logging.getLogger(__name__)

#: Verdicts that carry a usable assignment. An infeasible or errored run has
#: nothing to seed the next solve with.
_USABLE_VERDICTS = frozenset({"optimal", "feasible"})


def load_warm_start_solution(
    db: Any,
    execution_id: str,
    organization_id: str,
) -> dict[str, float] | None:
    """The assignment a previous execution found, or None.

    Never raises: a warm start is an optimization, so a failure to load one
    must cost the caller a cold solve and nothing else.

    Cross-org access returns None rather than 404. The caller is a solve, not a
    lookup, and telling one organization that another's execution id exists is
    the whole of the leak.
    """
    try:
        execution = db.query(ModelExecution).filter(ModelExecution.id == execution_id).first()
        if execution is None:
            logger.warning("Warm start execution not found: %s", execution_id)
            return None
        if execution.organization_id != organization_id:
            logger.warning("Warm start execution %s belongs to another organization", execution_id)
            return None
        if execution.status != ExecutionStatus.COMPLETED.value:
            logger.warning(
                "Warm start execution %s is not completed (status=%s)",
                execution_id,
                execution.status,
            )
            return None
        if execution.solver_status not in _USABLE_VERDICTS:
            logger.warning(
                "Warm start execution %s has no usable solution (solver_status=%s)",
                execution_id,
                execution.solver_status,
            )
            return None

        result_data = execution.result_data or {}
        # ``model`` is the key ``to_result_data()`` writes. ``solution`` is read
        # too, the same tolerance ``file_export`` keeps, in case a row predates
        # the key settling — no row in this database has one, so it costs a
        # dictionary lookup and covers an installation whose history is older.
        solution = result_data.get("model") or result_data.get("solution")
        if not solution or not isinstance(solution, dict):
            logger.warning("Warm start execution %s stored no assignment", execution_id)
            return None

        logger.info("Loaded warm start solution from execution %s", execution_id)
        return {name: float(value) for name, value in solution.items()}
    except Exception as exc:  # a warm start must never break the solve
        logger.warning("Failed to load warm start solution: %s", exc)
        return None


__all__ = ["load_warm_start_solution"]
