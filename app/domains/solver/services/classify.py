"""Problem-class classification — the single source of truth.

``classify(problem)`` returns the optimization class (LP / MILP / IP / BIP / QP /
MIQP / QCP / MIQCP) from the solver-agnostic :class:`OptimizationProblem`. It is
consumed by **both** the auto-router (so routing decisions never re-derive the
class) and the :class:`ModelStatsService` (so the Analyze surface and the router
provably agree). This kills a real "solve-contract drift" vector — the class logic
lived in two places (``auto_router._has_quadratic`` and the stats path).

The expression parser caps degree at 2, so general nonlinear (MINLP) is
unreachable by construction; that is surfaced as an explicit capability boundary
(``MAX_REPRESENTABLE_DEGREE``), not a silent gap.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from app.schemas.optimization import OptimizationProblem, VariableType

if TYPE_CHECKING:  # pragma: no cover
    from app.domains.solver.services.expression_parser import ExpressionParser

# Degree the expression parser can represent. Terms above this raise on parse, so a
# classified problem is always linear or quadratic — never MINLP.
MAX_REPRESENTABLE_DEGREE = 2


class ProblemClass(str, Enum):
    """Optimization problem class. String-valued for direct JSON serialization."""

    LP = "LP"  # linear, all continuous
    MILP = "MILP"  # linear, mixed integer + continuous
    IP = "IP"  # linear, all integer
    BIP = "BIP"  # linear, all binary
    QP = "QP"  # quadratic objective, all continuous
    MIQP = "MIQP"  # quadratic objective, has integer/binary
    QCP = "QCP"  # quadratic constraints, all continuous
    MIQCP = "MIQCP"  # quadratic constraints, has integer/binary


def _has_integrality(problem: OptimizationProblem) -> bool:
    return any(v.type in (VariableType.INTEGER, VariableType.BINARY) for v in problem.variables)


def classify(
    problem: OptimizationProblem,
    parser: ExpressionParser | None = None,
) -> ProblemClass:
    """Classify ``problem`` into a :class:`ProblemClass`.

    Pure + deterministic. Raises ``ParseError`` (``ValueError`` subclass) on a
    malformed objective/constraint expression — same contract the auto-router's
    ``_has_quadratic`` had, so routing behaviour is unchanged. Callers that
    classify *unvalidated* drafts (e.g. the live-stats path) should catch it.

    Quadratic detection uses :meth:`ParsedExpression.is_linear` as the single
    source of truth: ``x*x`` / ``x**2`` / ``2*x*x`` all consolidate to one bilinear
    term after parsing, and ``is_linear`` is False for any term with >1 variable.
    """
    if parser is None:
        from app.domains.solver.services.expression_parser import (  # noqa: PLC0415
            ExpressionParser,
        )

        parser = ExpressionParser()

    # A SET on purpose: the parser adopts it without copying, so classifying a
    # 100k-constraint problem stays linear instead of O(constraints x variables).
    known = {v.name for v in problem.variables}

    quad_obj = not parser.parse_expression(
        problem.objective.expression, known_variables=known
    ).is_linear()

    quad_con = any(
        not parser.parse_constraint(c.expression, known_variables=known).lhs.is_linear()
        for c in problem.constraints
    )

    has_int = _has_integrality(problem)

    if quad_con:
        return ProblemClass.MIQCP if has_int else ProblemClass.QCP
    if quad_obj:
        return ProblemClass.MIQP if has_int else ProblemClass.QP

    # Linear from here.
    if not has_int:
        return ProblemClass.LP

    has_continuous = any(v.type == VariableType.CONTINUOUS for v in problem.variables)
    if not has_continuous:
        all_binary = all(v.type == VariableType.BINARY for v in problem.variables)
        return ProblemClass.BIP if all_binary else ProblemClass.IP

    return ProblemClass.MILP


# Quadratic classes — the auto-router routes these to a quadratic-capable solver.
QUADRATIC_CLASSES = frozenset(
    {ProblemClass.QP, ProblemClass.MIQP, ProblemClass.QCP, ProblemClass.MIQCP}
)


__all__ = ["ProblemClass", "classify", "QUADRATIC_CLASSES", "MAX_REPRESENTABLE_DEGREE"]
