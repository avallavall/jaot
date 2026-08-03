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
from collections.abc import Callable
from typing import Any

from pyscipopt import SCIP_EVENTTYPE, SCIP_PARAMSETTING, Eventhdlr, Model  # noqa: F401

from app.domains.solver.adapters._scip_expression import (
    anchor_constant_expr,
    build_scip_expression as _build_scip_expression_impl,
    set_scip_objective,
)
from app.domains.solver.adapters._scip_model_builder import (
    build_scip_model as _build_scip_model_impl,
)
from app.domains.solver.adapters.base import STRICT_EPSILON, SolverCapabilities
from app.domains.solver.constraint_activity import (
    activity_of,
    is_binding as is_binding_at,
    is_binding_within_bounds,
)
from app.domains.solver.reduced_cost import derive_reduced_costs
from app.domains.solver.sensitivity_values import publishable_value
from app.domains.solver.services.expression_parser import ExpressionParser, ParsedExpression
from app.schemas.optimization import (
    ConstraintSensitivity,
    OptimizationProblem,
    OptimizationResult,
    ProgressPoint,
    SensitivityResult,
    SolverStatus,
    Variable,
    VariableSensitivity,
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

    def __init__(
        self,
        on_progress: Callable[[ProgressPoint], None] | None = None,
    ) -> None:
        super().__init__()
        self.history: list[ProgressPoint] = []
        self._on_progress = on_progress
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
            # Live Solve: stream this incumbent out (best-effort). The point is
            # already recorded above, so a failing callback never loses history;
            # the surrounding try/except also guarantees it can't abort the solve.
            if self._on_progress is not None:
                self._on_progress(point)
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
        supports_progress=True,  # _ProgressEventHandler streams per-incumbent (Live Solve)
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
        on_progress: Callable[[ProgressPoint], None] | None = None,
    ) -> OptimizationResult:
        """Solve an optimization problem with SCIP. See module docstring."""
        start_time = time.time()

        try:
            model, scip_vars, constraint_refs, progress_handler = self._build_model(
                problem, warm_start, on_progress
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
        on_progress: Callable[[ProgressPoint], None] | None = None,
    ) -> tuple[Model, dict[str, Any], dict[str, Any], _ProgressEventHandler]:
        """Create the SCIP model with variables, constraints, objective and progress handler."""
        model = Model(problem.name or "optimization_problem")
        self._configure_solver(model, problem)
        scip_vars = self._create_variables(model, problem.variables)
        variable_names = {v.name for v in problem.variables}
        constraint_refs = self._add_constraints(
            model, scip_vars, problem.constraints, variable_names
        )
        self._set_objective(model, scip_vars, problem.objective, variable_names)

        ws = warm_start or problem.heuristic_warm_start
        if ws is not None:
            self._apply_warm_start(model, scip_vars, ws)

        progress_handler = _ProgressEventHandler(on_progress)
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

        # Presolving. Aggressive is what makes branch-and-bound tractable, so a MIP
        # keeps it — its sensitivity comes from a separate LP relaxation anyway.
        #
        # A pure LP does NOT keep it, because this model IS where its shadow prices
        # and reduced costs are read from, and presolve is allowed to remove the
        # rows and columns they describe. `getDualSolVal` then answers 0 for what it
        # removed, which is indistinguishable from a dual that is genuinely zero.
        # Measured on `max 3x+2y ; x+y<=4 ; x+3y<=6 ; x<=3` (optimum 11 at (3,1),
        # all three rows tight): with aggressive presolve the LP is never solved at
        # all — 0 simplex iterations — and all three shadow prices come back -0.0
        # with `is_approximate=False`, i.e. stamped as exact. Without it: c1=2,
        # cap_x=1, and 2*4 + 1*3 = 11, which is strong duality holding exactly.
        # Turning presolve off is what fixes it; heuristics and propagation make no
        # difference (measured). Nor does it cost anything: on a 3000x2000 random
        # sparse LP the two settings solve in 0.98 s and 1.04 s — presolve earns its
        # keep on integer problems, not on the simplex.
        has_integers = self._has_integer_variables(problem)
        model.setPresolve(SCIP_PARAMSETTING.AGGRESSIVE if has_integers else SCIP_PARAMSETTING.OFF)

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
        variable_names: set[str],
    ) -> dict[str, Any]:
        """Add constraints to model and return constraint references for sensitivity analysis."""
        constraint_refs: dict[str, Any] = {}

        for i, constraint in enumerate(constraints):
            parsed = self._parser.parse_constraint(
                constraint.expression,
                known_variables=variable_names,
            )
            name = constraint.name or f"c{i}"
            # Anchor a constant LHS (no variable terms) so addCons never gets a Python
            # bool — the "given constraint is not ExprCons but bool" crash. Shared with
            # the file-export/stats builder via _scip_expression.anchor_constant_expr.
            lhs_expr = anchor_constant_expr(
                self._build_expression(parsed.lhs, scip_vars), scip_vars, label=name
            )

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
        variable_names: set[str],
    ) -> None:
        """Set the objective function."""
        parsed = self._parser.parse_expression(
            objective.expression,
            known_variables=variable_names,
        )

        obj_expr = self._build_expression(parsed, scip_vars)

        sense = "minimize" if objective.sense.value == "minimize" else "maximize"
        set_scip_objective(model, obj_expr, sense, is_linear=parsed.is_linear())

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

    # RHS / objective-coefficient ranging is not reliably exposed by the
    # PySCIPOpt build, so we never fabricate ranges — we annotate their absence.
    _RANGING_NOTE = "Coefficient and RHS ranging are not available for this solver build."

    def _binding_at(
        self, problem: OptimizationProblem, solution: dict[str, float]
    ) -> dict[str, bool]:
        """Which constraints sit on their limit at ``solution``, by name.

        Same arithmetic and same rule as the exact analysis, so the two never
        report different counts for the same run. A constraint whose expression
        will not parse is simply absent — no claim beats a wrong one.
        """
        known = set(solution)
        out: dict[str, bool] = {}
        for i, constraint in enumerate(problem.constraints):
            name = constraint.name or f"c{i + 1}"
            try:
                parsed = self._parser.parse_constraint(constraint.expression, known)
            except Exception:  # noqa: BLE001 — an unparseable row gets no claim
                continue
            out[name] = is_binding_at(
                activity_of(parsed.lhs.terms, solution), parsed.rhs, parsed.operator
            )
        return out

    def _extract_sensitivity(
        self,
        model: Model,
        constraint_refs: dict[str, Any],
        var_refs: dict[str, Any] | None = None,
        problem: OptimizationProblem | None = None,
        *,
        is_approximate: bool = False,
        note: str | None = None,
        integer_solution: dict[str, float] | None = None,
    ) -> SensitivityResult:
        """Extract sensitivity (shadow prices + reduced costs) from a solved LP model.

        Shadow prices come from ``getDualSolVal`` per constraint; reduced costs and
        the at-bound flag come from the variable references when provided. Objective
        and RHS ranging are not reliably exposed by PySCIPOpt, so those lists stay
        empty and the absence is recorded in ``note`` rather than guessed. Only valid
        for LP models — the real model for pure-LP problems, the LP relaxation for MIP.

        Args:
            model: Solved SCIP model (must be LP, not MIP)
            constraint_refs: Dict of constraint name -> SCIP constraint object
            var_refs: Dict of variable name -> SCIP variable object (for reduced costs)
            problem: The original problem, used to read variable bounds
            is_approximate: Stamp every entry as approximate (LP-relaxation path)
            note: Base note to prefix before the ranging annotation

        Returns:
            SensitivityResult with constraint shadow prices and variable reduced costs
        """
        constraint_sensitivities = []

        # "Binding" is a statement about slack, not about price — see
        # app/domains/solver/constraint_activity.py for the measurements that
        # forced this apart.
        #
        # Which solution it is about matters. On the MIP path `model` is a
        # *separate* LP relaxation, so its rows say nothing about the integer
        # answer the caller was handed: binding is evaluated against
        # `integer_solution` instead, the same x* the exact analysis reads. Only
        # when neither is available do we report None.
        sol = None
        if not is_approximate:
            try:
                sol = model.getBestSol()
            except Exception as e:  # pragma: no cover — defensive
                logger.debug("No solution available for binding status: %s", e)
        infinity = model.infinity()
        binding_at_x_star = (
            self._binding_at(problem, integer_solution)
            if integer_solution is not None and problem is not None
            else {}
        )

        for name, cons in constraint_refs.items():
            shadow_price = None
            is_binding = binding_at_x_star.get(name)
            try:
                # SCIP answers SCIP_INVALID (1e99) through the same double a real
                # dual rides on — e.g. for the surviving reference when two rows
                # share a name. A sentinel is None here, or the derivation below
                # prices reduced costs off it (measured: rc = 2e+99).
                shadow_price = publishable_value(model.getDualSolVal(cons))
            except Exception as e:
                logger.debug("Could not extract dual for constraint %s: %s", name, e)
            if is_binding is None and sol is not None:
                try:
                    # getActivity needs the solution passed explicitly: in SCIP's
                    # solved stage the no-argument form reads no current LP and
                    # returns 1e20 for every row.
                    is_binding = is_binding_within_bounds(
                        model.getActivity(cons, sol),
                        model.getLhs(cons),
                        model.getRhs(cons),
                        infinity,
                    )
                except Exception as e:
                    logger.debug("Could not read activity for constraint %s: %s", name, e)

            constraint_sensitivities.append(
                ConstraintSensitivity(
                    name=name,
                    shadow_price=shadow_price,
                    is_binding=is_binding,
                    is_approximate=is_approximate,
                )
            )

        # Reduced costs come from the duals just published, not from the solver's
        # own basis: with a cap written as a row SCIP bills that price twice, once
        # as the row's dual and again here. See reduced_cost.py for the numbers.
        derived_reduced_costs = (
            derive_reduced_costs(
                problem,
                {c.name: c.shadow_price for c in constraint_sensitivities},
                self._parser,
            )
            if problem is not None
            else {}
        )

        variable_sensitivities = (
            self._extract_variable_sensitivity(
                model, var_refs, problem, is_approximate, derived_reduced_costs
            )
            if var_refs
            else []
        )

        final_note = f"{note}. {self._RANGING_NOTE}" if note else self._RANGING_NOTE

        return SensitivityResult(
            constraints=constraint_sensitivities,
            variables=variable_sensitivities,
            objective_ranges=[],
            rhs_ranges=[],
            is_approximate=is_approximate,
            note=final_note,
        )

    @staticmethod
    def _extract_variable_sensitivity(
        model: Model,
        var_refs: dict[str, Any],
        problem: OptimizationProblem | None,
        is_approximate: bool,
        derived_reduced_costs: dict[str, float] | None = None,
    ) -> list[VariableSensitivity]:
        """Per-variable reduced costs + at-bound flags from a solved LP model.

        The reduced cost is the one implied by the shadow prices we publish
        (``derived_reduced_costs``), so the two halves of the Sensitivity tab agree;
        ``getVarRedcost`` is the fallback for models the derivation cannot price —
        quadratic ones, or any row whose dual is missing.

        ``getVarRedcost`` may be absent on some PySCIPOpt builds, and ``getVal``
        can fail mid-extraction; both are guarded so a single variable never
        aborts the whole sensitivity result.
        """
        derived_reduced_costs = derived_reduced_costs or {}
        bounds: dict[str, tuple[float | None, float | None]] = {}
        if problem is not None:
            for v in problem.variables:
                lb = v.lower_bound
                ub = v.upper_bound
                if v.type == VariableType.BINARY:
                    lb = 0.0 if lb is None else lb
                    ub = 1.0 if ub is None else ub
                bounds[v.name] = (lb, ub)

        variable_sensitivities: list[VariableSensitivity] = []
        for name, var in var_refs.items():
            reduced_cost = derived_reduced_costs.get(name)
            is_at_bound = None
            if reduced_cost is None:
                try:
                    reduced_cost = publishable_value(model.getVarRedcost(var))
                except Exception as e:
                    logger.debug("Could not extract reduced cost for %s: %s", name, e)
            try:
                value = model.getVal(var)
                lb, ub = bounds.get(name, (None, None))
                at_lb = lb is not None and abs(value - lb) <= 1e-7
                at_ub = ub is not None and abs(value - ub) <= 1e-7
                is_at_bound = bool(at_lb or at_ub)
            except Exception as e:
                logger.debug("Could not determine bound status for %s: %s", name, e)

            variable_sensitivities.append(
                VariableSensitivity(
                    name=name,
                    reduced_cost=reduced_cost,
                    is_at_bound=is_at_bound,
                    is_approximate=is_approximate,
                )
            )
        return variable_sensitivities

    def _has_integer_variables(self, problem: OptimizationProblem) -> bool:
        """Check if the problem has any integer or binary variables."""
        return any(v.type in (VariableType.INTEGER, VariableType.BINARY) for v in problem.variables)

    def _extract_sensitivity_for_mip(
        self,
        problem: OptimizationProblem,
        integer_solution: dict[str, float] | None = None,
    ) -> SensitivityResult:
        """Extract approximate sensitivity via LP relaxation for MIP problems.

        Creates a fresh LP model where all variables are continuous, solves it,
        and extracts dual values. Results are marked as approximate.

        The DUALS are the relaxation's; the binding flags are not. Those are read
        off ``integer_solution`` — the answer the caller actually got — so the
        Sensitivity tab and the exact analysis agree, and the "N of M constraints
        are binding" insight keeps working for MIPs (the majority of models).

        Presolve is off here for the same reason as in ``_configure_solver``, and
        SCIP's *defaults* are enough to trigger it: this model was built with them
        and returned -0.0 for every shadow price of a relaxation whose true duals
        are 2 and 1. "Approximate" is a statement about the relaxation, not a
        licence to report zeros nobody computed.
        """
        try:
            lp_model = Model("lp_relaxation")
            lp_model.hideOutput()
            lp_model.setParam("display/verblevel", 0)
            lp_model.setPresolve(SCIP_PARAMSETTING.OFF)

            variable_names = {v.name for v in problem.variables}
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

            return self._extract_sensitivity(
                lp_model,
                lp_constraint_refs,
                var_refs=lp_vars,
                problem=problem,
                is_approximate=True,
                note="Approximate — based on LP relaxation",
                integer_solution=integer_solution,
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
        variable_names: set[str],
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
        variable_names: set[str],
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
                result.sensitivity = self._compute_sensitivity(
                    model, problem, constraint_refs, scip_vars, result.solution
                )

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
                VariableSolution(
                    name=var_def.name,
                    value=value,
                    type=var_def.type,
                    family=var_def.family,
                    index_tuple=var_def.index_tuple,
                )
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

    def _is_quadratic_problem(self, problem: OptimizationProblem) -> bool:
        """True when the objective or any constraint carries a degree-2 term."""
        variable_names = {v.name for v in problem.variables}
        parsed_obj = self._parser.parse_expression(
            problem.objective.expression, known_variables=variable_names
        )
        if not parsed_obj.is_linear():
            return True
        return any(
            not self._parser.parse_constraint(
                c.expression, known_variables=variable_names
            ).lhs.is_linear()
            for c in problem.constraints
        )

    def _compute_sensitivity(
        self,
        model: Model,
        problem: OptimizationProblem,
        constraint_refs: dict[str, Any],
        var_refs: dict[str, Any] | None = None,
        integer_solution: dict[str, float] | None = None,
    ) -> SensitivityResult | None:
        """Extract sensitivity analysis (exact for LP, approximate for MIP).

        Quadratic problems are excluded: LP shadow prices / reduced costs do not
        apply to a quadratic model, and the "LP relaxation" rebuilt for MIPs would
        silently be a QP — better an honest absence than misleading duals.
        """
        try:
            if self._is_quadratic_problem(problem):
                return SensitivityResult(
                    constraints=[],
                    is_approximate=True,
                    note="Sensitivity analysis is not available for quadratic problems.",
                )
            if self._has_integer_variables(problem):
                return self._extract_sensitivity_for_mip(problem, integer_solution)
            return self._extract_sensitivity(
                model, constraint_refs, var_refs=var_refs, problem=problem
            )
        except Exception as e:
            logger.warning("Sensitivity extraction failed: %s", e)
            return None

    @staticmethod
    def _map_status(scip_status: str) -> SolverStatus:
        """Map SCIP status to our SolverStatus enum."""
        return _SCIP_STATUS_MAP.get(scip_status, SolverStatus.ERROR)
