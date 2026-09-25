"""JAOS adapter — the JAOS Python library as a SolverAdapter.

JAOS (github.com/avallavall/jaos, Apache-2.0) is a C library with a ctypes
binding and no Python dependency of its own. JAOT installs its manylinux wheel
from the project's GitHub Release (see requirements.txt).

The model is built from arrays: the columns in one ``load``, the rows in one
``add_rows`` in compressed sparse row form. JAOS refuses a row that names a
column twice; ``ExpressionParser`` has already merged repeated names by the
time the rows are built.

IMPORTANT: ``jaos`` is imported LAZILY inside is_available(), _read_version()
and solve() only. Importing it loads ``libjaos.so``, and a process without the
wheel must still start.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from typing import Any

from app.domains.solver.adapters._cli_solver import relative_gap
from app.domains.solver.adapters.base import (
    STRICT_EPSILON,
    CachedVersion,
    SolverCapabilities,
    binary_bounds,
    quadratic_term_refusal,
    refusal_fields,
)
from app.domains.solver.constraint_activity import is_binding_within_bounds
from app.domains.solver.sensitivity_values import publishable_value
from app.domains.solver.services._naming import constraint_label
from app.domains.solver.services.expression_parser import ExpressionParser
from app.schemas.optimization import (
    ConstraintSensitivity,
    OptimizationProblem,
    OptimizationResult,
    ProgressPoint,
    SensitivityResult,
    SolverStatus,
    VariableSensitivity,
    VariableSolution,
    VariableType,
)

logger = logging.getLogger(__name__)

#: The same ceiling the SCIP handler uses. JAOS reports progress at every node,
#: and a chart cannot show more points than it has pixels.
_MAX_PROGRESS_POINTS = 500

#: A point is recorded at every new incumbent. A point that only moves the bound
#: waits this long after the previous one. JAOS calls back at every node, and
#: each point is also a websocket message while Live Solve is open.
_BOUND_POINT_INTERVAL_SECONDS = 0.25

#: With neither the incumbent nor the bound moving, a point still goes out this
#: often. Without it the node count on the Live Solve panel froze: 217 nodes for
#: 16 seconds on a search that had reached 21,527 (driving the studio,
#: 2026-09-24), which reads as a stuck solve.
_HEARTBEAT_SECONDS = 2.0

# JAOS's ``SolveStatus`` by name. Every stop on a budget maps to TIME_LIMIT, as
# in the other adapters: the run kept whatever incumbent it had.
_STATUS_MAP: dict[str, SolverStatus] = {
    "OPTIMAL": SolverStatus.OPTIMAL,
    "INFEASIBLE": SolverStatus.INFEASIBLE,
    "UNBOUNDED": SolverStatus.UNBOUNDED,
    "TIME_LIMIT": SolverStatus.TIME_LIMIT,
    "NODE_LIMIT": SolverStatus.TIME_LIMIT,
    "WORK_LIMIT": SolverStatus.TIME_LIMIT,
    "INTERRUPTED": SolverStatus.TIME_LIMIT,
    "NUMERICAL_ERROR": SolverStatus.ERROR,
    "NOT_RUN": SolverStatus.ERROR,
}


def _finite_or_none(value: float | None) -> float | None:
    """JAOS says "no bound yet" with an infinity."""
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def _row_bounds(operator: str, rhs: float) -> tuple[float, float]:
    """A JAOT operator as the two sides of a JAOS row."""
    if operator == "<=":
        return (-math.inf, rhs)
    if operator == ">=":
        return (rhs, math.inf)
    if operator in ("==", "="):
        return (rhs, rhs)
    if operator == "<":
        return (-math.inf, rhs - STRICT_EPSILON)
    if operator == ">":
        return (rhs + STRICT_EPSILON, math.inf)
    raise ValueError(f"Unknown constraint operator {operator!r}.")


def _linear_only(term_variables: list[str], constraint: str | None) -> None:
    """Refuse a quadratic term instead of solving without it.

    ``constraint`` is the row's label, or None for a term in the objective.
    """
    if len(term_variables) >= 2:
        where = "the objective" if constraint is None else f"constraint {constraint!r}"
        raise quadratic_term_refusal(
            f"JAOS in JAOT takes linear models only — quadratic term "
            f"'{'*'.join(term_variables)}' in {where}. Use SCIP (or automatic "
            "selection) for quadratic models.",
            solver="JAOS",
            variables=term_variables,
            constraint=constraint,
        )


class _ProgressRecorder:
    """Turn JAOS's progress callback into ``ProgressPoint`` snapshots.

    JAOS calls back from every relaxation and once per node, with the node
    count, the best bound and the incumbent (all in the model's own sense, the
    objective constant included). A point needs an incumbent: before the first
    one there is a bound and nothing to compare it against, which is the same
    rule the SCIP and CBC traces follow.
    """

    def __init__(self, on_progress: Callable[[ProgressPoint], None] | None) -> None:
        self.history: list[ProgressPoint] = []
        self._on_progress = on_progress
        self._t0 = time.monotonic()
        self._last_emit = -math.inf

    def __call__(self, progress: Any) -> None:
        point = self._record(progress)
        if point is None or self._on_progress is None:
            return
        # An exception raised here stops a JAOS solve, and the Protocol says a
        # failing progress consumer must never do that. Only the consumer is
        # guarded. An exception from a signal handler (the worker's soft time
        # limit) must reach JAOS, which stops and raises it from solve().
        try:
            self._on_progress(point)
        except Exception as exc:
            logger.debug("Live Solve progress consumer failed: %s", exc)

    def _record(self, progress: Any) -> ProgressPoint | None:
        incumbent = _finite_or_none(progress.incumbent)
        if incumbent is None:
            return None
        bound = _finite_or_none(progress.bound)
        now = time.monotonic() - self._t0
        last = self.history[-1] if self.history else None
        if last is not None and last.objective == incumbent:
            since = now - self._last_emit
            if since < _HEARTBEAT_SECONDS and (
                last.dual_bound == bound or since < _BOUND_POINT_INTERVAL_SECONDS
            ):
                return None
        point = ProgressPoint(
            iteration=len(self.history) + 1,
            node=int(progress.nodes),
            objective=incumbent,
            primal_bound=incumbent,
            dual_bound=bound,
            gap=relative_gap(incumbent, bound),
            elapsed_seconds=round(now, 3),
        )
        self.history.append(point)
        self._last_emit = now
        return point

    def finish(self, result: OptimizationResult, solve_time: float) -> list[ProgressPoint]:
        """The trace, closed by a point at the answer the result reports.

        Without it the trace ends at the last callback, which can be earlier and
        at a different bound than the numbers printed next to the chart.
        """
        history = list(self.history)
        if result.objective_value is not None:
            final = ProgressPoint(
                iteration=len(history) + 1,
                node=result.nodes,
                objective=result.objective_value,
                primal_bound=result.objective_value,
                dual_bound=result.dual_bound,
                gap=result.gap,
                elapsed_seconds=round(solve_time, 3),
            )
            last = history[-1] if history else None
            if last is None or (last.objective, last.dual_bound, last.node) != (
                final.objective,
                final.dual_bound,
                final.node,
            ):
                history.append(final)
        if len(history) > _MAX_PROGRESS_POINTS:
            step = (len(history) - 2) / (_MAX_PROGRESS_POINTS - 2)
            indices = (
                [0]
                + [int(1 + i * step) for i in range(_MAX_PROGRESS_POINTS - 2)]
                + [len(history) - 1]
            )
            history = [history[i] for i in dict.fromkeys(indices)]
        return history


class _Built:
    """The arrays one solve was built from, kept to read the answer back."""

    def __init__(self) -> None:
        self.col_map: dict[str, int] = {}
        self.row_lower: list[float] = []
        self.row_upper: list[float] = []
        self.has_integer = False


class JAOSAdapter(CachedVersion):
    """JAOS solver adapter implementing the SolverAdapter Protocol."""

    capabilities: SolverCapabilities = SolverCapabilities(
        name="jaos",
        supports_continuous=True,
        supports_integer=True,
        supports_binary=True,
        # JAOS solves convex quadratic models only, and this flag cannot say
        # "convex only". A linear adapter refuses the model instead.
        supports_quadratic=False,
        supports_sensitivity=True,  # exact LP duals; none for a MIP
        supports_warm_start=True,  # set_mip_start, partial starts completed by JAOS
        supports_multi_objective=False,
        supports_progress=True,  # progress callback at every node (Live Solve)
    )

    def __init__(self) -> None:
        self._available: bool | None = None
        self._parser = ExpressionParser()

    def is_available(self) -> bool:
        """Cached import check. The wheel cannot appear or vanish mid-process.

        A wheel whose ``libjaos.so`` cannot be loaded raises
        ``jaos.LibraryNotFound``, a subclass of ImportError.
        """
        if self._available is None:
            try:
                import jaos  # noqa: F401, PLC0415

                self._available = True
            except ImportError:
                self._available = False
        return self._available

    @staticmethod
    def _read_version() -> str | None:
        """The library's version and the commit it was built from.

        Two builds between tags carry the same version, so the commit goes on
        too: "0.5.0+g09e99ade3094".
        """
        try:
            import jaos  # noqa: PLC0415

            commit = jaos.build_commit()
            return f"{jaos.version()}+g{commit}" if commit else str(jaos.version())
        except Exception as exc:
            logger.debug("Could not read the JAOS version: %s", exc)
            return None

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
        on_progress: Callable[[ProgressPoint], None] | None = None,
    ) -> OptimizationResult:
        """Solve a single-objective linear or mixed-integer problem with JAOS."""
        import jaos  # noqa: PLC0415 — lazy import; do not move to module level

        start_time = time.monotonic()
        model = None
        try:
            model = jaos.Model()
            built = self._build(jaos, model, problem)
            self._configure(jaos, model, problem)

            start = warm_start or problem.heuristic_warm_start
            start_given = self._apply_start(model, built, start)

            recorder = _ProgressRecorder(on_progress)
            model.set_progress_callback(recorder)
            model.solve()

            solve_time = time.monotonic() - start_time
            result = self._extract_result(jaos, model, built, problem, solve_time)
            if start_given:
                result.warm_start_used = bool(model.mip_report().start_accepted)
            history = recorder.finish(result, solve_time)
            if history:
                result.progress_history = history
            return result

        # Only the failures that belong to this solve are turned into a result.
        # Anything else is passed on. That includes an exception a signal
        # handler raised while JAOS ran, such as the worker's soft time limit:
        # JAOS stops, hands it back from solve(), and the caller owns it.
        except jaos.JaosError as exc:
            logger.error("JAOS solver error: %s", exc)
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.monotonic() - start_time,
                error_message=str(exc),
            )
        except (ValueError, KeyError) as exc:
            logger.error("JAOS could not build the model: %s", exc)
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.monotonic() - start_time,
                error_message=str(exc),
                **refusal_fields(exc),
            )
        finally:
            if model is not None:
                model.close()

    def _build(self, jaos: Any, model: Any, problem: OptimizationProblem) -> _Built:
        """Columns, integrality, objective and rows, in that order."""
        built = _Built()
        n = len(problem.variables)
        lower: list[float] = []
        upper: list[float] = []
        for idx, var in enumerate(problem.variables):
            if var.type == VariableType.BINARY:
                lb, ub = binary_bounds(var.lower_bound, var.upper_bound)
            else:
                lb = -math.inf if var.lower_bound is None else float(var.lower_bound)
                ub = math.inf if var.upper_bound is None else float(var.upper_bound)
            lower.append(lb)
            upper.append(ub)
            built.col_map[var.name] = idx

        objective = self._parser.parse_expression(problem.objective.expression)
        cost = [0.0] * n
        for term in objective.terms:
            _linear_only(term.variables, None)
            idx = built.col_map.get(term.variables[0]) if term.variables else None
            if idx is not None:
                cost[idx] += float(term.coefficient)
        sense = (
            jaos.ObjSense.MAXIMIZE
            if problem.objective.sense.lower() == "maximize"
            else jaos.ObjSense.MINIMIZE
        )
        model.load(
            n,
            0,
            cost,
            lower,
            upper,
            [],
            [],
            sense=sense,
            obj_offset=float(objective.constant),
        )

        for idx, var in enumerate(problem.variables):
            if var.type in (VariableType.INTEGER, VariableType.BINARY):
                model.set_col_integer(idx)
                built.has_integer = True

        starts = [0]
        index: list[int] = []
        value: list[float] = []
        for constraint in problem.constraints:
            parsed = self._parser.parse_constraint(constraint.expression)
            label = constraint.name or constraint.expression
            for term in parsed.lhs.terms:
                _linear_only(term.variables, label)
                col = built.col_map.get(term.variables[0]) if term.variables else None
                if col is not None:
                    index.append(col)
                    value.append(float(term.coefficient))
            starts.append(len(index))
            lo, up = _row_bounds(parsed.operator, float(parsed.rhs))
            built.row_lower.append(lo)
            built.row_upper.append(up)
        if built.row_lower:
            model.add_rows(built.row_lower, built.row_upper, starts, index, value)
        return built

    @staticmethod
    def _configure(jaos: Any, model: Any, problem: OptimizationProblem) -> None:
        opts = problem.options
        model.set_time_limit(float(opts.time_limit_seconds))
        # RELATIVE is |incumbent - bound| / |incumbent|, the rule SCIP and HiGHS
        # stop on. JAOS's default adds 1 to the denominator. A gap of 0 means 0.
        model.set_mip_gap(float(opts.gap_tolerance))
        model.set_mip_gap_rule(jaos.GapRule.RELATIVE)
        # JAOT's 0 is "auto" and JAOS's 0 is every core. A MIP still explores
        # one node at a time: the tree batch stays at its default, which keeps
        # the answer the same on every machine.
        model.set_threads(int(opts.threads))
        if opts.verbose:
            model.set_log_callback(lambda _level, line: logger.info("JAOS: %s", line))

    @staticmethod
    def _apply_start(model: Any, built: _Built, start: dict[str, float] | None) -> bool:
        """Hand JAOS a MIP start. Returns whether one was given.

        A partial start is fine: JAOS fixes the integer columns it names and
        completes the rest. An infeasible one is dropped by JAOS, and
        ``mip_report().start_accepted`` then says so. An LP has no use for it.
        """
        if not start or not built.has_integer:
            return False
        by_column = {
            built.col_map[name]: float(value)
            for name, value in start.items()
            if name in built.col_map and value is not None
        }
        if not by_column:
            return False
        model.set_mip_start(by_column)
        return True

    def _extract_result(
        self,
        jaos: Any,
        model: Any,
        built: _Built,
        problem: OptimizationProblem,
        solve_time: float,
    ) -> OptimizationResult:
        raw = model.status
        status = _STATUS_MAP.get(raw.name)
        if status is None:
            logger.warning("Unknown JAOS status %r — returning ERROR", raw)
            status = SolverStatus.ERROR

        report = model.mip_report() if built.has_integer else None
        iterations = int(model.iterations)
        nodes = int(report.nodes) if report is not None else None
        bound = _finite_or_none(report.bound) if report is not None else None

        objective: float | None = None
        col_values: list[float] | None = None
        solution = None
        if status is SolverStatus.OPTIMAL:
            objective = float(model.objective())
            solution = model.solution()
            col_values = list(solution.col_value)
        elif status is SolverStatus.TIME_LIMIT and report is not None and report.has_incumbent:
            # A run stopped by a limit keeps the best point it found.
            # ``objective()`` and ``solution()`` raise there; this does not.
            objective, col_values = model.mip_incumbent()
            objective = float(objective)

        if objective is None or col_values is None:
            result = OptimizationResult(
                status=status,
                solve_time_seconds=solve_time,
                iterations=iterations,
                nodes=nodes,
                dual_bound=bound if status is SolverStatus.TIME_LIMIT else None,
            )
            if status is SolverStatus.ERROR:
                result.error_message = f"JAOS stopped with status {raw.name}."
            return result

        if status is SolverStatus.OPTIMAL and bound is None:
            # An LP has no branch-and-bound bound. At the optimum the bound is
            # the answer, as in the HiGHS, CBC and GLPK adapters.
            bound = objective
        gap = relative_gap(objective, bound)

        variables: list[VariableSolution] = []
        values: dict[str, float] = {}
        for var in problem.variables:
            idx = built.col_map[var.name]
            val = float(col_values[idx])
            variables.append(
                VariableSolution(
                    name=var.name,
                    value=val,
                    type=var.type,
                    family=var.family,
                    index_tuple=var.index_tuple,
                )
            )
            values[var.name] = val

        result = OptimizationResult(
            status=status,
            objective_value=objective,
            solve_time_seconds=solve_time,
            variables=variables,
            solution=values,
            iterations=iterations,
            nodes=nodes,
            gap=gap,
            dual_bound=bound,
        )

        # Duals only for an LP at its optimum. A MIP's duals are the last
        # node's, which price a different model than the answer shown.
        if status is SolverStatus.OPTIMAL and not built.has_integer and solution is not None:
            try:
                result.sensitivity = self._sensitivity(solution, built, problem, col_values)
            except Exception as exc:  # never let sensitivity break a valid solve
                logger.warning("JAOS sensitivity extraction failed: %s", exc)
        return result

    @staticmethod
    def _sensitivity(
        solution: Any,
        built: _Built,
        problem: OptimizationProblem,
        col_values: list[float],
    ) -> SensitivityResult:
        """Exact LP duals, reduced costs and binding rows, from one solve."""
        row_dual = list(solution.row_dual)
        row_activity = list(solution.row_activity)
        col_dual = list(solution.col_dual)

        constraints: list[ConstraintSensitivity] = []
        for i, constraint in enumerate(problem.constraints):
            constraints.append(
                ConstraintSensitivity(
                    name=constraint_label(constraint.name, i),
                    shadow_price=publishable_value(float(row_dual[i])),
                    # Binding is slack, not price. Measured against the bounds
                    # the row was built with, so a strict `<` is on its limit
                    # at rhs - STRICT_EPSILON.
                    is_binding=is_binding_within_bounds(
                        float(row_activity[i]),
                        built.row_lower[i],
                        built.row_upper[i],
                        math.inf,
                    ),
                    is_approximate=False,
                )
            )

        variables: list[VariableSensitivity] = []
        for var in problem.variables:
            idx = built.col_map[var.name]
            value = col_values[idx]
            lb = 0.0 if var.type == VariableType.BINARY else var.lower_bound
            ub = 1.0 if var.type == VariableType.BINARY else var.upper_bound
            at_lb = lb is not None and abs(value - lb) <= 1e-7
            at_ub = ub is not None and abs(value - ub) <= 1e-7
            variables.append(
                VariableSensitivity(
                    name=var.name,
                    reduced_cost=publishable_value(float(col_dual[idx])),
                    is_at_bound=bool(at_lb or at_ub),
                    is_approximate=False,
                )
            )

        return SensitivityResult(
            constraints=constraints,
            variables=variables,
            is_approximate=False,
        )
