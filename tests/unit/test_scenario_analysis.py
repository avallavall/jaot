"""What-if scenario analysis by real re-solves (Sensitivity L2).

The happy paths drive the REAL solver: a re-solve that does not actually solve
proves nothing about a feature whose whole point is that the delta is real. The
budget/accounting paths use a scripted solve so the batch is deterministic.
"""

import pytest

from app.domains.solver.services import get_solver_service
from app.domains.solver.services.scenario_analysis import (
    ScenarioBudget,
    compute_scenario_analysis,
)
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    ScenarioStatus,
    SolverStatus,
    Variable,
    VariableType,
)

pytestmark = pytest.mark.unit


def _real_solve():
    """Solve through the real solver service, as the Celery task does."""
    service = get_solver_service()

    def _solve(problem: OptimizationProblem, warm_start: dict[str, float] | None):
        return service.solve(problem, warm_start_solution=warm_start)

    return _solve


def _lp_problem() -> OptimizationProblem:
    """max 3x + 2y s.t. x + y <= 10, x <= 4  ->  x=4, y=6, obj=24."""
    return OptimizationProblem(
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="3*x + 2*y"),
        constraints=[
            Constraint(name="cap", expression="x + y <= 10"),
            Constraint(name="xmax", expression="x <= 4"),
        ],
    )


def test_relaxing_a_binding_row_reports_the_real_gain():
    """One more unit of `cap` is worth exactly +2 (y grows at its rate)."""
    analysis = compute_scenario_analysis(
        _lp_problem(),
        {"x": 4.0, "y": 6.0},
        solve=_real_solve(),
        objective_value=24.0,
    )

    assert analysis.computed
    assert analysis.sense == "maximize"
    relax_cap = next(
        r for r in analysis.rhs_scenarios if r.constraint == "cap" and r.direction == "relax"
    )
    assert relax_cap.status == ScenarioStatus.COMPUTED
    assert relax_cap.rhs == pytest.approx(10.0)
    assert relax_cap.rhs_new == pytest.approx(11.0)
    assert relax_cap.objective_value == pytest.approx(26.0)
    assert relax_cap.objective_delta == pytest.approx(2.0)
    assert relax_cap.objective_delta_per_unit == pytest.approx(2.0)
    assert relax_cap.improves is True

    # And the other side: one unit LESS of cap costs the same 2.
    tighten_cap = next(
        r for r in analysis.rhs_scenarios if r.constraint == "cap" and r.direction == "tighten"
    )
    assert tighten_cap.rhs_new == pytest.approx(9.0)
    assert tighten_cap.objective_delta == pytest.approx(-2.0)
    assert tighten_cap.improves is False


def test_relaxing_a_ge_row_lowers_its_rhs():
    """Relaxing means widening the feasible set — for >= that is DOWN, not up."""
    problem = OptimizationProblem(
        variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="5*x"),
        constraints=[Constraint(name="floor", expression="x >= 3")],
    )
    analysis = compute_scenario_analysis(
        problem, {"x": 3.0}, solve=_real_solve(), objective_value=15.0
    )

    relax = next(r for r in analysis.rhs_scenarios if r.direction == "relax")
    assert relax.rhs_new == pytest.approx(2.0)
    assert relax.objective_value == pytest.approx(10.0)
    assert relax.improves is True  # cheaper, and this is a minimisation


def test_regret_prices_overruling_a_binary_decision():
    """Forcing the plant the model closed costs its regret, normalised >= 0."""
    problem = OptimizationProblem(
        variables=[
            Variable(name="open_a", type=VariableType.BINARY),
            Variable(name="open_b", type=VariableType.BINARY),
        ],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="10*open_a + 25*open_b"),
        constraints=[Constraint(name="one", expression="open_a + open_b >= 1")],
    )
    analysis = compute_scenario_analysis(
        problem,
        {"open_a": 1.0, "open_b": 0.0},
        solve=_real_solve(),
        objective_value=10.0,
    )

    by_var = {d.variable: d for d in analysis.decision_scenarios}
    # Forcing the cheap plant CLOSED makes the expensive one mandatory: +15.
    assert by_var["open_a"].original_value == 1.0
    assert by_var["open_a"].forced_value == 0.0
    assert by_var["open_a"].status == ScenarioStatus.COMPUTED
    assert by_var["open_a"].objective_value == pytest.approx(25.0)
    assert by_var["open_a"].regret == pytest.approx(15.0)
    # The plant the model left CLOSED is offered too — its contribution c_j·x*
    # is zero, so ranking by contribution would have dropped the more
    # interesting half of the question.
    assert by_var["open_b"].original_value == 0.0
    assert by_var["open_b"].forced_value == 1.0
    assert by_var["open_b"].objective_value == pytest.approx(25.0)
    assert by_var["open_b"].regret == pytest.approx(15.0)


