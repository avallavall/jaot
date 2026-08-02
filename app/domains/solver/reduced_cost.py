"""One definition of "reduced cost", derived from the duals we publish.

A reduced cost and a shadow price answer the same question from two sides: what
one more unit is worth. Read together — and the Sensitivity tab shows them on the
same screen — they must add up. SCIP's ``getVarRedcost`` does not, once a cap is
written as a *row* instead of a column bound.

Measured 2026-08-02, same model both ways (``max 3x + 2y + z`` s.t. ``x + y <= 4``,
``y + z <= 6``, ``x`` capped at 3):

    cap on x is a…   duals                      rc(x) published   rc(x) implied
    row              c1=1, c2=1, cap_x=2        2.0               0.0
    column bound     c1=1, c2=1                 2.0               2.0

With the cap as a row SCIP bills the same 2 twice: once as the row's dual and again
as the variable's reduced cost. HiGHS, on the same two models, reports 0.0 and 2.0 —
it is right both times. So this was not a house-style choice between conventions:
the default solver disagreed with the other solver and with its own duals, and
capping by rows is the ordinary way to write a model.

Deriving from the duals we already publish keeps the two numbers consistent by
construction, and costs nothing — the coefficients are parsed anyway to build the
model. The identity is the textbook one, for the sign convention JAOT publishes
duals in (positive for a binding ``<=`` row, whatever the objective sense):

    rc_j = c_j - sum_i y_i * a_ij

Only linear models qualify. With a quadratic term there is no single a_ij to price
against, so the caller keeps whatever the solver said rather than being handed a
derived number that quietly ignores the cross terms.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domains.solver.services.expression_parser import ExpressionParser
from app.schemas.optimization import OptimizationProblem


def _linear_coefficients(terms: list) -> dict[str, float] | None:
    """Collapse parsed terms to ``{variable: coefficient}``, or None if quadratic."""
    coefficients: dict[str, float] = {}
    for term in terms:
        if len(term.variables) > 1:
            return None
        if term.variables:
            coefficients[term.variables[0]] = coefficients.get(term.variables[0], 0.0) + float(
                term.coefficient
            )
    return coefficients


def derive_reduced_costs(
    problem: OptimizationProblem,
    shadow_prices: Mapping[str, float | None],
    parser: ExpressionParser,
) -> dict[str, float]:
    """Reduced costs implied by ``shadow_prices``, keyed by variable name.

    Returns an empty dict when the model is not linear, or when any constraint's
    dual is missing — a partial derivation would silently drop a row's price and
    read as a confident number.
    """
    names = {v.name for v in problem.variables}
    objective = parser.parse_expression(problem.objective.expression, names)
    costs = _linear_coefficients(objective.terms)
    if costs is None:
        return {}

    reduced: dict[str, float] = {name: costs.get(name, 0.0) for name in names}
    for constraint in problem.constraints:
        dual = shadow_prices.get(constraint.name)
        if dual is None:
            return {}
        if dual == 0.0:
            continue  # a free row prices nothing; skip the parse
        parsed = parser.parse_constraint(constraint.expression, names)
        coefficients = _linear_coefficients(parsed.lhs.terms)
        if coefficients is None:
            return {}
        for name, coefficient in coefficients.items():
            if name in reduced:
                reduced[name] -= dual * coefficient
    return reduced
