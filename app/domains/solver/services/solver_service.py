"""Solver orchestrator — solver-agnostic dispatch through the SolverAdapter registry.

All SCIP-specific code lives in app/domains/solver/adapters/scip.py.
This module is the thin orchestrator that:
- Resolves the requested adapter via registry.get(solver_name)
- Delegates single-objective solves to adapter.solve()
- Runs multi-objective scalarization loops (epsilon-constraint / weighted-sum)
  by calling adapter.solve() on fresh OptimizationProblem subproblems
- Applies the D-02 native-delegation gate for adapters that natively support
  multi-objective solving (e.g., future HiGHS/Hexaly adapters)

Phase 4 Plan 03 / SOLV-04 / SOLV-05.
"""

import logging

import numpy as np
from sqlalchemy.orm import Session

from app.domains.solver.adapters import registry
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
    SolverUnavailableError,
)
from app.domains.solver.services.expression_parser import ExpressionParser, ParsedExpression
from app.schemas.optimization import (
    Constraint,
    MultiObjectiveConfig,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    ParetoPoint,
    SolverStatus,
)

logger = logging.getLogger(__name__)


def _emit_expression_string(parsed: ParsedExpression) -> str:
    """Render a ParsedExpression as a canonical string the parser can re-parse.

    Example: ParsedExpression(terms=[Term(2.0, ['x']), Term(-1.0, ['y','z'])], constant=3.0)
             -> "3.0 + 2.0*x + -1.0*y*z"
    """
    parts: list[str] = [repr(parsed.constant)]
    for term in parsed.terms:
        if not term.variables:
            parts.append(repr(term.coefficient))
        elif len(term.variables) == 1:
            parts.append(f"{repr(term.coefficient)}*{term.variables[0]}")
        elif len(term.variables) == 2:
            parts.append(f"{repr(term.coefficient)}*{term.variables[0]}*{term.variables[1]}")
    return " + ".join(parts)


def _build_weighted_objective(
    obj1: Objective,
    obj2: Objective,
    w1: float,
    w2: float,
) -> Objective:
    """Build a scalarized Objective from two weighted sources.

    Converts to minimize direction per the original _solve_weighted logic.
    Uses string interpolation of the raw expressions — the adapter's parser
    will re-parse and build the SCIP object inside adapter.solve().
    """
    sign1 = 1.0 if obj1.sense == ObjectiveSense.MINIMIZE else -1.0
    sign2 = 1.0 if obj2.sense == ObjectiveSense.MINIMIZE else -1.0
    scaled_str = f"({w1 * sign1}) * ({obj1.expression}) + ({w2 * sign2}) * ({obj2.expression})"
    return Objective(sense=ObjectiveSense.MINIMIZE, expression=scaled_str)


def _build_scalarized_problem(
    base: OptimizationProblem,
    scalar_objective: Objective,
    extra_constraint_exprs: list[str] | None = None,
) -> OptimizationProblem:
    """Build a fresh OptimizationProblem with a scalarized objective."""
    extras = [
        Constraint(name=f"_mo_extra_{i}", expression=expr)
        for i, expr in enumerate(extra_constraint_exprs or [])
    ]
    return OptimizationProblem(
        name=f"{base.name or 'mo'}_scalarized",
        variables=base.variables,
        objective=scalar_objective,
        constraints=[*base.constraints, *extras],
        options=base.options,
    )


def _compute_objective_value(
    result: OptimizationResult,
    obj_spec: Objective,
    parser: ExpressionParser,
    variable_names: list[str],
) -> float:
    """Compute an objective value from a result.solution dict.

    Replaces _extract_objective_value which took a SCIP Model + scip_vars.
    """
    parsed = parser.parse_expression(obj_spec.expression, known_variables=variable_names)
    value = parsed.constant
    for term in parsed.terms:
        if len(term.variables) == 1:
            var_name = term.variables[0]
            value += term.coefficient * result.solution.get(var_name, 0.0)
        elif len(term.variables) == 2:
            v1, v2 = term.variables
            value += term.coefficient * result.solution.get(v1, 0.0) * result.solution.get(v2, 0.0)
    return value