def test_regret_reports_an_impossible_overrule_as_infeasible():
    """Some overrules are not expensive but impossible — say so, don't drop them."""
    problem = OptimizationProblem(
        variables=[Variable(name="use", type=VariableType.BINARY)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="7*use"),
        constraints=[Constraint(name="must", expression="use >= 1")],
    )
    analysis = compute_scenario_analysis(
        problem, {"use": 1.0}, solve=_real_solve(), objective_value=7.0
    )

    forced = analysis.decision_scenarios[0]
    assert forced.forced_value == 0.0
    assert forced.status == ScenarioStatus.INFEASIBLE
    assert forced.regret is None


def test_equality_rows_are_labelled_as_such():
    """An equality has no slack to give; both moves are just RHS up/down."""
    problem = OptimizationProblem(
        variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="4*x"),
        constraints=[Constraint(name="demand", expression="x == 5")],
    )
    analysis = compute_scenario_analysis(
        problem, {"x": 5.0}, solve=_real_solve(), objective_value=20.0
    )

    assert [r.is_equality for r in analysis.rhs_scenarios] == [True, True]
    up = next(r for r in analysis.rhs_scenarios if r.rhs_new > 5.0)
    assert up.objective_value == pytest.approx(24.0)


def test_the_source_problem_is_never_mutated():
    problem = _lp_problem()
    before = problem.model_dump()

    compute_scenario_analysis(
        problem, {"x": 4.0, "y": 6.0}, solve=_real_solve(), objective_value=24.0
    )

    assert problem.model_dump() == before


class _ScriptedSolve:
    """Deterministic stand-in: records what it was asked, answers a fixed value."""

    def __init__(self, *, seconds_per_solve: float = 0.0, objective: float = 1.0) -> None:
        self.calls: list[OptimizationProblem] = []
        self.limits: list[float] = []
        self._seconds = seconds_per_solve
        self._objective = objective
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def __call__(
        self, problem: OptimizationProblem, warm_start: dict[str, float] | None
    ) -> OptimizationResult:
        self.calls.append(problem)
        self.limits.append(problem.options.time_limit_seconds)
        self.now += self._seconds
        return OptimizationResult(
            status=SolverStatus.OPTIMAL,
            objective_value=self._objective,
            solve_time_seconds=self._seconds,
        )


def _wide_problem(rows: int) -> OptimizationProblem:
    """`rows` binding constraints, so the batch always has more work than budget."""
    return OptimizationProblem(
        variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x"),
        constraints=[Constraint(name=f"c{i}", expression="x <= 5") for i in range(rows)],
    )


def test_the_resolve_cap_stops_the_batch_and_marks_it_partial():
    scripted = _ScriptedSolve()
    analysis = compute_scenario_analysis(
        _wide_problem(6),
        {"x": 5.0},
        solve=scripted,
        objective_value=5.0,
        budget=ScenarioBudget(max_resolves=3, top_constraints=6),
        clock=scripted.clock,
    )

    assert len(scripted.calls) == 3
    assert analysis.resolves_used == 3
    assert analysis.resolves_planned == 12  # 6 rows x 2 directions
    assert analysis.partial is True
    skipped = [r for r in analysis.rhs_scenarios if r.status == ScenarioStatus.SKIPPED_BUDGET]
    assert len(skipped) == 9
    assert all(r.objective_value is None for r in skipped)


def test_the_time_budget_stops_the_batch_mid_round():
    """Wall-clock is the second limit: 4 solves of 30s fit in a 120s budget."""
    scripted = _ScriptedSolve(seconds_per_solve=30.0)
    analysis = compute_scenario_analysis(
        _wide_problem(8),
        {"x": 5.0},
        solve=scripted,
        objective_value=5.0,
        budget=ScenarioBudget(max_resolves=20, top_constraints=8, total_seconds=120.0),
        clock=scripted.clock,
    )

    assert len(scripted.calls) == 4
    assert analysis.partial is True
    assert analysis.seconds_used == pytest.approx(120.0)


