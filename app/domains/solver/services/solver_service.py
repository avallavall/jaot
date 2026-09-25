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

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

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
    ObjectiveSpec,
    OptimizationProblem,
    OptimizationResult,
    ParetoPoint,
    ProgressPoint,
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
            parts.append(f"{term.coefficient!r}*{term.variables[0]}")
        elif len(term.variables) == 2:
            parts.append(f"{term.coefficient!r}*{term.variables[0]}*{term.variables[1]}")
    return " + ".join(parts)


def _build_weighted_objective(
    obj1: Objective | ObjectiveSpec,
    obj2: Objective | ObjectiveSpec,
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


def multi_objective_view(
    problem: OptimizationProblem, config: MultiObjectiveConfig
) -> OptimizationProblem:
    """The problem as its scalarized subproblems carry it, for classification.

    Every subproblem optimises one objective and puts the other one, or both,
    in a constraint. A quadratic objective therefore ends up in a constraint
    somewhere, and a solver that cannot take one cannot run the front. The
    problem's own ``objective`` is not solved at all in multi-objective mode,
    so it is replaced.
    """
    obj1, obj2 = config.objectives[0], config.objectives[1]
    held = [
        Constraint(name=f"_mo_objective_{n}", expression=f"{spec.expression} <= 0")
        for n, spec in enumerate((obj1, obj2), start=1)
    ]
    return problem.model_copy(
        update={
            "objective": Objective(sense=obj1.sense, expression=obj1.expression),
            "constraints": [*problem.constraints, *held],
        }
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
        on_progress: Callable[[ProgressPoint], None] | None = None,
    ) -> OptimizationResult:
        """Resolve adapter via registry and delegate. Raises SolverNotFoundError if not registered.

        ``on_progress`` (optional) is forwarded to the adapter for Live Solve
        streaming; adapters whose ``capabilities.supports_progress`` is False
        accept and ignore it.
        """
        name = solver_name or self._default_solver_name
        # Registry errors (not found / unavailable) are contract violations —
        # propagate them so callers can catch SolverNotFoundError explicitly.
        adapter = registry.get(name)
        try:
            return adapter.solve(problem, warm_start=warm_start_solution, on_progress=on_progress)
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
        """Solve a multi-objective problem and return its Pareto front."""
        return self.solve_pareto_front(problem, config, solver_name=solver_name).points

    def solve_pareto_front(
        self,
        problem: OptimizationProblem,
        config: MultiObjectiveConfig,
        solver_name: str | None = None,
    ) -> ParetoFront:
        """Solve a multi-objective problem via the D-02 gate or the scalarization loops.

        Returns the front and, when it is empty, the verdict that explains why.

        Raises:
            MultiObjectiveSolveError: no point was found and the solver failed
                (an error, not a verdict such as "infeasible"). An empty front
                used to be reported for a model the solver could not run at
                all, and it read as "this model has no trade-offs".
        """
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
            return ParetoFront(points=adapter.solve_multi_objective(problem, config))

        run = _Scalarization(adapter, problem, config, self.parser)
        if config.mode == "epsilon":
            points = self._solve_epsilon_constraint(run, config)
        elif config.mode == "weighted":
            points = self._solve_weighted(run, config)
        else:
            raise ValueError(f"Unknown multi-objective mode: {config.mode}")
        front = self._pareto_front(points, sense1=run.obj1.sense, sense2=run.obj2.sense)
        return run.finish(front)

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

    def _pareto_front(
        self,
        points: list[ParetoPoint],
        *,
        sense1: ObjectiveSense,
        sense2: ObjectiveSense,
    ) -> list[ParetoPoint]:
        """The non-dominated, duplicate-free subset of *points*, in the order found.

        Both scalarization loops solve the same model once per weight or per
        epsilon, and several of those runs land on the same corner: a front of
        ten reported seven copies of (0, 0) and three real points, counted and
        drawn as ten trade-offs. A scalarized run can also return a point
        another run beats outright, which is not a trade-off either.

        A point already on the list dominates the new one, or the new one
        dominates points already there — both directions have to be checked, so
        the survivors are re-filtered against each newcomer.
        """
        kept: list[ParetoPoint] = []
        for point in points:
            if any(_same_point(point, other) for other in kept):
                continue
            if not self._is_nondominated(point.f1, point.f2, kept, sense1=sense1, sense2=sense2):
                continue
            kept = [
                other
                for other in kept
                if self._is_nondominated(other.f1, other.f2, [point], sense1=sense1, sense2=sense2)
            ]
            kept.append(point)
        return kept

    def _solve_weighted(
        self,
        run: _Scalarization,
        config: MultiObjectiveConfig,
    ) -> list[ParetoPoint]:
        """Weighted sum, swept over ``n_points`` weights from objective 2 to objective 1.

        The two ends are solved lexicographically instead of with a zero weight.
        A zero weight lets the solver return any of the points that tie on the
        other objective, and the one it picked could be dominated: with
        max 3x+5y against min 2x+4y it returned (10, 8) where (12, 8) was
        feasible.

        Each objective is divided by its range between the two ends before it is
        weighted. Without that, the weights only mean something when both
        objectives are in the same units: a cost in millions against a count in
        tens puts every interior weight on the cost end of the front.
        """
        obj1, obj2 = run.obj1, run.obj2
        best_for_2 = run.lexicographic_end(first=obj2, second=obj1)  # weight 1 on objective 2
        best_for_1 = run.lexicographic_end(first=obj1, second=obj2)  # weight 1 on objective 1

        scale1 = scale2 = 1.0
        if best_for_1 is not None and best_for_2 is not None:
            range1 = abs(best_for_1.f1 - best_for_2.f1)
            range2 = abs(best_for_2.f2 - best_for_1.f2)
            if range1 < _SAME_POINT_TOLERANCE or range2 < _SAME_POINT_TOLERANCE:
                # One point is best on both objectives: there is no trade-off to sweep.
                return [best_for_1, best_for_2]
            scale1, scale2 = range1, range2

        points = [best_for_2] if best_for_2 is not None else []
        for w1 in np.linspace(0.0, 1.0, config.n_points)[1:-1]:
            c1 = float(w1) / scale1
            c2 = (1.0 - float(w1)) / scale2
            # A common factor does not move the optimum. Dividing it out keeps
            # the coefficients near 1 instead of at 1e-7 for a wide range.
            largest = max(c1, c2)
            scalar = _build_weighted_objective(obj1, obj2, c1 / largest, c2 / largest)
            result = run.solve(scalar)
            if result is not None:
                points.append(run.point(result))
        if best_for_1 is not None:
            points.append(best_for_1)
        return points

    def _solve_epsilon_constraint(
        self,
        run: _Scalarization,
        config: MultiObjectiveConfig,
    ) -> list[ParetoPoint]:
        """Epsilon constraint: best objective 1 for ``n_points`` limits on objective 2.

        The limits run from the value objective 2 takes where objective 1 is at
        its best, to the best value objective 2 can reach. Both ends are points
        of the front, solved lexicographically. The old grid stopped one step
        short of the best value of objective 2, so that end of the front was
        never shown.
        """
        obj1, obj2 = run.obj1, run.obj2
        best_for_2 = run.lexicographic_end(first=obj2, second=obj1)
        if best_for_2 is None:
            # Objective 2 has no best value (infeasible, unbounded or an error),
            # so there is nothing to put a limit on.
            return []
        f2_best = best_for_2.f2
        best_for_1 = run.lexicographic_end(first=obj1, second=obj2)
        if best_for_1 is not None:
            f2_far = best_for_1.f2
            if abs(f2_far - f2_best) < _SAME_POINT_TOLERANCE:
                # One point is best on both objectives: there is no trade-off.
                return [best_for_1, best_for_2]
        else:
            f2_far = self._far_end_without_best_first(run, f2_best)

        limits = np.linspace(f2_far, f2_best, config.n_points)
        points = [best_for_1] if best_for_1 is not None else []
        # Without a best point for objective 1, the far end is solved like any
        # other limit. The near end is always the lexicographic point.
        for eps in limits[1:-1] if best_for_1 is not None else limits[:-1]:
            operator = "<=" if obj2.sense == ObjectiveSense.MINIMIZE else ">="
            limit = f"{obj2.expression} {operator} {float(eps)!r}"
            result = run.solve(Objective(sense=obj1.sense, expression=obj1.expression), [limit])
            if result is not None:
                points.append(run.point(result))
        points.append(best_for_2)
        return points

    def _far_end_without_best_first(self, run: _Scalarization, f2_best: float) -> float:
        """Where the epsilon grid starts when objective 1 has no best value.

        That is the worst value objective 2 can take. When it has none either
        (unbounded the other way) or it equals the best value, the grid steps
        away from the best value in the direction that makes objective 2 WORSE.
        The old step went the other way whenever the optimum was zero or
        negative, and always for a constant MAXIMIZE objective: every epsilon
        then asked for better than the optimum, every subproblem was
        infeasible, and the front came back empty.
        """
        obj2 = run.obj2
        opposite = (
            ObjectiveSense.MAXIMIZE
            if obj2.sense == ObjectiveSense.MINIMIZE
            else ObjectiveSense.MINIMIZE
        )
        step = max(1.0, abs(f2_best))
        worse = f2_best + step if obj2.sense == ObjectiveSense.MINIMIZE else f2_best - step
        result = run.solve(Objective(sense=opposite, expression=obj2.expression))
        if result is None:
            return worse
        f2_worst = run.value(result, obj2)
        if abs(f2_worst - f2_best) < 1e-9:
            return worse
        return f2_worst


@dataclass(frozen=True)
class ParetoFront:
    """A multi-objective run's answer: the front, and why it is empty when it is."""

    points: list[ParetoPoint]
    #: The verdict of the solve that left the front empty (infeasible,
    #: unbounded, time limit). None when the front has points.
    empty_status: SolverStatus | None = None


class MultiObjectiveSolveError(RuntimeError):
    """The solver failed on the subproblems, so no front could be computed."""


#: How far a held objective may move from the value it is held at, relative to
#: its size. The value comes from a solution that satisfies the model only
#: within the solver's own tolerance (about 1e-6), so holding it exactly could
#: make the second solve infeasible. A slack far below that tolerance cannot
#: buy a visibly different point.
_HOLD_TOLERANCE = 1e-9


def _hold(objective: ObjectiveSpec, value: float) -> str:
    """A constraint that keeps ``objective`` at least as good as ``value``."""
    slack = _HOLD_TOLERANCE * max(1.0, abs(value))
    if objective.sense == ObjectiveSense.MAXIMIZE:
        return f"{objective.expression} >= {value - slack!r}"
    return f"{objective.expression} <= {value + slack!r}"


class _Scalarization:
    """One multi-objective run: the solver, the base problem and every refusal it gave.

    Each subproblem is a fresh OptimizationProblem handed to ``adapter.solve()``.
    No solver API is called here.
    """

    def __init__(
        self,
        adapter: object,
        problem: OptimizationProblem,
        config: MultiObjectiveConfig,
        parser: ExpressionParser,
    ) -> None:
        self.adapter = adapter
        self.problem = problem
        self.obj1, self.obj2 = config.objectives[0], config.objectives[1]
        self.label1 = self.obj1.label or "Objective 1"
        self.label2 = self.obj2.label or "Objective 2"
        self.parser = parser
        self.variable_names = [v.name for v in problem.variables]
        #: Every subproblem that did not produce a solution, in the order solved.
        self.refusals: list[OptimizationResult] = []

    def solve(
        self, objective: Objective, extra_constraints: list[str] | None = None
    ) -> OptimizationResult | None:
        """Solve one subproblem. None when it produced no solution."""
        subproblem = _build_scalarized_problem(self.problem, objective, extra_constraints)
        try:
            result = self.adapter.solve(subproblem)  # type: ignore[attr-defined]
        except (SolverNotFoundError, SolverUnavailableError):
            raise
        except Exception as exc:  # an adapter bug must not lose the other points
            logger.debug("Multi-objective subproblem failed: %s", exc)
            result = OptimizationResult(
                status=SolverStatus.ERROR, solve_time_seconds=0.0, error_message=str(exc)
            )
        if result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE) and result.solution:
            return result
        self.refusals.append(result)
        return None

    def value(self, result: OptimizationResult, objective: ObjectiveSpec) -> float:
        """The value ``objective`` takes at ``result``'s solution."""
        spec = Objective(sense=objective.sense, expression=objective.expression)
        return _compute_objective_value(result, spec, self.parser, self.variable_names)

    def point(self, result: OptimizationResult) -> ParetoPoint:
        """The Pareto point ``result`` stands for."""
        f1 = self.value(result, self.obj1)
        f2 = self.value(result, self.obj2)
        return ParetoPoint(
            f1=f1,
            f2=f2,
            solution=dict(result.solution or {}),
            objective_values={self.label1: f1, self.label2: f2},
        )

    def lexicographic_end(
        self, *, first: ObjectiveSpec, second: ObjectiveSpec
    ) -> ParetoPoint | None:
        """The best point for ``first``, and among those the best for ``second``.

        Optimising ``first`` alone can land on any of the points that tie on
        it, and some of them are worse on ``second`` than they need to be: that
        point is dominated, and it is the end of the front. So ``first`` is held
        at its optimum and ``second`` is optimised.

        None when ``first`` has no optimum. When the second solve fails, the
        first answer is kept: it is still optimal for ``first``.
        """
        lead = self.solve(Objective(sense=first.sense, expression=first.expression))
        if lead is None:
            return None
        held = self.solve(
            Objective(sense=second.sense, expression=second.expression),
            [_hold(first, self.value(lead, first))],
        )
        return self.point(held if held is not None else lead)

    def finish(self, points: list[ParetoPoint]) -> ParetoFront:
        """The run's answer. Raises when the solver failed on any subproblem.

        A failed subproblem is not a verdict about the model: the points it
        would have given are missing, and the front that is left looks
        complete. HiGHS refusing a quadratic objective still returned the one
        end whose subproblems were linear.
        """
        for refusal in self.refusals:
            if refusal.status == SolverStatus.ERROR:
                raise MultiObjectiveSolveError(
                    refusal.error_message or "The solver failed on a multi-objective subproblem."
                )
        if points or not self.refusals:
            return ParetoFront(points=points)
        return ParetoFront(points=[], empty_status=self.refusals[0].status)


#: How close two objective values have to be to count as the same point. The
#: numbers come back from a solver, so exact equality would keep two runs that
#: landed on the same corner and differ in the last bit.
_SAME_POINT_TOLERANCE = 1e-6


def _same_point(one: ParetoPoint, other: ParetoPoint) -> bool:
    """True when two Pareto points are the same trade-off."""
    return (
        abs(one.f1 - other.f1) < _SAME_POINT_TOLERANCE
        and abs(one.f2 - other.f2) < _SAME_POINT_TOLERANCE
    )


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
