"""Auto-generated insights for optimization results.

Analyzes a solved OptimizationResult + the original problem definition
to produce human-readable insights about the solution quality, binding
constraints, variable utilization, and improvement suggestions.

Each insight carries BOTH an English `message` and a machine-readable
`code` + `params`. The message is the wire value API and MCP clients read;
the code is what a localized interface renders, so the same analysis can be
shown in the reader's language without the solver domain owning translations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.domains.solver.services.file_export import extract_solution
from app.schemas.optimization import OptimizationProblem

InsightCategory = Literal["objective", "constraints", "variables", "performance"]
InsightSeverity = Literal["info", "warning", "success"]


@dataclass(frozen=True)
class Insight:
    """A single auto-generated insight."""

    category: InsightCategory
    message: str
    severity: InsightSeverity = "info"
    #: Stable identifier for this insight, so a UI can localize it. Percentages
    #: and gaps travel in `params` as fractions (0.4, not 40) — the renderer picks
    #: the notation, which is the part that differs between locales.
    code: str = ""
    params: dict[str, Any] = field(default_factory=dict)


def generate_insights(
    problem: OptimizationProblem,
    result_data: dict,
) -> list[Insight]:
    """Generate insights from a completed solve.

    Args:
        problem: The original optimization problem.
        result_data: The stored result_data from ModelExecution.

    Returns:
        List of Insight objects sorted by relevance.
    """
    insights: list[Insight] = []

    solution = extract_solution(result_data)
    objective_value = result_data.get("objective_value")
    solver_status = result_data.get("solver_status", "")
    gap = result_data.get("gap")
    solve_time = result_data.get("solve_time_seconds")

    # --- Objective insights ---
    if objective_value is not None:
        sense = problem.objective.sense.value
        insights.append(
            Insight(
                category="objective",
                message=f"Optimal {sense}d value: {objective_value:,.6g}",
                severity="success" if solver_status == "optimal" else "info",
                code=f"objective.optimal_value.{sense}",
                params={"value": objective_value},
            )
        )

    if solver_status == "optimal":
        insights.append(
            Insight(
                category="objective",
                message="Solution is globally optimal — no better feasible solution exists.",
                severity="success",
                code="objective.globally_optimal",
            )
        )
    elif solver_status == "feasible":
        insights.append(
            Insight(
                category="objective",
                message="Solution is feasible but may not be globally optimal. "
                "Consider increasing the time limit.",
                severity="warning",
                code="objective.feasible_not_proven",
            )
        )
    elif solver_status == "infeasible":
        insights.append(
            Insight(
                category="objective",
                message="Problem is infeasible — no solution satisfies all constraints. "
                "Review constraint definitions for contradictions.",
                severity="warning",
                code="objective.infeasible",
            )
        )
    elif solver_status == "unbounded":
        insights.append(
            Insight(
                category="objective",
                message="Problem is unbounded — the objective can be improved indefinitely. "
                "Check for missing variable bounds or constraints.",
                severity="warning",
                code="objective.unbounded",
            )
        )

    # --- MIP gap insight ---
    if gap is not None and gap > 0.001:
        insights.append(
            Insight(
                category="performance",
                message=f"MIP gap is {gap:.2%}. The solution may be improvable — "
                "consider increasing the time limit or relaxing gap tolerance.",
                severity="warning",
                code="performance.gap_improvable",
                params={"gap": gap},
            )
        )
    elif gap is not None and gap <= 0.001:
        insights.append(
            Insight(
                category="performance",
                message=f"MIP gap is {gap:.4%} — effectively optimal.",
                severity="success",
                code="performance.gap_negligible",
                params={"gap": gap},
            )
        )

    # --- Solve time insight ---
    if solve_time is not None:
        if solve_time < 1.0:
            insights.append(
                Insight(
                    category="performance",
                    message=f"Solved in {solve_time:.2f}s — very fast.",
                    severity="info",
                    code="performance.solved_fast",
                    params={"seconds": solve_time},
                )
            )
        elif solve_time > 60.0:
            insights.append(
                Insight(
                    category="performance",
                    message=f"Solve took {solve_time:.1f}s. For faster results, "
                    "consider reducing the problem size or relaxing gap tolerance.",
                    severity="warning",
                    code="performance.solved_slow",
                    params={"seconds": solve_time},
                )
            )

    # --- Variable insights ---
    if solution and problem.variables:
        _analyze_variables(insights, problem, solution)

    # --- Sensitivity insights ---
    sensitivity = result_data.get("sensitivity")
    if sensitivity and isinstance(sensitivity, dict):
        _analyze_sensitivity(insights, sensitivity)

    return insights


def _analyze_variables(
    insights: list[Insight],
    problem: OptimizationProblem,
    solution: dict,
) -> None:
    """Analyze variable values for bound saturation and type distribution."""
    at_lower = 0
    at_upper = 0
    zero_count = 0
    total = len(problem.variables)

    type_counts = {"binary": 0, "integer": 0, "continuous": 0}

    for var in problem.variables:
        value = solution.get(var.name)
        if value is None:
            continue

        type_counts[var.type.value] += 1

        if var.lower_bound is not None and abs(value - var.lower_bound) < 1e-6:
            at_lower += 1
        if var.upper_bound is not None and abs(value - var.upper_bound) < 1e-6:
            at_upper += 1
        if abs(value) < 1e-6:
            zero_count += 1

    at_bounds = at_lower + at_upper
    if at_bounds > 0:
        pct = at_bounds / total * 100
        insights.append(
            Insight(
                category="variables",
                message=f"{at_bounds} of {total} variables ({pct:.0f}%) are at their bounds. "
                "Relaxing these bounds could improve the objective.",
                severity="warning" if pct > 50 else "info",
                code="variables.at_bounds",
                params={"count": at_bounds, "total": total, "share": at_bounds / total},
            )
        )

    if zero_count > 0 and zero_count < total:
        pct = zero_count / total * 100
        insights.append(
            Insight(
                category="variables",
                message=f"{zero_count} of {total} variables ({pct:.0f}%) are zero in the solution.",
                severity="info",
                code="variables.zero_valued",
                params={"count": zero_count, "total": total, "share": zero_count / total},
            )
        )

    # Type distribution summary
    parts = []
    for vtype, count in type_counts.items():
        if count > 0:
            parts.append(f"{count} {vtype}")
    if len(parts) > 1:
        insights.append(
            Insight(
                category="variables",
                message=f"Variable mix: {', '.join(parts)}.",
                severity="info",
                code="variables.type_mix",
                # Counts, not a joined phrase: the type names and the way a list is
                # punctuated ("a, b and c" / "a, b y c") both belong to the renderer.
                params={vtype: count for vtype, count in type_counts.items() if count > 0},
            )
        )


def _analyze_sensitivity(
    insights: list[Insight],
    sensitivity: dict,
) -> None:
    """Analyze sensitivity/shadow price data."""
    constraints = sensitivity.get("constraints", [])
    if not constraints:
        return

    binding = [c for c in constraints if c.get("is_binding")]
    total = len(constraints)

    if binding:
        pct = len(binding) / total * 100
        insights.append(
            Insight(
                category="constraints",
                message=f"{len(binding)} of {total} constraints ({pct:.0f}%) are binding "
                "(active at optimality).",
                severity="info",
                code="constraints.binding",
                params={"count": len(binding), "total": total, "share": len(binding) / total},
            )
        )

    # Most impactful constraint by shadow price
    with_price = [
        c
        for c in constraints
        if c.get("shadow_price") is not None and abs(c["shadow_price"]) > 1e-8
    ]
    if with_price:
        top = max(with_price, key=lambda c: abs(c["shadow_price"]))
        insights.append(
            Insight(
                category="constraints",
                message=f'Most impactful constraint: "{top.get("name", "?")}" '
                f"(shadow price: {top['shadow_price']:.4g}). "
                "Relaxing this constraint would most improve the objective.",
                severity="info",
                code="constraints.most_impactful",
                params={"name": top.get("name", "?"), "shadowPrice": top["shadow_price"]},
            )
        )
