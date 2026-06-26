"""Infeasibility analysis (IIS) — solver-agnostic deletion filtering.

When a model is INFEASIBLE the solver only tells the user "no solution". This
module finds *why*: a minimal subset of constraints (and/or variable bounds) that
are mutually unsatisfiable — an Irreducible Infeasible Set (IIS). Drop any single
member and the model becomes feasible.

Method: **deletion filtering**. Starting from the full set of removable items
(constraints + finite variable bounds), each item is tentatively removed and the
model re-solved as a pure *feasibility* problem (objective replaced by the
constant ``0``, so the solve can only return OPTIMAL=feasible or INFEASIBLE,
never UNBOUNDED). If the model stays infeasible without the item, the item is
redundant and dropped; otherwise it is required and kept. What remains is a
minimal conflicting set.

This is intentionally solver-agnostic: it only calls ``SolverService.solve`` on
freshly built ``OptimizationProblem`` candidates and never touches a solver's
native API — so it satisfies import-linter contract 5 (services ↛ pyscipopt) and
works for any registered adapter.

Cost is O(n) re-solves, so callers bound it with a constraint cap and a wall-clock
time budget (``IIS_MAX_CONSTRAINTS`` / ``IIS_TIME_BUDGET_SECONDS`` platform
settings). When either bound is hit the analysis falls back to ``method="llm_only"``
and the LLM reasons heuristically over the formulation instead.

Note: plain deletion filtering returns *a* minimal conflicting set, not
necessarily the smallest one — that is the documented, accepted trade-off.
"""

from __future__ import annotations

import logging
import time

from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import (
    InfeasibilityAnalysis,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    SolverStatus,
    Variable,
)

logger = logging.getLogger(__name__)

# Pure-feasibility objective: a constant, so a candidate solve can only come back
# OPTIMAL (feasible region non-empty) or INFEASIBLE — never UNBOUNDED. This keeps
# deletion filtering's "is it still infeasible?" question unambiguous.
_FEASIBILITY_OBJECTIVE = Objective(sense=ObjectiveSense.MINIMIZE, expression="0")

# A bound is a (kind, variable_name) pair where kind is "lb" or "ub".
_BoundItem = tuple[str, str]
# An item in the removable universe: a constraint index or a bound.
_Item = tuple[str, object]


def _constraint_name(problem: OptimizationProblem, index: int) -> str:
    """Stable display name for a constraint, matching the adapter's ``c{i}`` fallback."""
    name = problem.constraints[index].name
    return name if name else f"c{index}"


def _bound_label(problem: OptimizationProblem, item: _BoundItem) -> str:
    """Render a bound item as a human-readable inequality (e.g. ``x >= 10``)."""
    kind, var_name = item
    var = next((v for v in problem.variables if v.name == var_name), None)
    if var is None:
        return var_name
    if kind == "lb":
        return f"{var_name} >= {var.lower_bound}"
    return f"{var_name} <= {var.upper_bound}"


def _removable_bounds(problem: OptimizationProblem) -> list[_BoundItem]:
    """Finite, relaxable variable bounds eligible for deletion filtering.

    Only continuous/integer variables with an explicit finite bound qualify.
    Binary variables are excluded: their 0/1 domain is intrinsic to the type and
    cannot be relaxed by clearing a numeric bound.
    """
    bounds: list[_BoundItem] = []
    for var in problem.variables:
        if var.type.value == "binary":
            continue
        if var.lower_bound is not None:
            bounds.append(("lb", var.name))
        if var.upper_bound is not None:
            bounds.append(("ub", var.name))
    return bounds


def _build_candidate(
    problem: OptimizationProblem,
    active_constraint_indices: set[int],
    removable_bounds: set[_BoundItem],
    active_bounds: set[_BoundItem],
    per_solve_limit: float,
) -> OptimizationProblem:
    """Build a feasibility candidate keeping only the active constraints/bounds.

    A removable bound that is *not* in ``active_bounds`` is relaxed to ``None``
    (unbounded). Bounds outside ``removable_bounds`` (e.g. binary domains, or
    bounds that were ``None`` to begin with) are always preserved as-is.
    """
    variables: list[Variable] = []
    for var in problem.variables:
        lb = var.lower_bound
        ub = var.upper_bound
        if ("lb", var.name) in removable_bounds and ("lb", var.name) not in active_bounds:
            lb = None
        if ("ub", var.name) in removable_bounds and ("ub", var.name) not in active_bounds:
            ub = None
        variables.append(var.model_copy(update={"lower_bound": lb, "upper_bound": ub}))

    constraints = [problem.constraints[i] for i in sorted(active_constraint_indices)]

    return OptimizationProblem(
        name=f"{problem.name or 'model'}_iis_candidate",
        variables=variables,
        objective=_FEASIBILITY_OBJECTIVE,
        constraints=constraints,
        options=SolverOptions(time_limit_seconds=per_solve_limit),
        solver_name=problem.solver_name,
    )


def _classify(iis_constraints: list[str], iis_bounds: list[str]) -> str:
    """Map the surviving IIS members to a conflict_type discriminator."""
    if iis_constraints and iis_bounds:
        return "mixed"
    if iis_constraints:
        return "constraint"
    if iis_bounds:
        return "bound"
    return "unknown"


