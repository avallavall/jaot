"""HiGHS adapter — highspy implementation of SolverAdapter.

Phase 5 / HIGH-01. Single-file adapter mirroring SCIPAdapter structure.
HiGHS expression building uses sparse column-index arrays, not expression tree
objects, so no helper split is needed (simpler than SCIP).

IMPORTANT: highspy is imported LAZILY inside is_available() and solve() only.
Do NOT add 'import highspy' at module level — it would crash at startup when
highspy is not installed.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.domains.solver.adapters.base import STRICT_EPSILON, SolverCapabilities
from app.domains.solver.services.expression_parser import ExpressionParser
from app.schemas.optimization import (
    ConstraintSensitivity,
    OptimizationProblem,
    OptimizationResult,
    SensitivityResult,
    SolverStatus,
    Variable,
    VariableSensitivity,
    VariableSolution,
    VariableType,
)

if TYPE_CHECKING:
    pass  # highspy types referenced via strings only — no top-level import

logger = logging.getLogger(__name__)

# Sentinel for unbounded bounds — highspy uses 1e30 (kHighsInf)
_HIGHS_INF = 1e30


# Map HiGHS modelStatusToString() output → SolverStatus.
# NOTE: modelStatusToString() returns human-readable strings like "Optimal",
# NOT enum key names like "kOptimal". Verified against highspy 1.12.x at runtime.
_HIGHS_STATUS_MAP: dict[str, SolverStatus] = {
    "Optimal": SolverStatus.OPTIMAL,
    "Infeasible": SolverStatus.INFEASIBLE,
    "Primal infeasible or unbounded": SolverStatus.INFEASIBLE,
    "Unbounded": SolverStatus.UNBOUNDED,
    "Bound on objective reached": SolverStatus.OPTIMAL,
    "Target for objective reached": SolverStatus.OPTIMAL,
    "Solution limit reached": SolverStatus.TIME_LIMIT,
    "Iteration limit reached": SolverStatus.TIME_LIMIT,
    "Time limit reached": SolverStatus.TIME_LIMIT,
    "Memory limit reached": SolverStatus.ERROR,
    "Not Set": SolverStatus.ERROR,
    "Empty": SolverStatus.ERROR,
    "Load error": SolverStatus.ERROR,
    "Model error": SolverStatus.ERROR,
    "Solve error": SolverStatus.ERROR,
    "Presolve error": SolverStatus.ERROR,
    "Postsolve error": SolverStatus.ERROR,
    "Interrupted by user": SolverStatus.TIME_LIMIT,
    "Interrupted by HiGHS": SolverStatus.TIME_LIMIT,
    "Unknown": SolverStatus.ERROR,
}


class HiGHSAdapter:
    """HiGHS solver adapter implementing SolverAdapter Protocol.

    Uses highspy Python bindings (MIT license, ~15MB footprint).
    highspy is imported lazily to avoid startup crashes when not installed.
    """

    capabilities: SolverCapabilities = SolverCapabilities(
        name="highs",
        supports_continuous=True,
        supports_integer=True,
        supports_binary=True,
        supports_quadratic=False,
        supports_sensitivity=True,
        supports_warm_start=False,
        supports_multi_objective=False,
        # Phase 7.4 / D-10: requires_license removed — no per-request gate
    )

    def __init__(self) -> None:
        self._available: bool | None = None
        self._parser = ExpressionParser()

    def is_available(self) -> bool:
        """Cached import check — same pattern as SCIPAdapter.is_available()."""
        if self._available is None:
            try:
                import highspy  # noqa: F401, PLC0415

                self._available = True
            except ImportError:
                self._available = False
        return self._available  # type: ignore[return-value]

    # Phase 7.4 / D-10: validate_license removed — no per-request gate for HiGHS.

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
    ) -> OptimizationResult:
        """Solve a single-objective optimization problem using HiGHS."""
        import highspy  # noqa: PLC0415 — lazy import; do not move to module level

        if warm_start is not None:
            logger.warning("HiGHS does not support warm start — warm_start argument ignored.")

        start_time = time.time()
        try:
            h = highspy.Highs()
            self._configure_solver(h, problem)

            col_map = self._create_variables(h, highspy, problem.variables)
            self._add_constraints(h, problem.constraints, col_map)
            self._set_objective(h, highspy, problem.objective, col_map)

            h.run()

            solve_time = time.time() - start_time
            return self._extract_result(h, col_map, problem, solve_time)

        except Exception as exc:
            logger.error("HiGHS solver error: %s", exc, exc_info=True)
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.time() - start_time,
                error_message=str(exc),
            )

    def _configure_solver(self, h: object, problem: OptimizationProblem) -> None:
        """Apply solver options from OptimizationProblem.options."""
        import os  # noqa: PLC0415

        opts = problem.options
        h.setOptionValue("output_flag", opts.verbose)  # type: ignore[attr-defined]
        h.setOptionValue("time_limit", float(opts.time_limit_seconds))  # type: ignore[attr-defined]
        h.setOptionValue("mip_rel_gap", float(opts.gap_tolerance))  # type: ignore[attr-defined]
        # Default threads=1 on Windows (thread-safety issue in highspy 1.12-1.13);
        # use 0 (auto) on Linux (production deploy). os.name check avoids a hard import.
        if opts.threads > 0:
            h.setOptionValue("threads", opts.threads)  # type: ignore[attr-defined]
        elif os.name == "nt":
            h.setOptionValue("threads", 1)  # type: ignore[attr-defined]
        # else: Linux — let HiGHS choose automatically

    def _create_variables(
        self,
        h: object,
        highspy_module: object,
        variables: list[Variable],
    ) -> dict[str, int]:
        """Add variables to HiGHS model. Returns col_map: var_name -> column_index."""
        col_map: dict[str, int] = {}
        for idx, var in enumerate(variables):
            lb = var.lower_bound if var.lower_bound is not None else -_HIGHS_INF
            ub = var.upper_bound if var.upper_bound is not None else _HIGHS_INF
            if var.type == VariableType.BINARY:
                lb, ub = 0.0, 1.0
            h.addVar(lb, ub)  # type: ignore[attr-defined]
            if var.type in (VariableType.INTEGER, VariableType.BINARY):
                h.changeColIntegrality(  # type: ignore[attr-defined]
                    idx,
                    highspy_module.HighsVarType.kInteger,  # type: ignore[attr-defined]
                )
            col_map[var.name] = idx
        return col_map

    def _add_constraints(
        self,
        h: object,
        constraints: list,
        col_map: dict[str, int],
    ) -> None:
        """Add constraints to HiGHS model using two-sided row bounds.

        Constraint expressions are in the form "x + 2*y >= 10" — they include
        the operator inline. We use parse_constraint() to split into LHS/operator/RHS.
        """
        for constraint in constraints:
            parsed = self._parser.parse_constraint(constraint.expression)
            indices = []
            coeffs = []
            for term in parsed.lhs.terms:
                if len(term.variables) == 1:
                    var_name = term.variables[0]
                    if var_name in col_map:
                        indices.append(col_map[var_name])
                        coeffs.append(float(term.coefficient))
                # skip quadratic/constant terms (linear problems only here)

            lower, upper = self._operator_bounds(parsed.operator, float(parsed.rhs))
            h.addRow(lower, upper, len(indices), indices, coeffs)  # type: ignore[attr-defined]

    def _operator_bounds(self, operator: str, rhs: float) -> tuple[float, float]:
        """Convert operator + rhs to HiGHS (lower, upper) two-sided bounds."""
        if operator == "<=":
            return (-_HIGHS_INF, rhs)
        if operator == ">=":
            return (rhs, _HIGHS_INF)
        if operator in ("==", "="):
            return (rhs, rhs)
        if operator == "<":
            return (-_HIGHS_INF, rhs - STRICT_EPSILON)
        if operator == ">":
            return (rhs + STRICT_EPSILON, _HIGHS_INF)
        # Fallback: treat as unconstrained (should not happen with validated input)
        logger.warning("Unknown constraint operator %r, treating as unconstrained", operator)
        return (-_HIGHS_INF, _HIGHS_INF)

    def _set_objective(
        self,
        h: object,
        highspy_module: object,
        objective: object,
        col_map: dict[str, int],
    ) -> None:
        """Set objective sense and coefficients."""
        sense_lower = objective.sense.lower()  # type: ignore[attr-defined]
        if sense_lower == "maximize":
            h.changeObjectiveSense(  # type: ignore[attr-defined]
                highspy_module.ObjSense.kMaximize  # type: ignore[attr-defined]
            )
        else:
            h.changeObjectiveSense(  # type: ignore[attr-defined]
                highspy_module.ObjSense.kMinimize  # type: ignore[attr-defined]
            )

        parsed = self._parser.parse_expression(objective.expression)  # type: ignore[attr-defined]
        for term in parsed.terms:
            if len(term.variables) == 1:
                var_name = term.variables[0]
                if var_name in col_map:
                    h.changeColCost(  # type: ignore[attr-defined]
                        col_map[var_name], float(term.coefficient)
                    )

    def _map_status(self, h: object) -> SolverStatus:
        """Map highspy HighsModelStatus to SolverStatus via string name (stable across versions).

        NOTE: modelStatusToString() returns human-readable strings like "Optimal",
        NOT the enum key names like "kOptimal". The _HIGHS_STATUS_MAP uses these
        human-readable strings as keys.
        """
        model_status = h.getModelStatus()  # type: ignore[attr-defined]
        status_str = h.modelStatusToString(model_status)  # type: ignore[attr-defined]
        mapped = _HIGHS_STATUS_MAP.get(status_str)
        if mapped is None:
            logger.warning("Unknown HiGHS status string %r — returning ERROR", status_str)
        return mapped if mapped is not None else SolverStatus.ERROR

    def _extract_result(
        self,
        h: object,
        col_map: dict[str, int],
        problem: OptimizationProblem,
        solve_time: float,
    ) -> OptimizationResult:
        """Extract solution from HiGHS model after h.run()."""
        status = self._map_status(h)

        if status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
            return OptimizationResult(
                status=status,
                solve_time_seconds=solve_time,
            )

        obj_value = h.getObjectiveValue()  # type: ignore[attr-defined]
        sol = h.getSolution()  # type: ignore[attr-defined]
        col_values = list(sol.col_value)

        variable_solutions = []
        solution_dict: dict[str, float] = {}
        for var in problem.variables:
            idx = col_map.get(var.name)
            if idx is not None and idx < len(col_values):
                val = col_values[idx]
                variable_solutions.append(VariableSolution(name=var.name, value=val, type=var.type))
                solution_dict[var.name] = float(val)

        result = OptimizationResult(
            status=status,
            objective_value=float(obj_value),
            solve_time_seconds=solve_time,
            variables=variable_solutions,
            solution=solution_dict,
        )

        # Sensitivity: HiGHS exposes exact LP duals (row_dual) + reduced costs
        # (col_dual). Without this the capability flag `supports_sensitivity=True`
        # was a lie — pure-LP solves auto-routed here came back with no
        # sensitivity, so the UI showed an empty "Sensitivity" tab.
        try:
            result.sensitivity = self._extract_sensitivity(sol, col_map, problem, col_values)
        except Exception as exc:  # never let sensitivity break a valid solve
            logger.warning("HiGHS sensitivity extraction failed: %s", exc)

        return result

    def _extract_sensitivity(
        self,
        sol: object,
        col_map: dict[str, int],
        problem: OptimizationProblem,
        col_values: list[float],
    ) -> SensitivityResult | None:
        """Build a SensitivityResult from HiGHS exact LP duals.

        Returns None (→ no sensitivity persisted) when duals are not meaningful:
        integer/binary problems (HiGHS gives no useful duals for a MIP) or when
        HiGHS reports the dual solution invalid. Duals are exact for LP, so
        ``is_approximate`` is always False here — unlike the SCIP LP-relaxation path.
        """
        # HiGHS duals are only meaningful for a pure LP.
        if any(v.type in (VariableType.INTEGER, VariableType.BINARY) for v in problem.variables):
            return None
        # highspy sets dual_valid=0 when no dual solution is available.
        if not getattr(sol, "dual_valid", 1):
            return None

        row_dual = list(getattr(sol, "row_dual", []) or [])
        col_dual = list(getattr(sol, "col_dual", []) or [])
        if not row_dual and not col_dual:
            return None

        # Rows are added in problem.constraints order (one addRow per constraint),
        # so row index i maps 1:1 to constraints[i].
        constraint_sens: list[ConstraintSensitivity] = []
        for i, constraint in enumerate(problem.constraints):
            shadow_price = float(row_dual[i]) if i < len(row_dual) else None
            is_binding = abs(shadow_price) > 1e-8 if shadow_price is not None else None
            constraint_sens.append(
                ConstraintSensitivity(
                    name=constraint.name or f"c{i}",
                    shadow_price=shadow_price,
                    is_binding=is_binding,
                    is_approximate=False,
                )
            )

        variable_sens: list[VariableSensitivity] = []
        for var in problem.variables:
            idx = col_map.get(var.name)
            reduced_cost = float(col_dual[idx]) if idx is not None and idx < len(col_dual) else None
            is_at_bound: bool | None = None
            if idx is not None and idx < len(col_values):
                value = col_values[idx]
                lb = 0.0 if var.type == VariableType.BINARY else var.lower_bound
                ub = 1.0 if var.type == VariableType.BINARY else var.upper_bound
                at_lb = lb is not None and abs(value - lb) <= 1e-7
                at_ub = ub is not None and abs(value - ub) <= 1e-7
                is_at_bound = bool(at_lb or at_ub)
            variable_sens.append(
                VariableSensitivity(
                    name=var.name,
                    reduced_cost=reduced_cost,
                    is_at_bound=is_at_bound,
                    is_approximate=False,
                )
            )

        return SensitivityResult(
            constraints=constraint_sens,
            variables=variable_sens,
            is_approximate=False,
        )