class SolverService:
    """Solver-agnostic orchestrator.

    Dispatches solves to the registered SolverAdapter for the given solver_name.
    Multi-objective orchestration runs scalarization loops that call adapter.solve()
    on fresh OptimizationProblem subproblems — no SCIP API calls here.

    Usage:
        solver = SolverService()
        result = solver.solve(problem)
    """

    def __init__(self, solver_name: str = DEFAULT_SOLVER_NAME) -> None:
        self._default_solver_name = solver_name
        self.parser = ExpressionParser()

    def resolve_effective_solver(
        self,
        requested_name: str | None,
        problem: OptimizationProblem,
        org_id: str | None = None,
        db: Session | None = None,
    ) -> tuple[str, str | None, bool]:
        """Resolve the effective solver name for a request.

        Phase 7.4 / D-11 / D-13: when the caller sends
        ``solver_name="auto"`` we delegate to
        :func:`~app.domains.solver.services.auto_router.select_solver`
        and propagate the returned ``(name, reason, fallback_triggered)``
        triple so the API layer can surface both the chosen solver and
        the reason to the UI (D-08). For any explicit name (or the
        omitted default) the return tuple carries ``reason=None`` and
        ``fallback_triggered=False``.

        Note: ``org_id`` and ``db`` are no longer used by the auto-router
        (Phase 7.4 replaced the BYOL license-state DB lookup with a
        Celery worker-health probe). They are kept in the signature for
        backwards-compatibility with call sites that pass them; they are
        silently ignored.

        Args:
            requested_name: Either ``"auto"``, an explicit solver name
                (``"scip"``, ``"highs"``, ``"hexaly"``), or ``None``.
            problem: The optimization problem — required for
                auto-routing classification.
            org_id: Ignored (kept for call-site compatibility).
            db: Ignored (kept for call-site compatibility).

        Returns:
            ``(effective_solver_name, reason_or_None, fallback_triggered)``.
        """
        if requested_name == "auto":
            from app.domains.solver.services.auto_router import (  # noqa: PLC0415
                select_solver,
            )

            effective, reason, fallback_triggered = select_solver(problem, self.parser)
            return (effective, reason, fallback_triggered)
        # Explicit solver name (or legacy None -> default per Pitfall 8).
        return (requested_name or self._default_solver_name, None, False)

    def solve(
        self,
        problem: OptimizationProblem,
        warm_start_solution: dict[str, float] | None = None,
        solver_name: str | None = None,
    ) -> OptimizationResult:
        """Resolve adapter via registry and delegate. Raises SolverNotFoundError if not registered."""
        name = solver_name or self._default_solver_name
        # Registry errors (not found / unavailable) are contract violations —
        # propagate them so callers can catch SolverNotFoundError explicitly.
        adapter = registry.get(name)
        try:
            return adapter.solve(problem, warm_start=warm_start_solution)
        except (SolverNotFoundError, SolverUnavailableError):
            raise
        except Exception as exc:
            logger.error(f"Solver error: {exc}")
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=0.0,
                error_message=str(exc),
            )

    def solve_multi_objective(
        self,
        problem: OptimizationProblem,
        config: MultiObjectiveConfig,
        solver_name: str | None = None,
    ) -> list[ParetoPoint]:
        """Solve a multi-objective problem via D-02 gate or scalarization loops."""
        name = solver_name or self._default_solver_name
        adapter = registry.get(name)

        # D-02: native delegation gate. If the adapter advertises multi-objective
        # support AND implements solve_multi_objective, delegate natively.
        # Otherwise fall through to the orchestrator-owned scalarization loops.
        # hasattr (not isinstance) is intentional — Research §Pitfall 2/4 warns
        # against @runtime_checkable on Protocol in Python 3.12, so we never use
        # isinstance(adapter, MultiObjectiveSolverAdapter) at runtime.
        if adapter.capabilities.supports_multi_objective and hasattr(
            adapter, "solve_multi_objective"
        ):
            return adapter.solve_multi_objective(problem, config)

        if config.mode == "epsilon":
            return self._solve_epsilon_constraint(problem, config, adapter)
        elif config.mode == "weighted":
            return self._solve_weighted(problem, config, adapter)
        else:
            raise ValueError(f"Unknown multi-objective mode: {config.mode}")

    def _is_nondominated(
        self,
        new_f1: float,
        new_f2: float,
        points: list[ParetoPoint],
        *,
        sense1: ObjectiveSense = ObjectiveSense.MINIMIZE,
        sense2: ObjectiveSense = ObjectiveSense.MINIMIZE,
    ) -> bool:
        """Check if a new point (new_f1, new_f2) is not dominated by any existing Pareto point.

        A point A dominates B if A is at least as good on ALL objectives and strictly
        better on at least one. Comparison direction follows objective sense:
        - MINIMIZE: dominated if existing point value <= new value
        - MAXIMIZE: dominated if existing point value >= new value
        """
        for pt in points:
            dom1 = pt.f1 <= new_f1 if sense1 == ObjectiveSense.MINIMIZE else pt.f1 >= new_f1
            dom2 = pt.f2 <= new_f2 if sense2 == ObjectiveSense.MINIMIZE else pt.f2 >= new_f2
            strict1 = pt.f1 < new_f1 if sense1 == ObjectiveSense.MINIMIZE else pt.f1 > new_f1
            strict2 = pt.f2 < new_f2 if sense2 == ObjectiveSense.MINIMIZE else pt.f2 > new_f2
            if dom1 and dom2 and (strict1 or strict2):
                return False  # dominated
        return True

    def _solve_weighted(
        self,
        problem: OptimizationProblem,
        config: MultiObjectiveConfig,
        adapter: object,
    ) -> list[ParetoPoint]:
        """Weighted-sum scalarization: builds OptimizationProblem per weight and calls adapter.solve()."""
        obj1 = config.objectives[0]
        obj2 = config.objectives[1]
        variable_names = [v.name for v in problem.variables]

        label1 = obj1.label or "Objective 1"
        label2 = obj2.label or "Objective 2"

        weights = np.linspace(0.0, 1.0, config.n_points)
        pareto_points: list[ParetoPoint] = []

        for w1 in weights:
            w2 = 1.0 - w1
            try:
                scalar_obj = _build_weighted_objective(obj1, obj2, w1, w2)
                subproblem = _build_scalarized_problem(problem, scalar_obj)
                result = adapter.solve(subproblem)

                if result.status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
                    continue
                if not result.solution:
                    continue

                f1_val = _compute_objective_value(result, obj1, self.parser, variable_names)
                f2_val = _compute_objective_value(result, obj2, self.parser, variable_names)
                point = ParetoPoint(
                    f1=f1_val,
                    f2=f2_val,
                    solution=dict(result.solution),
                    objective_values={label1: f1_val, label2: f2_val},
                )
                pareto_points.append(point)

            except Exception as e:
                logger.debug(f"Weighted solve failed for w1={w1}: {e}")
                continue

        # Deduplicate approximately equal points
        unique_points: list[ParetoPoint] = []
        for pt in pareto_points:
            is_duplicate = any(
                abs(pt.f1 - up.f1) < 1e-6 and abs(pt.f2 - up.f2) < 1e-6 for up in unique_points
            )
            if not is_duplicate:
                unique_points.append(pt)

        return unique_points

    def _solve_epsilon_constraint(
        self,
        problem: OptimizationProblem,
        config: MultiObjectiveConfig,
        adapter: object,
    ) -> list[ParetoPoint]:
        """Epsilon-constraint: finds f2 range, then calls adapter.solve() per epsilon subproblem."""
        obj1 = config.objectives[0]
        obj2 = config.objectives[1]
        variable_names = [v.name for v in problem.variables]

        label1 = obj1.label or "Objective 1"
        label2 = obj2.label or "Objective 2"

        # --- Step 1: Find f2 optimal (optimize obj2 alone) ---
        scalar_obj2 = Objective(sense=obj2.sense, expression=obj2.expression)
        sub_opt = _build_scalarized_problem(problem, scalar_obj2)
        result_opt = adapter.solve(sub_opt)

        if result_opt.status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
            logger.warning("Could not find f2 optimal — returning empty Pareto set")
            return []

        f2_optimal = _compute_objective_value(result_opt, obj2, self.parser, variable_names)

        # --- Step 2: Find f2 worst (optimize f2 in opposite direction) ---
        opposite = (
            ObjectiveSense.MAXIMIZE
            if obj2.sense == ObjectiveSense.MINIMIZE
            else ObjectiveSense.MINIMIZE
        )
        scalar_obj2_w = Objective(sense=opposite, expression=obj2.expression)
        sub_worst = _build_scalarized_problem(problem, scalar_obj2_w)
        result_worst = adapter.solve(sub_worst)

        if result_worst.status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
            # Expand range in the direction that worsens obj2 per its sense.
            # MINIMIZE: worst is higher, so multiply by 2 (or subtract if negative).
            # MAXIMIZE: worst is lower, so halve (or add if negative).
            if obj2.sense == ObjectiveSense.MINIMIZE:
                f2_worst = f2_optimal * 2.0 if f2_optimal > 0 else f2_optimal - 1.0
            else:  # MAXIMIZE: worst is a lower value
                f2_worst = f2_optimal / 2.0 if f2_optimal > 0 else f2_optimal + 1.0
        else:
            f2_worst = _compute_objective_value(result_worst, obj2, self.parser, variable_names)

        if abs(f2_worst - f2_optimal) < 1e-9:
            f2_worst = f2_optimal + 1.0

        epsilons = np.linspace(f2_worst, f2_optimal, config.n_points + 1)[:-1]

        # --- Step 3: For each epsilon, solve constrained problem ---
        pareto_points: list[ParetoPoint] = []

        for eps in epsilons:
            try:
                if obj2.sense == ObjectiveSense.MINIMIZE:
                    eps_constraint = f"{obj2.expression} <= {eps}"
                else:
                    eps_constraint = f"{obj2.expression} >= {eps}"

                scalar_obj1 = Objective(sense=obj1.sense, expression=obj1.expression)
                subproblem = _build_scalarized_problem(
                    problem, scalar_obj1, extra_constraint_exprs=[eps_constraint]
                )
                result = adapter.solve(subproblem)

                if (
                    result.status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
                    or not result.solution
                ):
                    continue

                f1_val = _compute_objective_value(result, obj1, self.parser, variable_names)
                f2_val = _compute_objective_value(result, obj2, self.parser, variable_names)
                point = ParetoPoint(
                    f1=f1_val,
                    f2=f2_val,
                    solution=dict(result.solution),
                    objective_values={label1: f1_val, label2: f2_val},
                )
                pareto_points.append(point)

            except Exception as exc:
                logger.debug(f"Epsilon-constraint solve failed for eps={eps}: {exc}")
                continue

        return pareto_points


def get_solver_service(solver_name: str | None = None) -> SolverService:
    """Return a fresh SolverService per call.

    Not cached — the singleton we had before created test-order brittleness
    with register_default_adapters(). Init cost is negligible
    (ExpressionParser only). Registry validation happens inside
    SolverService.solve() when the adapter is resolved.
    """
    if solver_name is not None:
        return SolverService(solver_name=solver_name)
    return SolverService()