def compute_iis(
    problem: OptimizationProblem,
    solver: SolverService,
    *,
    max_constraints: int,
    time_budget_s: float,
    solver_name: str | None = None,
) -> InfeasibilityAnalysis:
    """Compute a minimal infeasible subset (IIS) by deletion filtering.

    Args:
        problem: The infeasible problem to analyse. The objective is ignored —
            every candidate solve is a pure feasibility check.
        solver: Solver orchestrator used to re-solve candidates (agnostic).
        max_constraints: Cap on the removable-item universe (constraints + finite
            bounds). Above it, exact IIS is skipped → ``method="llm_only"``.
        time_budget_s: Wall-clock budget for the whole search. Exceeding it mid
            search aborts to ``method="llm_only"``.
        solver_name: Optional explicit solver to use for every candidate solve.

    Returns:
        An :class:`InfeasibilityAnalysis`. ``method="iis"`` carries the conflicting
        constraint names / bound labels; ``method="llm_only"`` signals the caller
        to fall back to heuristic LLM reasoning, with ``note`` explaining why.
    """
    try:
        return _compute_iis_inner(
            problem,
            solver,
            max_constraints=max_constraints,
            time_budget_s=time_budget_s,
            solver_name=solver_name,
        )
    except Exception as exc:  # best-effort: never let IIS failure mask the result
        logger.warning("IIS computation failed, falling back to llm_only: %s", exc)
        return InfeasibilityAnalysis(
            method="llm_only",
            conflict_type="unknown",
            note="Exact infeasibility analysis failed; reasoning heuristically instead.",
        )


def _compute_iis_inner(
    problem: OptimizationProblem,
    solver: SolverService,
    *,
    max_constraints: int,
    time_budget_s: float,
    solver_name: str | None,
) -> InfeasibilityAnalysis:
    removable_bounds = _removable_bounds(problem)
    removable_bounds_set = set(removable_bounds)
    constraint_indices = list(range(len(problem.constraints)))
    universe_size = len(constraint_indices) + len(removable_bounds)

    # Cap the cost: each item costs one extra re-solve.
    if universe_size > max_constraints:
        return InfeasibilityAnalysis(
            method="llm_only",
            conflict_type="unknown",
            note=(
                f"Model too large for exact IIS ({universe_size} constraints/bounds "
                f"> cap {max_constraints}); reasoning heuristically instead."
            ),
        )

    # Each candidate gets a tight per-solve limit so one slow re-solve cannot
    # consume the whole budget. At least 1s (SolverOptions minimum).
    per_solve_limit = max(1.0, min(5.0, float(time_budget_s)))
    start = time.monotonic()

    def _solve_feasibility(
        active_constraints: set[int], active_bounds: set[_BoundItem]
    ) -> SolverStatus:
        candidate = _build_candidate(
            problem, active_constraints, removable_bounds_set, active_bounds, per_solve_limit
        )
        result = solver.solve(candidate, solver_name=solver_name)
        return result.status

    # --- Step 1: confirm the full model really is infeasible ---
    all_constraints = set(constraint_indices)
    all_bounds = set(removable_bounds)
    full_status = _solve_feasibility(all_constraints, all_bounds)
    if full_status != SolverStatus.INFEASIBLE:
        if full_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
            return InfeasibilityAnalysis(
                method="iis",
                conflict_type="unknown",
                note="Model is feasible — there is no infeasibility to explain.",
            )
        return InfeasibilityAnalysis(
            method="llm_only",
            conflict_type="unknown",
            note=(
                "Could not confirm infeasibility within the time limit; "
                "reasoning heuristically instead."
            ),
        )

    # --- Step 2: deletion filtering over the combined item universe ---
    # Ordered so the working set updates in place; constraints first, then bounds.
    items: list[_Item] = [("c", i) for i in constraint_indices]
    items += [("bound", b) for b in removable_bounds]

    working_constraints = set(constraint_indices)
    working_bounds = set(removable_bounds)

    for kind, payload in items:
        if time.monotonic() - start > time_budget_s:
            return InfeasibilityAnalysis(
                method="llm_only",
                conflict_type="unknown",
                note=(
                    "Time budget exceeded during exact IIS search; reasoning heuristically instead."
                ),
            )

        if kind == "c":
            idx = payload  # constraint index
            trial_constraints = working_constraints - {idx}
            status = _solve_feasibility(trial_constraints, working_bounds)
            if status == SolverStatus.INFEASIBLE:
                # Still infeasible without it → redundant, drop it.
                working_constraints = trial_constraints
        else:
            bound = payload  # _BoundItem
            trial_bounds = working_bounds - {bound}
            status = _solve_feasibility(working_constraints, trial_bounds)
            if status == SolverStatus.INFEASIBLE:
                working_bounds = trial_bounds

    iis_constraints = [_constraint_name(problem, i) for i in sorted(working_constraints)]
    iis_bounds = [_bound_label(problem, b) for b in removable_bounds if b in working_bounds]

    note = None
    if not iis_constraints and not iis_bounds:
        note = (
            "Infeasibility is not attributable to any single constraint or bound "
            "(e.g. integrality requirements)."
        )

    return InfeasibilityAnalysis(
        iis_constraints=iis_constraints,
        iis_variable_bounds=iis_bounds,
        conflict_type=_classify(iis_constraints, iis_bounds),
        method="iis",
        note=note,
    )
