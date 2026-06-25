"""SCIP adapter — PySCIPOpt implementation of SolverAdapter.

Phase 4 / Plan 03 / SOLV-04. Full extraction complete.

SCIPAdapter owns the complete SCIP solve pipeline: all 10 private SCIP methods,
the _ProgressEventHandler, _SCIP_STATUS_MAP, and the module-level helpers.
solver_service.py delegates via registry.get('scip').solve() — no direct SCIP API
calls remain outside this file and app/domains/solver/adapters/_scip_*.py helpers.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pyscipopt import SCIP_EVENTTYPE, SCIP_PARAMSETTING, Eventhdlr, Model  # noqa: F401

from app.domains.solver.adapters._scip_expression import (
    build_scip_expression as _build_scip_expression_impl,
)
from app.domains.solver.adapters._scip_model_builder import (
    build_scip_model as _build_scip_model_impl,
)
from app.domains.solver.adapters.base import STRICT_EPSILON, SolverCapabilities
from app.domains.solver.services.expression_parser import ExpressionParser, ParsedExpression
from app.schemas.optimization import (
    ConstraintSensitivity,
    OptimizationProblem,
    OptimizationResult,
    ProgressPoint,
    SensitivityResult,
    SolverStatus,
    Variable,
    VariableSolution,
    VariableType,
)

logger = logging.getLogger(__name__)

_SCIP_STATUS_MAP: dict[str, SolverStatus] = {
    "optimal": SolverStatus.OPTIMAL,
    "infeasible": SolverStatus.INFEASIBLE,
    "unbounded": SolverStatus.UNBOUNDED,
    "timelimit": SolverStatus.TIME_LIMIT,
    "userinterrupt": SolverStatus.TIME_LIMIT,
    "nodelimit": SolverStatus.TIME_LIMIT,
    "totalnodelimit": SolverStatus.TIME_LIMIT,
    "stallnodelimit": SolverStatus.TIME_LIMIT,
    "gaplimit": SolverStatus.OPTIMAL,
    "memlimit": SolverStatus.ERROR,
    "sollimit": SolverStatus.FEASIBLE,
    "bestsollimit": SolverStatus.FEASIBLE,
    "restartlimit": SolverStatus.FEASIBLE,
}

# Cap progress snapshots so a long solve with thousands of incumbents can't
# bloat the JSONB column or memory. SCIP rarely yields more than a few hundred
# improving solutions; anything beyond is downsampled to the most recent ones.
_MAX_PROGRESS_POINTS = 500
_SCIP_INF = 1e15

# Dispatch table for constraint operators — avoids duplicated elif chains in
# _add_constraints and _rebuild_lp_constraints. Strict inequalities use a small
# epsilon since pyscipopt addCons only supports non-strict operators.
_CONSTRAINT_BUILDERS: dict[str, Any] = {
    "<=": lambda lhs, rhs: lhs <= rhs,
    ">=": lambda lhs, rhs: lhs >= rhs,
    "==": lambda lhs, rhs: lhs == rhs,
    "=": lambda lhs, rhs: lhs == rhs,
    "<": lambda lhs, rhs: lhs <= rhs - STRICT_EPSILON,
    ">": lambda lhs, rhs: lhs >= rhs + STRICT_EPSILON,
}


def _is_finite_bound(value: float) -> bool:
    return value == value and abs(value) <= _SCIP_INF  # NaN-safe


class _ProgressEventHandler(Eventhdlr):
    """Capture primal/dual/gap snapshots while SCIP solves.

    Subscribed to BESTSOLFOUND so we get a point every time a new best feasible
    solution is found. The resulting list is read after model.optimize() returns
    and persisted in OptimizationResult.progress_history so the execution detail
    view can render a real convergence chart.
    """

    EVENT_MASK = SCIP_EVENTTYPE.BESTSOLFOUND

    def __init__(self) -> None:
        super().__init__()
        self.history: list[ProgressPoint] = []
        self._t0 = time.time()
        self._iter = 0

    def eventinit(self) -> None:  # type: ignore[override]
        self.model.catchEvent(self.EVENT_MASK, self)

    def eventexit(self) -> None:  # type: ignore[override]
        self.model.dropEvent(self.EVENT_MASK, self)

    def eventexec(self, event: Any) -> None:  # type: ignore[override]
        try:
            m = self.model
            primal = m.getPrimalbound()
            # SCIP uses ±1e+20 as "no bound yet" — skip until we have something.
            if not _is_finite_bound(primal):
                return
            try:
                gap = m.getGap()
            except Exception:
                gap = None
            if gap is not None and not _is_finite_bound(gap):
                gap = None
            dual = m.getDualbound()
            self._iter += 1
            point = ProgressPoint(
                iteration=self._iter,
                node=m.getNNodes(),
                objective=primal,
                primal_bound=primal,
                dual_bound=dual if _is_finite_bound(dual) else None,
                gap=gap,
                elapsed_seconds=round(time.time() - self._t0, 3),
            )
            self.history.append(point)
        except Exception as exc:  # never let the handler raise — would abort the solve
            logger.debug("Progress event handler failed: %s", exc)


class SCIPAdapter:
    """SCIP implementation of the SolverAdapter Protocol.

    Full extraction — all 10 private SCIP methods live here plus _ProgressEventHandler.
    solve() runs the complete SCIP pipeline internally — no delegation to SolverService.
    """

    capabilities: SolverCapabilities = SolverCapabilities(
        name="scip",
        supports_continuous=True,
        supports_integer=True,
        supports_binary=True,
        supports_quadratic=True,  # SCIP handles quadratic via addCons
        supports_sensitivity=True,  # via getDualSolVal + LP relaxation
        supports_warm_start=True,  # via createSol + addSol
        supports_multi_objective=False,  # uses orchestrator fallback
        # Phase 7.4 / D-10: requires_license removed — no per-request gate
    )

    def __init__(self) -> None:
        self._parser = ExpressionParser()
        self._available: bool | None = None

    def is_available(self) -> bool:
        """Cached import check per D-12. Safe to cache for SCIP because
        pyscipopt is an installed Python package — its availability cannot
        change mid-process.

        DO NOT copy this pattern for Hexaly (Phase 7) — license expiry
        needs a fresh check on every call.
        """
        if self._available is None:
            try:
                import pyscipopt  # noqa: F401

                self._available = True
            except ImportError:
                self._available = False
        return self._available

    # Phase 7.4 / D-10: validate_license removed — no per-request gate for SCIP.

    def _build_expression(
        self,
        parsed: ParsedExpression,
        scip_vars: dict[str, Any],
    ) -> Any:
        """Build a SCIP expression — D-06.

        Private to SCIPAdapter. HiGHSAdapter (Phase 5) will have its own
        `_build_expression` that uses highspy variable types instead of
        SCIP Variables. Cohesion > DRY because the two builders are
        structurally different.
        """
        return _build_scip_expression_impl(parsed, scip_vars)

    def build_scip_model(
        self,
        problem: OptimizationProblem,
    ) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        """Forward-compat accessor for SCIP-specific callers reaching through registry.get('scip').

        Returns (scip_Model, scip_vars_dict, constraint_refs_dict). Used by file_export.py and
        by any future Phase 5+ caller that wants to go through the registry rather than importing
        _scip_model_builder directly. Per Research §Pitfall 1 Option A.
        """
        return _build_scip_model_impl(problem)

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
    ) -> OptimizationResult:
        """Solve an optimization problem with SCIP. See module docstring."""
        start_time = time.time()

        try:
            model, scip_vars, constraint_refs, progress_handler = self._build_model(
                problem, warm_start
            )

            logger.info("Solving problem: %s", problem.name or "unnamed")
            model.optimize()

            solve_time = time.time() - start_time
            result = self._extract_result(
                model, scip_vars, problem, solve_time, constraint_refs=constraint_refs
            )

            effective_warm_start = warm_start or problem.heuristic_warm_start
            if effective_warm_start is not None:
                result.warm_start_used = True

            history = self._finalize_progress_history(progress_handler, model, result, solve_time)
            if history:
                result.progress_history = history

            return result

        except Exception as e:
            logger.error("Solver error: %s", e)
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.time() - start_time,
                error_message=str(e),
            )

    def _build_model(
        self,
        problem: OptimizationProblem,
        warm_start: dict[str, float] | None,
    ) -> tuple[Model, dict[str, Any], dict[str, Any], _ProgressEventHandler]:
        """Create the SCIP model with variables, constraints, objective and progress handler."""
        model = Model(problem.name or "optimization_problem")
        self._configure_solver(model, problem)
        scip_vars = self._create_variables(model, problem.variables)
        variable_names = [v.name for v in problem.variables]
        constraint_refs = self._add_constraints(
            model, scip_vars, problem.constraints, variable_names
        )
        self._set_objective(model, scip_vars, problem.objective, variable_names)

        ws = warm_start or problem.heuristic_warm_start
        if ws is not None:
            self._apply_warm_start(model, scip_vars, ws)

        progress_handler = _ProgressEventHandler()
        model.includeEventhdlr(
            progress_handler,
            "JaotProgressHdlr",
            "Capture primal/dual/gap snapshots for convergence chart",
        )
        return model, scip_vars, constraint_refs, progress_handler

    @staticmethod
    def _finalize_progress_history(
        progress_handler: _ProgressEventHandler,
        model: Model,
        result: OptimizationResult,
        solve_time: float,
    ) -> list[ProgressPoint]:
        """Append the final objective/dual-bound point to the progress history."""
        history = list(progress_handler.history)
        if result.objective_value is None:
            return history

        dual = model.getDualbound()
        final_point = ProgressPoint(
            iteration=(history[-1].iteration + 1) if history else 1,
            node=model.getNNodes(),
            objective=result.objective_value,
            primal_bound=result.objective_value,
            dual_bound=dual if _is_finite_bound(dual) else None,
            gap=result.gap,
            elapsed_seconds=round(solve_time, 3),
        )
        if not history or history[-1].objective != final_point.objective:
            history.append(final_point)

        # Downsample to _MAX_PROGRESS_POINTS if needed — keep first + last + evenly
        # spaced middle entries. O(n) once here instead of O(n) per pop(1) during solve.
        if len(history) > _MAX_PROGRESS_POINTS:
            step = (len(history) - 2) / (_MAX_PROGRESS_POINTS - 2)
            indices = (
                [0]
                + [int(1 + i * step) for i in range(_MAX_PROGRESS_POINTS - 2)]
                + [len(history) - 1]
            )
            history = [history[i] for i in dict.fromkeys(indices)]  # dedupe preserving order

        return history

    def _configure_solver(self, model: Model, problem: OptimizationProblem) -> None:
        """Configure SCIP solver options."""
        options = problem.options

        # Time limit
        model.setParam("limits/time", options.time_limit_seconds)

        # MIP gap
        model.setParam("limits/gap", options.gap_tolerance)

        # Threads (0 = auto)
        if options.threads > 0:
            model.setParam("parallel/maxnthreads", options.threads)

        # Verbosity
        if not options.verbose:
            model.setParam("display/verblevel", 0)

        # Aggressive presolving for better performance
        model.setPresolve(SCIP_PARAMSETTING.AGGRESSIVE)

    def _create_variables(
        self,
        model: Model,
        variables: list[Variable],
    ) -> dict[str, Any]:
        """Create SCIP variables from problem definition."""
        scip_vars = {}

        for var in variables:
            # Determine bounds
            lb = var.lower_bound if var.lower_bound is not None else None
            ub = var.upper_bound if var.upper_bound is not None else None

            if var.type == VariableType.BINARY:
                scip_var = model.addVar(
                    name=var.name,
                    vtype="B",  # Binary
                )
            elif var.type == VariableType.INTEGER:
                scip_var = model.addVar(
                    name=var.name,
                    vtype="I",  # Integer
                    lb=lb,
                    ub=ub,
                )
            else:  # CONTINUOUS
                scip_var = model.addVar(
                    name=var.name,
                    vtype="C",  # Continuous
                    lb=lb,
                    ub=ub,
                )

            scip_vars[var.name] = scip_var
            logger.debug("Created variable: %s (%s)", var.name, var.type)

        return scip_vars

    def _add_constraints(
        self,
        model: Model,
        scip_vars: dict[str, Any],
        constraints: list[Any],
        variable_names: list[str],
    ) -> dict[str, Any]:
        """Add constraints to model and return constraint references for sensitivity analysis."""
        constraint_refs: dict[str, Any] = {}

        for i, constraint in enumerate(constraints):
            parsed = self._parser.parse_constraint(
                constraint.expression,
                known_variables=variable_names,
            )
            lhs_expr = self._build_expression(parsed.lhs, scip_vars)
            name = constraint.name or f"c{i}"

            cons = self._add_cons_for_operator(model, parsed.operator, lhs_expr, parsed.rhs, name)
            if cons is not None:
                constraint_refs[name] = cons

            logger.debug("Added constraint: %s", name)

        return constraint_refs

    @staticmethod
    def _add_cons_for_operator(
        model: Model,
        operator: str,
        lhs_expr: Any,
        rhs: float,
        name: str,
    ) -> Any | None:
        """Dispatch constraint creation through the operator builder table."""
        builder = _CONSTRAINT_BUILDERS.get(operator)
        if builder is None:
            return None
        return model.addCons(builder(lhs_expr, rhs), name=name)

    def _set_objective(
        self,
        model: Model,
        scip_vars: dict[str, Any],
        objective: Any,
        variable_names: list[str],
    ) -> None:
        """Set the objective function."""
        parsed = self._parser.parse_expression(
            objective.expression,
            known_variables=variable_names,
        )

        obj_expr = self._build_expression(parsed, scip_vars)

        sense = "minimize" if objective.sense.value == "minimize" else "maximize"
        model.setObjective(obj_expr, sense=sense)

        logger.debug("Set objective: %s %s", sense, objective.expression)

    def _apply_warm_start(
        self,
        model: Model,
        scip_vars: dict[str, Any],
        warm_start: dict[str, float],
    ) -> bool:
        """Inject a warm start solution into the SCIP model before optimization.

        Uses addSol (not trySol) so the solution is added as a starting point.

        Args:
            model: SCIP model
            scip_vars: Dict of variable name -> SCIP variable
            warm_start: Dict of variable name -> value

        Returns:
            True if warm start was added successfully, False otherwise
        """
        try:
            sol = model.createSol()
            for var_name, value in warm_start.items():
                if var_name in scip_vars:
                    model.setSolVal(sol, scip_vars[var_name], float(value))
            model.addSol(sol, free=True)
            logger.debug("Warm start solution injected successfully")
            return True
        except Exception as e:
            logger.warning("Failed to inject warm start solution: %s", e)
            return False

    def _extract_sensitivity(
        self,
        model: Model,
        constraint_refs: dict[str, Any],
    ) -> SensitivityResult:
        """Extract sensitivity analysis (shadow prices) from a solved LP model.

        Uses getDualSolVal on each constraint reference. Only valid for LP problems.

        Args:
            model: Solved SCIP model (must be LP, not MIP)
            constraint_refs: Dict of constraint name -> SCIP constraint object

        Returns:
            SensitivityResult with constraint shadow prices
        """
        constraint_sensitivities = []

        for name, cons in constraint_refs.items():
            shadow_price = None
            is_binding = None
            try:
                shadow_price = model.getDualSolVal(cons)
                # A constraint is binding if |shadow_price| > small epsilon
                is_binding = abs(shadow_price) > 1e-8
            except Exception as e:
                logger.debug("Could not extract dual for constraint %s: %s", name, e)

            constraint_sensitivities.append(
                ConstraintSensitivity(
                    name=name,
                    shadow_price=shadow_price,
                    is_binding=is_binding,
                    is_approximate=False,
                )
            )

        return SensitivityResult(
            constraints=constraint_sensitivities,
            is_approximate=False,
        )

    def _has_integer_variables(self, problem: OptimizationProblem) -> bool:
        """Check if the problem has any integer or binary variables."""
        return any(v.type in (VariableType.INTEGER, VariableType.BINARY) for v in problem.variables)

    def _extract_sensitivity_for_mip(
        self,
        problem: OptimizationProblem,
    ) -> SensitivityResult:
        """Extract approximate sensitivity via LP relaxation for MIP problems.

        Creates a fresh LP model where all variables are continuous, solves it,
        and extracts dual values. Results are marked as approximate.
        """
        try:
            lp_model = Model("lp_relaxation")
            lp_model.hideOutput()
            lp_model.setParam("display/verblevel", 0)

            variable_names = [v.name for v in problem.variables]
            lp_vars = self._create_lp_relaxation_vars(lp_model, problem)
            lp_constraint_refs = self._rebuild_lp_constraints(
                lp_model, problem, lp_vars, variable_names
            )
            self._set_lp_objective(lp_model, problem, lp_vars, variable_names)

            lp_model.optimize()

            if lp_model.getStatus() != "optimal":
                return SensitivityResult(
                    constraints=[],
                    is_approximate=True,
                    note="LP relaxation did not reach optimality — sensitivity unavailable",
                )

            sensitivity = self._extract_sensitivity(lp_model, lp_constraint_refs)
            corrected = [
                cs.model_copy(update={"is_approximate": True}) for cs in sensitivity.constraints
            ]
            return SensitivityResult(
                constraints=corrected,
                is_approximate=True,
                note="Approximate — based on LP relaxation",
            )

        except Exception as e:
            logger.warning("LP relaxation sensitivity failed: %s", e)
            return SensitivityResult(
                constraints=[],
                is_approximate=True,
                note=f"Sensitivity analysis failed: {e}",
            )

    @staticmethod
    def _create_lp_relaxation_vars(lp_model: Model, problem: OptimizationProblem) -> dict[str, Any]:
        """Recreate all variables as continuous for the LP relaxation."""
        lp_vars: dict[str, Any] = {}
        for var in problem.variables:
            lb = var.lower_bound
            ub = var.upper_bound
            if var.type == VariableType.BINARY:
                lb = 0.0 if lb is None else lb
                ub = 1.0 if ub is None else ub
            lp_vars[var.name] = lp_model.addVar(name=var.name, vtype="C", lb=lb, ub=ub)
        return lp_vars

    def _rebuild_lp_constraints(
        self,
        lp_model: Model,
        problem: OptimizationProblem,
        lp_vars: dict[str, Any],
        variable_names: list[str],
    ) -> dict[str, Any]:
        """Rebuild problem constraints on the LP relaxation model."""
        lp_constraint_refs: dict[str, Any] = {}
        for i, constraint in enumerate(problem.constraints):
            parsed = self._parser.parse_constraint(
                constraint.expression,
                known_variables=variable_names,
            )
            lhs_expr = self._build_expression(parsed.lhs, lp_vars)
            name = constraint.name or f"c{i}"

            cons = self._add_cons_for_operator(
                lp_model, parsed.operator, lhs_expr, parsed.rhs, name
            )
            if cons is not None:
                lp_constraint_refs[name] = cons
        return lp_constraint_refs

    def _set_lp_objective(
        self,
        lp_model: Model,
        problem: OptimizationProblem,
        lp_vars: dict[str, Any],
        variable_names: list[str],
    ) -> None:
        """Set the objective on the LP relaxation model."""
        parsed_obj = self._parser.parse_expression(
            problem.objective.expression,
            known_variables=variable_names,
        )
        obj_expr = self._build_expression(parsed_obj, lp_vars)
        sense = "minimize" if problem.objective.sense.value == "minimize" else "maximize"
        lp_model.setObjective(obj_expr, sense=sense)

    def _extract_result(
        self,
        model: Model,
        scip_vars: dict[str, Any],
        problem: OptimizationProblem,
        solve_time: float,
        constraint_refs: dict[str, Any] | None = None,
    ) -> OptimizationResult:
        """Extract solution from solved model."""
        status = self._map_status(model.getStatus())

        result = OptimizationResult(
            status=status,
            solve_time_seconds=solve_time,
            iterations=model.getNLPIterations() if hasattr(model, "getNLPIterations") else None,
            nodes=model.getNNodes(),
        )

        if status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE, SolverStatus.TIME_LIMIT):
            return result

        try:
            if model.getNSols() == 0:
                result.status = SolverStatus.INFEASIBLE
                result.error_message = "No solution found"
                return result

            result.objective_value = model.getObjVal()
            result.variables, result.solution = self._extract_variable_values(
                model, scip_vars, problem
            )
            result.gap = self._compute_mip_gap(model)

            logger.info("Solution found: obj=%.4f", result.objective_value)

            if constraint_refs:
                result.sensitivity = self._compute_sensitivity(model, problem, constraint_refs)

        except Exception as e:
            logger.warning("Error extracting solution: %s", e)
            result.error_message = f"Solution extraction error: {e}"

        return result

    @staticmethod
    def _extract_variable_values(
        model: Model,
        scip_vars: dict[str, Any],
        problem: OptimizationProblem,
    ) -> tuple[list[VariableSolution], dict[str, float]]:
        """Read variable values from the solved model."""
        var_solutions: list[VariableSolution] = []
        solution_dict: dict[str, float] = {}
        for var_def in problem.variables:
            value = model.getVal(scip_vars[var_def.name])
            if var_def.type in (VariableType.INTEGER, VariableType.BINARY):
                value = round(value)
            var_solutions.append(
                VariableSolution(name=var_def.name, value=value, type=var_def.type)
            )
            solution_dict[var_def.name] = value
        return var_solutions, solution_dict

    @staticmethod
    def _compute_mip_gap(model: Model) -> float | None:
        """Return MIP gap if available, otherwise None."""
        try:
            return model.getGap()
        except Exception:
            logger.debug("MIP gap extraction failed", exc_info=True)
            return None

    def _compute_sensitivity(
        self,
        model: Model,
        problem: OptimizationProblem,
        constraint_refs: dict[str, Any],
    ) -> SensitivityResult | None:
        """Extract sensitivity analysis (exact for LP, approximate for MIP)."""
        try:
            if self._has_integer_variables(problem):
                return self._extract_sensitivity_for_mip(problem)
            return self._extract_sensitivity(model, constraint_refs)
        except Exception as e:
            logger.warning("Sensitivity extraction failed: %s", e)
            return None

    @staticmethod
    def _map_status(scip_status: str) -> SolverStatus:
        """Map SCIP status to our SolverStatus enum."""
        return _SCIP_STATUS_MAP.get(scip_status, SolverStatus.ERROR)