def test_relaxations_are_spent_before_tightenings():
    """A batch cut short must have spent its budget on the informative half."""
    scripted = _ScriptedSolve()
    analysis = compute_scenario_analysis(
        _wide_problem(4),
        {"x": 5.0},
        solve=scripted,
        objective_value=5.0,
        budget=ScenarioBudget(max_resolves=4, top_constraints=4),
        clock=scripted.clock,
    )

    ran = [r for r in analysis.rhs_scenarios if r.status != ScenarioStatus.SKIPPED_BUDGET]
    assert len(ran) == 4
    assert {r.direction for r in ran} == {"relax"}


def test_per_solve_limit_scales_off_the_original_solve_time():
    scripted = _ScriptedSolve()
    compute_scenario_analysis(
        _wide_problem(1),
        {"x": 5.0},
        solve=scripted,
        objective_value=5.0,
        base_solve_seconds=4.0,
        budget=ScenarioBudget(per_solve_multiplier=2.0, per_solve_cap_seconds=30.0),
        clock=scripted.clock,
    )

    assert scripted.limits[0] == pytest.approx(8.0)


def test_per_solve_limit_honours_the_cap_for_a_slow_model():
    scripted = _ScriptedSolve()
    analysis = compute_scenario_analysis(
        _wide_problem(1),
        {"x": 5.0},
        solve=scripted,
        objective_value=5.0,
        base_solve_seconds=600.0,
        budget=ScenarioBudget(per_solve_multiplier=2.0, per_solve_cap_seconds=30.0),
        clock=scripted.clock,
    )

    assert scripted.limits[0] == pytest.approx(30.0)
    assert analysis.per_solve_limit_seconds == pytest.approx(30.0)


def test_delta_is_one_unit_on_integral_data_and_relative_otherwise():
    scripted = _ScriptedSolve()
    problem = OptimizationProblem(
        variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x"),
        constraints=[
            Constraint(name="whole", expression="x <= 12"),
            Constraint(name="fractional", expression="x <= 2.5"),
            Constraint(name="big", expression="x <= 5000"),
        ],
    )
    analysis = compute_scenario_analysis(
        problem,
        {"x": 12.0},  # only `whole` is binding at x=12, so ask for all rows via top-K
        solve=scripted,
        objective_value=12.0,
        budget=ScenarioBudget(top_constraints=3),
        clock=scripted.clock,
    )
    # `whole` binds at x=12; the deltas come from the row's own RHS magnitude.
    deltas = {r.constraint: r.delta for r in analysis.rhs_scenarios}
    assert deltas["whole"] == pytest.approx(1.0)

    from app.domains.solver.services.scenario_analysis import _pick_delta

    assert _pick_delta(2.5) == pytest.approx(0.025)
    assert _pick_delta(5000.0) == pytest.approx(50.0)
    assert _pick_delta(0.0) == pytest.approx(1.0)


def test_no_base_objective_declines_instead_of_guessing():
    analysis = compute_scenario_analysis(
        _lp_problem(), {"x": 4.0, "y": 6.0}, solve=_real_solve(), objective_value=None
    )

    assert analysis.computed is False
    assert analysis.note == "no_base_objective"
    assert analysis.rhs_scenarios == []


def test_a_model_with_nothing_binding_declines():
    problem = OptimizationProblem(
        variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x"),
        constraints=[Constraint(name="loose", expression="x <= 100")],
    )
    analysis = compute_scenario_analysis(
        problem, {"x": 0.0}, solve=_real_solve(), objective_value=0.0
    )

    assert analysis.computed is False
    assert analysis.note == "no_scenarios"


def test_a_time_limited_scenario_is_reported_as_a_bound():
    """An incumbent under a time limit bounds the delta — never label it exact."""

    def _timed_out(problem: OptimizationProblem, warm_start: dict[str, float] | None):
        return OptimizationResult(
            status=SolverStatus.TIME_LIMIT, objective_value=99.0, solve_time_seconds=30.0
        )

    analysis = compute_scenario_analysis(
        _wide_problem(1), {"x": 5.0}, solve=_timed_out, objective_value=5.0
    )

    row = analysis.rhs_scenarios[0]
    assert row.status == ScenarioStatus.TIME_LIMIT
    assert row.objective_value == pytest.approx(99.0)
    assert row.objective_delta == pytest.approx(94.0)
