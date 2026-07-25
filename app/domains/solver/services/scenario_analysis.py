"""What-if analysis by real re-solves (Sensitivity L2).

Level 1 (``exact_analysis``) reads the solution you already have: which rows are
binding, how much headroom each family keeps, what each family contributes. What
it structurally cannot answer is "what would one more unit buy me?" — in a MIP
that question has no reliable closed form. LP-relaxation shadow prices are duals
of an easier problem and go near-uniform under degeneracy, which is exactly why
the panel demotes them.

So this module answers it the only honest way: perturb the model and solve it
again. Two families of scenario:

* **RHS ranging** — move a binding constraint's right-hand side by δ and
  re-solve. The Δobjective is the real price of that unit, and the collected
  rows read as a tornado chart ("+1h on machine 3 → −420 €").
* **Decision regret** — force a binary decision to its opposite value and
  re-solve: what it costs to overrule the model (or that overruling it is
  outright infeasible).

Every re-solve is a full solve, so the work is bounded twice: a per-solve time
limit AND a total budget for the batch. When the budget runs out the remaining
scenarios come back ``SKIPPED_BUDGET`` and ``partial`` is set — a truncated
answer is reported as truncated, never padded. Runs ON DEMAND off the request
path (Celery), never on the solve path.

Solver-agnostic: it only builds ``OptimizationProblem`` values and calls back
into an injected solve function.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.domains.solver.services.exact_analysis import compute_exact_analysis
from app.domains.solver.services.expression_parser import (
    ExpressionParser,
    ParsedConstraint,
    ParseError,
    Term,
)
from app.schemas.optimization import (
    Constraint,
    DecisionScenario,
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    RhsScenario,
    ScenarioAnalysis,
    ScenarioStatus,
    SolverStatus,
    Variable,
    VariableType,
)

# A solve of one perturbed problem: (problem, warm_start) -> result.
SolveFn = Callable[[OptimizationProblem, dict[str, float] | None], OptimizationResult]

_EPS = 1e-9
# The solver schema floors a time limit at 1s; never ask for less.
_MIN_SOLVE_SECONDS = 1.0
# Below this much budget left, starting another solve only guarantees a timeout.
_MIN_USEFUL_SECONDS = 2.0


@dataclass(frozen=True)
class ScenarioBudget:
    """How much work one L2 batch may do. Defaults mirror the platform settings.

    ``per_solve_multiplier`` scales each re-solve's limit off the ORIGINAL solve
    time (a model that took 4s gets 8s per scenario), capped by
    ``per_solve_cap_seconds`` — and the whole batch by ``total_seconds``.
    """

    max_resolves: int = 20
    top_constraints: int = 8
    top_decisions: int = 4
    per_solve_multiplier: float = 2.0
    per_solve_cap_seconds: float = 30.0
    total_seconds: float = 300.0


def _fmt(value: float) -> str:
    """Round-trippable number for a rebuilt expression."""
    return repr(float(value))


def _render_term(term: Term) -> str:
    """One term as ``coef*x`` / ``coef*x*y`` (coefficient sign handled by caller)."""
    magnitude = _fmt(abs(term.coefficient))
    return "*".join([magnitude, *term.variables])


def _render_constraint(parsed: ParsedConstraint, rhs: float) -> str | None:
    """Rebuild a constraint from its parsed LHS with a new RHS.

    Rebuilt from the parsed terms rather than by editing the original text: the
    parser has already moved variables left and constants right, so the canonical
    form is unambiguous no matter how the source was written. Returns None when
    the row carries no variables (nothing to re-solve).
    """
    terms = [t for t in parsed.lhs.terms if t.variables]
    if not terms:
        return None
    pieces: list[str] = []
    for i, term in enumerate(terms):
        sign = "-" if term.coefficient < 0 else "+"
        if i == 0:
            pieces.append(f"-{_render_term(term)}" if sign == "-" else _render_term(term))
        else:
            pieces.append(f" {sign} {_render_term(term)}")
    return f"{''.join(pieces)} {parsed.operator} {_fmt(rhs)}"


def _pick_delta(rhs: float) -> float:
    """The δ to move a RHS by: one whole unit on integral data, 1% otherwise.

    On integral data (capacities, headcount, trucks) the smallest change a user
    can actually make is one unit, and "+1 truck → −80 €" is the readable
    answer. On fractional data 1% keeps the perturbation proportional. Rows
    normalise by δ anyway (``objective_delta_per_unit``), so mixed δ still
    compare in one chart.
    """
    magnitude = abs(rhs)
    if magnitude < _EPS:
        return 1.0
    if abs(rhs - round(rhs)) < _EPS:
        return max(1.0, round(magnitude * 0.01))
    return magnitude * 0.01


def _is_binary(variable: Variable) -> bool:
    """Binary, or an integer variable pinned to {0, 1} — same decision either way."""
    if variable.type == VariableType.BINARY:
        return True
    return (
        variable.type == VariableType.INTEGER
        and variable.lower_bound is not None
        and variable.upper_bound is not None
        and abs(variable.lower_bound) < _EPS
        and abs(variable.upper_bound - 1.0) < _EPS
    )


def _status_of(result: OptimizationResult) -> ScenarioStatus:
    """Map a solver outcome onto the scenario contract (bounds stay labelled)."""
    if result.status == SolverStatus.OPTIMAL:
        return ScenarioStatus.COMPUTED
    if result.status in (SolverStatus.FEASIBLE, SolverStatus.TIME_LIMIT):
        # An incumbent under a time limit bounds the true delta — it is not it.
        return ScenarioStatus.TIME_LIMIT
    if result.status == SolverStatus.INFEASIBLE:
        return ScenarioStatus.INFEASIBLE
    return ScenarioStatus.ERROR


@dataclass
class _RhsPlan:
    """One planned RHS scenario, before it is (maybe) solved."""

    constraint: Constraint
    parsed: ParsedConstraint
    family: str | None
    direction: str
    delta: float
    rhs_new: float
    is_equality: bool


@dataclass
class _DecisionPlan:
    """One planned regret scenario, before it is (maybe) solved."""

    variable: Variable
    original_value: float
    forced_value: float


def _plan_rhs_scenarios(
    problem: OptimizationProblem,
    parser: ExpressionParser,
    known: set[str],
    binding_names: list[str],
    families: dict[str, str | None],
) -> list[list[_RhsPlan]]:
    """Plan relax/tighten moves for the binding rows, grouped by round.

    Returns ``[relax_round, tighten_round]``: relaxing every candidate is more
    informative than doing both directions of half of them, so when the budget
    runs short the first round is the one that survives.
    """
    by_name: dict[str, Constraint] = {}
    for i, constraint in enumerate(problem.constraints):
        by_name.setdefault(constraint.name or f"c{i + 1}", constraint)

    relax: list[_RhsPlan] = []
    tighten: list[_RhsPlan] = []
    for name in binding_names:
        constraint = by_name.get(name)
        if constraint is None:
            continue
        try:
            parsed = parser.parse_constraint(constraint.expression, known)
        except (ParseError, ValueError, ZeroDivisionError):
            continue  # unparseable rows are simply not offered as scenarios
        if not any(t.variables for t in parsed.lhs.terms):
            continue
        delta = _pick_delta(parsed.rhs)
        is_equality = parsed.operator == "=="
        # Relaxing widens the feasible set: ≤ gains room going up, ≥ going down.
        # An equality has no slack to give — the pair is then just ↑/↓ RHS, and
        # ``is_equality`` tells the UI to say so instead of "relax/tighten".
        up_relaxes = parsed.operator in ("<=", "<") or is_equality
        for direction in ("relax", "tighten"):
            relaxing = direction == "relax"
            goes_up = up_relaxes if relaxing else not up_relaxes
            plan = _RhsPlan(
                constraint=constraint,
                parsed=parsed,
                family=families.get(name),
                direction=direction,
                delta=delta,
                rhs_new=parsed.rhs + (delta if goes_up else -delta),
                is_equality=is_equality,
            )
            (relax if relaxing else tighten).append(plan)
    return [relax, tighten]


def _objective_weights(
    problem: OptimizationProblem,
    parser: ExpressionParser,
    known: set[str],
) -> dict[str, float]:
    """Objective coefficient c_j per variable (linear terms only)."""
    try:
        parsed = parser.parse_expression(problem.objective.expression, known)
    except (ParseError, ValueError, ZeroDivisionError):
        return {}
    weights: dict[str, float] = {}
    for term in parsed.terms:
        if len(term.variables) == 1:
            name = term.variables[0]
            weights[name] = weights.get(name, 0.0) + term.coefficient
    return weights


def _plan_decision_scenarios(
    problem: OptimizationProblem,
    solution: dict[str, float],
    weights: dict[str, float],
    limit: int,
) -> list[_DecisionPlan]:
    """Pick the binary decisions worth overruling: heaviest objective weight first.

    Ranked by the objective COEFFICIENT, not by the term's contribution c_j·x*:
    every decision the model left switched off contributes exactly zero, and
    those are precisely the interesting ones ("what if I open the plant you
    closed?"). Picks alternate between switched-on and switched-off decisions so
    the panel answers both questions instead of whichever the solution favoured.
    Only variables the objective actually mentions are offered — a binary with
    no objective weight has no cost of overruling to report here.
    """
    by_name = {v.name: v for v in problem.variables}
    ranked = sorted(
        (
            name
            for name, weight in weights.items()
            if abs(weight) > _EPS
            and (variable := by_name.get(name)) is not None
            and _is_binary(variable)
            and round(solution.get(name, 0.0)) in (0, 1)
        ),
        key=lambda name: -abs(weights[name]),
    )
    switched_on = [n for n in ranked if round(solution.get(n, 0.0)) == 1]
    switched_off = [n for n in ranked if round(solution.get(n, 0.0)) == 0]

    picked: list[str] = []
    while len(picked) < limit and (switched_on or switched_off):
        for queue in (switched_on, switched_off):
            if queue and len(picked) < limit:
                picked.append(queue.pop(0))
    return [
        _DecisionPlan(
            variable=by_name[name],
            original_value=float(round(solution.get(name, 0.0))),
            forced_value=float(1 - round(solution.get(name, 0.0))),
        )
        for name in picked
    ]


def _problem_with_constraint(
    problem: OptimizationProblem,
    plan: _RhsPlan,
    expression: str,
    time_limit: float,
) -> OptimizationProblem:
    """Copy of the problem with one constraint's RHS moved."""
    scenario = problem.model_copy(deep=True)
    target = plan.constraint.name
    for i, constraint in enumerate(scenario.constraints):
        same_row = (
            constraint.name == target
            if target is not None
            else constraint.expression == plan.constraint.expression
        )
        if same_row:
            scenario.constraints[i] = constraint.model_copy(update={"expression": expression})
            break
    scenario.options = scenario.options.model_copy(update={"time_limit_seconds": time_limit})
    # The warm_start CONFIG points at another execution; the batch passes its own
    # start solution directly, so drop it rather than re-loading a stale one.
    scenario.warm_start = None
    return scenario


def _problem_with_forced_variable(
    problem: OptimizationProblem,
    plan: _DecisionPlan,
    time_limit: float,
) -> OptimizationProblem:
    """Copy of the problem with one binary pinned to its opposite value.

    Pinned by an explicit equality ROW, not by bounds: a binary is declared to
    the solver as a {0,1} type and adapters legitimately ignore its bounds (the
    SCIP one calls ``addVar(vtype="B")`` with none), so a bounds-only pin would
    silently solve the UNCHANGED model and report zero regret for everything.
    The bounds are narrowed too — free for integer-typed decisions, harmless
    where the type already says {0,1}.
    """
    scenario = problem.model_copy(deep=True)
    for i, variable in enumerate(scenario.variables):
        if variable.name == plan.variable.name:
            scenario.variables[i] = variable.model_copy(
                update={"lower_bound": plan.forced_value, "upper_bound": plan.forced_value}
            )
            break
    scenario.constraints = [
        *scenario.constraints,
        Constraint(
            name=f"__force_{plan.variable.name}"[:256],
            expression=f"{plan.variable.name} == {_fmt(plan.forced_value)}",
        ),
    ]
    scenario.options = scenario.options.model_copy(update={"time_limit_seconds": time_limit})
    scenario.warm_start = None
    return scenario


class _Budget:
    """Tracks the batch's two limits: number of re-solves and wall-clock."""

    def __init__(
        self,
        budget: ScenarioBudget,
        base_solve_seconds: float | None,
        clock: Callable[[], float],
    ) -> None:
        self._budget = budget
        self._clock = clock
        self._start = clock()
        self._used = 0
        base = base_solve_seconds if base_solve_seconds and base_solve_seconds > 0 else None
        scaled = base * budget.per_solve_multiplier if base else budget.per_solve_cap_seconds
        self.per_solve_limit = max(
            _MIN_SOLVE_SECONDS, min(scaled, budget.per_solve_cap_seconds, budget.total_seconds)
        )

    @property
    def used(self) -> int:
        return self._used

    def elapsed(self) -> float:
        return self._clock() - self._start

    def next_limit(self) -> float | None:
        """Seconds to give the next solve, or None when the batch must stop."""
        if self._used >= self._budget.max_resolves:
            return None
        remaining = self._budget.total_seconds - self.elapsed()
        if remaining < _MIN_USEFUL_SECONDS:
            return None
        return max(_MIN_SOLVE_SECONDS, min(self.per_solve_limit, remaining))

    def spend(self) -> None:
        self._used += 1


def compute_scenario_analysis(
    problem: OptimizationProblem,
    solution: dict[str, float],
    *,
    solve: SolveFn,
    objective_value: float | None = None,
    base_solve_seconds: float | None = None,
    budget: ScenarioBudget | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ScenarioAnalysis:
    """Run the bounded what-if batch for one solved execution."""
    budget = budget or ScenarioBudget()
    if objective_value is None:
        # Every row is a delta against the base objective; without it there is
        # nothing honest to report.
        return ScenarioAnalysis(computed=False, note="no_base_objective")

    parser = ExpressionParser()
    known = set(solution)
    exact = compute_exact_analysis(problem, solution, objective_value=objective_value)
    binding = [row for row in exact.constraints if row.is_binding][: budget.top_constraints]
    families = {row.name: row.family for row in exact.constraints}

    rounds = _plan_rhs_scenarios(problem, parser, known, [row.name for row in binding], families)
    decisions = _plan_decision_scenarios(
        problem,
        solution,
        _objective_weights(problem, parser, known),
        budget.top_decisions,
    )
    if not rounds[0] and not decisions:
        return ScenarioAnalysis(
            computed=False,
            note="no_scenarios",
            sense=problem.objective.sense.value,
            base_objective=objective_value,
        )

    tracker = _Budget(budget, base_solve_seconds, clock)
    rhs_rows: list[RhsScenario] = []
    decision_rows: list[DecisionScenario] = []

    # Order: relax every candidate, then the regret questions, then tighten.
    # Each step is strictly less informative than the one before it, so a batch
    # cut short by the budget still spent it on the most useful scenarios.
    for plan in rounds[0]:
        rhs_rows.append(_run_rhs(problem, plan, solve, tracker, objective_value, solution))
    for plan in decisions:
        decision_rows.append(_run_decision(problem, plan, solve, tracker, objective_value))
    for plan in rounds[1]:
        rhs_rows.append(_run_rhs(problem, plan, solve, tracker, objective_value, solution))

    planned = len(rounds[0]) + len(rounds[1]) + len(decisions)
    partial = any(r.status == ScenarioStatus.SKIPPED_BUDGET for r in rhs_rows) or any(
        d.status == ScenarioStatus.SKIPPED_BUDGET for d in decision_rows
    )
    return ScenarioAnalysis(
        computed=True,
        sense=problem.objective.sense.value,
        base_objective=objective_value,
        rhs_scenarios=rhs_rows,
        decision_scenarios=decision_rows,
        resolves_used=tracker.used,
        resolves_planned=planned,
        seconds_used=tracker.elapsed(),
        budget_seconds=budget.total_seconds,
        per_solve_limit_seconds=tracker.per_solve_limit,
        partial=partial,
    )


def _run_rhs(
    problem: OptimizationProblem,
    plan: _RhsPlan,
    solve: SolveFn,
    tracker: _Budget,
    base_objective: float,
    base_solution: dict[str, float],
) -> RhsScenario:
    """Solve one RHS move (or report why it was not solved)."""
    row = RhsScenario(
        constraint=plan.constraint.name or plan.constraint.expression[:64],
        family=plan.family,
        operator=plan.parsed.operator,
        direction=plan.direction,
        is_equality=plan.is_equality,
        rhs=plan.parsed.rhs,
        rhs_new=plan.rhs_new,
        delta=plan.delta,
        status=ScenarioStatus.SKIPPED_BUDGET,
    )
    limit = tracker.next_limit()
    if limit is None:
        return row

    expression = _render_constraint(plan.parsed, plan.rhs_new)
    if expression is None:
        row.status = ScenarioStatus.ERROR
        return row

    scenario = _problem_with_constraint(problem, plan, expression, limit)
    # Only a relaxation keeps the base solution feasible, so only a relaxation
    # may warm-start from it; feeding an infeasible start to a tightened model
    # buys nothing and risks confusing the adapter.
    warm_start = dict(base_solution) if plan.direction == "relax" and base_solution else None

    tracker.spend()
    result = solve(scenario, warm_start)
    row.status = _status_of(result)
    row.solve_time_seconds = result.solve_time_seconds
    if row.status in (ScenarioStatus.COMPUTED, ScenarioStatus.TIME_LIMIT):
        if result.objective_value is None:
            row.status = ScenarioStatus.ERROR
            return row
        row.objective_value = result.objective_value
        row.objective_delta = result.objective_value - base_objective
        row.objective_delta_per_unit = row.objective_delta / plan.delta if plan.delta else None
        sense = problem.objective.sense
        row.improves = (
            row.objective_delta < -_EPS
            if sense == ObjectiveSense.MINIMIZE
            else row.objective_delta > _EPS
        )
    return row


def _run_decision(
    problem: OptimizationProblem,
    plan: _DecisionPlan,
    solve: SolveFn,
    tracker: _Budget,
    base_objective: float,
) -> DecisionScenario:
    """Solve one forced-decision scenario (or report why it was not solved)."""
    row = DecisionScenario(
        variable=plan.variable.name,
        family=plan.variable.family,
        original_value=plan.original_value,
        forced_value=plan.forced_value,
        status=ScenarioStatus.SKIPPED_BUDGET,
    )
    limit = tracker.next_limit()
    if limit is None:
        return row

    scenario = _problem_with_forced_variable(problem, plan, limit)
    tracker.spend()
    result = solve(scenario, None)
    row.status = _status_of(result)
    row.solve_time_seconds = result.solve_time_seconds
    if row.status in (ScenarioStatus.COMPUTED, ScenarioStatus.TIME_LIMIT):
        if result.objective_value is None:
            row.status = ScenarioStatus.ERROR
            return row
        row.objective_value = result.objective_value
        # Normalised to the problem's sense: regret is always "how much worse".
        row.regret = (
            result.objective_value - base_objective
            if problem.objective.sense == ObjectiveSense.MINIMIZE
            else base_objective - result.objective_value
        )
    return row
