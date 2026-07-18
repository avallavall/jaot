"""Exact, solution-based analysis (A3).

Binding constraints, slack/utilization per constraint (b_i − a_i·x*), and
objective contributions (c_j·x*_j) — all computed from the solution x* and the
problem data, so they are EXACT for the integer solution and solver-agnostic,
unlike LP-relaxation shadow prices (which are duals of a different, easier
problem and near-uniform under degeneracy).

Run ON DEMAND, never on the solve path: it re-parses every constraint, which is
the expensive part on large models. The constraint list is bounded and the
returned rows are capped, so a pathological model degrades to a truncated view
rather than a slow request.
"""

from app.domains.solver.services.expression_parser import ExpressionParser, ParseError
from app.schemas.optimization import (
    ConstraintUtilization,
    ExactAnalysis,
    ObjectiveTermContribution,
    OptimizationProblem,
)

# Slack/contribution smaller than this is treated as zero (binding / negligible).
_EPS = 1e-6
# Bound worst-case latency: analyse at most this many constraints, return at most
# this many rows (binding + tightest first) and objective terms.
_MAX_CONSTRAINTS = 5000
_MAX_ROWS = 200
_MAX_CONTRIBUTIONS = 100


def _activity(terms: list, solution: dict[str, float]) -> float:
    """Evaluate a parsed LHS (constants already moved to the RHS) at x*."""
    total = 0.0
    for term in terms:
        if not term.variables:
            total += term.coefficient
            continue
        value = term.coefficient
        for var in term.variables:
            value *= solution.get(var, 0.0)
        total += value
    return total


def compute_exact_analysis(
    problem: OptimizationProblem,
    solution: dict[str, float],
    *,
    objective_value: float | None = None,
) -> ExactAnalysis:
    """Exact binding/slack/utilization + objective contributions at ``solution``."""
    parser = ExpressionParser()
    known = set(solution)

    total = len(problem.constraints)
    truncated_constraints = total > _MAX_CONSTRAINTS
    rows: list[ConstraintUtilization] = []
    for i, constraint in enumerate(problem.constraints[:_MAX_CONSTRAINTS]):
        try:
            parsed = parser.parse_constraint(constraint.expression, known)
        except (ParseError, ValueError, ZeroDivisionError):
            continue  # best-effort: an unparseable constraint is skipped, not fatal
        activity = _activity(parsed.lhs.terms, solution)
        rhs = parsed.rhs
        op = parsed.operator
        if op in ("<=", "<"):
            slack = rhs - activity
        elif op in (">=", ">"):
            slack = activity - rhs
        else:  # == : distance from equality
            slack = abs(activity - rhs)
        is_binding = abs(slack) < _EPS
        utilization = activity / rhs if op in ("<=", "<") and abs(rhs) > 1e-12 else None
        rows.append(
            ConstraintUtilization(
                name=constraint.name or f"c{i + 1}",
                activity=activity,
                rhs=rhs,
                operator=op,
                slack=slack,
                is_binding=is_binding,
                utilization=utilization,
            )
        )

    binding_count = sum(1 for r in rows if r.is_binding)
    # Binding first, then tightest (smallest |slack|) — the informative rows lead.
    rows.sort(key=lambda r: (not r.is_binding, abs(r.slack)))
    truncated_constraints = truncated_constraints or len(rows) > _MAX_ROWS

    contributions = _objective_contributions(parser, problem, solution)
    truncated_contributions = len(contributions) > _MAX_CONTRIBUTIONS

    return ExactAnalysis(
        objective_value=objective_value,
        total_constraints=total,
        binding_count=binding_count,
        constraints=rows[:_MAX_ROWS],
        contributions=contributions[:_MAX_CONTRIBUTIONS],
        truncated_constraints=truncated_constraints,
        truncated_contributions=truncated_contributions,
        computed=True,
    )


def _objective_contributions(
    parser: ExpressionParser,
    problem: OptimizationProblem,
    solution: dict[str, float],
) -> list[ObjectiveTermContribution]:
    """Per-term c_j·x*_j, non-negligible, sorted by |contribution| descending."""
    try:
        parsed = parser.parse_expression(problem.objective.expression, set(solution))
    except (ParseError, ValueError, ZeroDivisionError):
        return []
    out: list[ObjectiveTermContribution] = []
    for term in parsed.terms:
        if not term.variables:
            continue
        value = term.coefficient
        for var in term.variables:
            value *= solution.get(var, 0.0)
        if abs(value) < _EPS:
            continue
        out.append(ObjectiveTermContribution(label=" · ".join(term.variables), contribution=value))
    out.sort(key=lambda o: abs(o.contribution), reverse=True)
    return out
