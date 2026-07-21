"""Exact, solution-based analysis (A3 + Sensitivity L1).

Binding constraints, slack/utilization per constraint (b_i − a_i·x*), and
objective contributions (c_j·x*_j) — all computed from the solution x* and the
problem data, so they are EXACT for the integer solution and solver-agnostic,
unlike LP-relaxation shadow prices (which are duals of a different, easier
problem and near-uniform under degeneracy).

Sensitivity L1 layers family-level KPIs on top: constraint rows and objective
terms aggregate by their recovered FAMILY (authoritative from the JModel
compiler, best-effort ``parse_flat_name`` otherwise — the exact contract of
``annotate_variable_structure``), computed over ALL analysed rows/terms rather
than the capped display lists, so the aggregates hold at model scale.

Run ON DEMAND, never on the solve path: it re-parses every constraint, which is
the expensive part on large models. The constraint list is bounded and the
returned rows are capped, so a pathological model degrades to a truncated view
rather than a slow request.
"""

from app.domains.solver.services.expression_parser import ExpressionParser, ParseError
from app.schemas.optimization import (
    Constraint,
    ConstraintFamilyStats,
    ConstraintUtilization,
    ExactAnalysis,
    ObjectiveFamilyContribution,
    ObjectiveTermContribution,
    OptimizationProblem,
)
from app.schemas.solution_structure import parse_flat_name

# Slack/contribution smaller than this is treated as zero (binding / negligible).
_EPS = 1e-6
# Bound worst-case latency: analyse at most this many constraints, return at most
# this many rows (binding + tightest first), objective terms, and family groups.
_MAX_CONSTRAINTS = 5000
_MAX_ROWS = 200
_MAX_CONTRIBUTIONS = 100
_MAX_FAMILIES = 100


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


def _constraint_family(constraint: Constraint, authoritative: bool) -> str | None:
    """Family of one row, honouring the ``annotate_variable_structure`` contract:
    when ANY row carries a compiler-set family, unannotated rows are genuine
    scalars — never second-guessed by the name heuristic."""
    if constraint.family:
        return constraint.family
    if authoritative or not constraint.name:
        return None
    parsed = parse_flat_name(constraint.name)
    return parsed[0] if parsed else None


def _variable_families(problem: OptimizationProblem) -> dict[str, str]:
    """Map variable name → family, authoritative-first (same contract as above)."""
    if any(v.family for v in problem.variables):
        return {v.name: v.family for v in problem.variables if v.family}
    out: dict[str, str] = {}
    for v in problem.variables:
        parsed = parse_flat_name(v.name)
        if parsed is not None:
            out[v.name] = parsed[0]
    return out


def compute_exact_analysis(
    problem: OptimizationProblem,
    solution: dict[str, float],
    *,
    objective_value: float | None = None,
) -> ExactAnalysis:
    """Exact binding/slack/utilization + objective contributions at ``solution``."""
    parser = ExpressionParser()
    known = set(solution)
    authoritative = any(c.family for c in problem.constraints)

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
                family=_constraint_family(constraint, authoritative),
            )
        )

    binding_count = sum(1 for r in rows if r.is_binding)
    # Aggregate BEFORE the row cap — the KPIs must describe the whole model.
    families, truncated_families = _family_stats(rows)
    # Binding first, then tightest (smallest |slack|) — the informative rows lead.
    rows.sort(key=lambda r: (not r.is_binding, abs(r.slack)))
    truncated_constraints = truncated_constraints or len(rows) > _MAX_ROWS

    contributions, contribution_families = _objective_contributions(parser, problem, solution)
    truncated_contributions = len(contributions) > _MAX_CONTRIBUTIONS
    truncated_families = truncated_families or len(contribution_families) > _MAX_FAMILIES

    return ExactAnalysis(
        objective_value=objective_value,
        total_constraints=total,
        binding_count=binding_count,
        constraints=rows[:_MAX_ROWS],
        contributions=contributions[:_MAX_CONTRIBUTIONS],
        families=families,
        contribution_families=contribution_families[:_MAX_FAMILIES],
        truncated_constraints=truncated_constraints,
        truncated_contributions=truncated_contributions,
        truncated_families=truncated_families,
        computed=True,
    )


def _family_stats(rows: list[ConstraintUtilization]) -> tuple[list[ConstraintFamilyStats], bool]:
    """Per-family binding/slack/utilization KPIs, tightest families first."""
    by_family: dict[str, list[ConstraintUtilization]] = {}
    for row in rows:
        if row.family:
            by_family.setdefault(row.family, []).append(row)

    stats: list[ConstraintFamilyStats] = []
    for family, members in by_family.items():
        slacks = [m.slack for m in members]
        utils = [m.utilization for m in members if m.utilization is not None]
        stats.append(
            ConstraintFamilyStats(
                family=family,
                total=len(members),
                binding_count=sum(1 for m in members if m.is_binding),
                slack_min=min(slacks),
                slack_mean=sum(slacks) / len(slacks),
                slack_max=max(slacks),
                utilization_mean=sum(utils) / len(utils) if utils else None,
                utilization_max=max(utils) if utils else None,
            )
        )
    # Most saturated families lead; the headroom ranking reads bottom-up.
    stats.sort(key=lambda s: (-(s.binding_count / s.total), s.slack_min, s.family))
    return stats[:_MAX_FAMILIES], len(stats) > _MAX_FAMILIES


def _objective_contributions(
    parser: ExpressionParser,
    problem: OptimizationProblem,
    solution: dict[str, float],
) -> tuple[list[ObjectiveTermContribution], list[ObjectiveFamilyContribution]]:
    """Per-term c_j·x*_j plus the same totals rolled up by variable family."""
    try:
        parsed = parser.parse_expression(problem.objective.expression, set(solution))
    except (ParseError, ValueError, ZeroDivisionError):
        return [], []
    var_families = _variable_families(problem)
    # Merge like terms by label ("2*x + 3*x" is ONE x row) — the panel keys rows
    # by label, and two rows with the same name would both collide and mislead.
    by_label: dict[str, float] = {}
    # Family totals accumulate EVERY term (no _EPS filter per term) so the family
    # figure is the true total, not a sum of the rows that happened to display.
    by_family: dict[str, tuple[float, int]] = {}
    for term in parsed.terms:
        if not term.variables:
            continue
        value = term.coefficient
        for var in term.variables:
            value *= solution.get(var, 0.0)
        label = " · ".join(term.variables)
        by_label[label] = by_label.get(label, 0.0) + value
        # A term belongs to a family only when ALL its variables agree on one —
        # a bilinear cross-family term has no honest single owner.
        term_families = {var_families.get(var) for var in term.variables}
        if len(term_families) == 1 and (family := term_families.pop()) is not None:
            prev_value, prev_terms = by_family.get(family, (0.0, 0))
            by_family[family] = (prev_value + value, prev_terms + 1)
    out = [
        ObjectiveTermContribution(label=label, contribution=value)
        for label, value in by_label.items()
        if abs(value) >= _EPS
    ]
    out.sort(key=lambda o: abs(o.contribution), reverse=True)
    family_out = [
        ObjectiveFamilyContribution(family=family, contribution=value, terms=terms)
        for family, (value, terms) in by_family.items()
        if abs(value) >= _EPS
    ]
    family_out.sort(key=lambda o: abs(o.contribution), reverse=True)
    return out, family_out
