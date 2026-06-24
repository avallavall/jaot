"""Auto-generated insights for optimization results.

Analyzes a solved OptimizationResult + the original problem definition
to produce human-readable insights about the solution quality, binding
constraints, variable utilization, and improvement suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
            )
        )

    if solver_status == "optimal":
        insights.append(
            Insight(
                category="objective",
                message="Solution is globally optimal — no better feasible solution exists.",
                severity="success",
            )
        )
    elif solver_status == "feasible":
        insights.append(
            Insight(
                category="objective",
                message="Solution is feasible but may not be globally optimal. "
                "Consider increasing the time limit.",
                severity="warning",
            )
        )
    elif solver_status == "infeasible":
        insights.append(
            Insight(
                category="objective",
                message="Problem is infeasible — no solution satisfies all constraints. "
                "Review constraint definitions for contradictions.",
                severity="warning",
            )
        )
    elif solver_status == "unbounded":
        insights.append(
            Insight(
                category="objective",
                message="Problem is unbounded — the objective can be improved indefinitely. "
                "Check for missing variable bounds or constraints.",
                severity="warning",
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
            )
        )
    elif gap is not None and gap <= 0.001:
        insights.append(
            Insight(
                category="performance",
                message=f"MIP gap is {gap:.4%} — effectively optimal.",
                severity="success",
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
                )
            )
        elif solve_time > 60.0:
            insights.append(
                Insight(
                    category="performance",
                    message=f"Solve took {solve_time:.1f}s. For faster results, "
                    "consider reducing the problem size or relaxing gap tolerance.",
                    severity="warning",
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
            )
        )

    if zero_count > 0 and zero_count < total:
        pct = zero_count / total * 100
        insights.append(
            Insight(
                category="variables",
                message=f"{zero_count} of {total} variables ({pct:.0f}%) are zero in the solution.",
                severity="info",
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
            )
        )
