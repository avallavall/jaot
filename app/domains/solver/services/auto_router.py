"""Auto-routing decision logic — Phase 7.4 / D-11 / D-13 / INT-01.

Pure function :func:`select_solver` returning ``(solver_name, reason,
fallback_triggered)``. No DB access — Hexaly availability is determined by a
runtime probe of the Celery worker (``_probe_hexaly_worker`` in
``app.domains.solver.services.worker_health``).

Decision tree (post-Phase-7.4):

    1. All variables CONTINUOUS AND no quadratic terms anywhere -> ``"highs"``
       reason="lp_routed_to_highs", fallback_triggered=False
    2. Any quadratic term AND Hexaly worker available -> ``"hexaly"``
       reason="quadratic_routed_to_hexaly", fallback_triggered=False
    3. Any quadratic term AND Hexaly worker unavailable -> ``"scip"``
       reason="hexaly_unavailable_fallback", fallback_triggered=True
       (sync/async caller surfaces a `warning` field on the response — D-11)
    4. Otherwise (MIP / mixed) -> ``"scip"``
       reason="milp_routed_to_scip", fallback_triggered=False

Reason slugs are stable public contract (D-13) — exposed to UI; do not
rename without updating frontend locale strings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domains.solver.adapters.base import HEXALY_SOLVER_NAME
from app.schemas.optimization import OptimizationProblem, VariableType

if TYPE_CHECKING:  # pragma: no cover
    from app.domains.solver.services.expression_parser import ExpressionParser

logger = logging.getLogger(__name__)


# Reason slugs (D-13). Stable public contract — frontend locale strings key
# off these.
AUTO_REASON_LP = "lp_routed_to_highs"
AUTO_REASON_QUADRATIC = "quadratic_routed_to_hexaly"
AUTO_REASON_FALLBACK = "hexaly_unavailable_fallback"
AUTO_REASON_MIP = "milp_routed_to_scip"


def _has_quadratic(problem: OptimizationProblem, parser: ExpressionParser) -> bool:
    """True iff any term (objective or constraint LHS) references >=2 variables.

    Uses :meth:`ParsedExpression.is_linear` as the single source of truth
    (Pitfall 5 — x*x / x**2 / 2*x*x all consolidate to one bilinear term
    after parsing; ``is_linear`` returns False for any term with
    ``len(variables) > 1``).
    """
    known = [v.name for v in problem.variables]
    parsed_obj = parser.parse_expression(problem.objective.expression, known_variables=known)
    if not parsed_obj.is_linear():
        return True
    for constraint in problem.constraints:
        parsed_c = parser.parse_constraint(constraint.expression, known_variables=known)
        if not parsed_c.lhs.is_linear():
            return True
    return False


def _is_pure_lp(problem: OptimizationProblem) -> bool:
    """True when every decision variable is CONTINUOUS (no INTEGER / BINARY)."""
    return all(v.type == VariableType.CONTINUOUS for v in problem.variables)


def select_solver(
    problem: OptimizationProblem,
    parser: ExpressionParser | None = None,
) -> tuple[str, str, bool]:
    """Select the best solver per the Phase 7.4 decision tree.

    Args:
        problem: The optimization problem to classify.
        parser: Optional :class:`ExpressionParser` override. Defaults to a
            fresh instance (lazy-imported to keep ``auto_router`` import
            cheap).

    Returns:
        Tuple ``(solver_name, reason, fallback_triggered)``:
          - ``solver_name``: one of ``"highs"``, ``"hexaly"``, ``"scip"``.
          - ``reason``: one of the four :data:`AUTO_REASON_*` constants.
          - ``fallback_triggered``: True iff Hexaly was the preferred choice
            but the worker was unavailable; the caller MUST surface a
            ``warning`` field on the solve response per D-11.

    Pure function: deterministic given (problem, worker-availability snapshot).
    No DB access. No multi-tenancy concerns (no org-scoped reads).
    """
    if parser is None:
        from app.domains.solver.services.expression_parser import (  # noqa: PLC0415
            ExpressionParser,
        )

        parser = ExpressionParser()

    has_quadratic = _has_quadratic(problem, parser)
    pure_lp = _is_pure_lp(problem)

    # 1. LP -> HiGHS
    if pure_lp and not has_quadratic:
        return ("highs", AUTO_REASON_LP, False)

    # 2 + 3. Quadratic — check worker, fall back to SCIP if down (D-11).
    # Probe the source-level helper directly so a single mock target covers
    # both this routing decision AND the post-routing availability gate
    # (availability_gate.ensure_hexaly_worker_or_503 calls _probe_hexaly_worker
    # too; tests that mock at one layer but not the other surface 503 in a
    # 422-expecting test).
    if has_quadratic:
        from app.domains.solver.services.worker_health import (  # noqa: PLC0415
            _probe_hexaly_worker,
        )

        healthy, probe_msg = _probe_hexaly_worker()
        if healthy:
            return (HEXALY_SOLVER_NAME, AUTO_REASON_QUADRATIC, False)
        logger.warning(
            "auto_router: Hexaly worker unavailable (%s), falling back to SCIP "
            "for quadratic problem (D-11 explicit fallback).",
            probe_msg or "no diagnostic message",
        )
        return ("scip", AUTO_REASON_FALLBACK, True)

    # 4. MIP / mixed default
    return ("scip", AUTO_REASON_MIP, False)


__all__ = [
    "AUTO_REASON_FALLBACK",
    "AUTO_REASON_LP",
    "AUTO_REASON_MIP",
    "AUTO_REASON_QUADRATIC",
    "select_solver",
]
