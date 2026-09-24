"""Every adapter must solve the model it was given, and report what happened.

# CONTRACT-TEST: SCIP, HiGHS, CBC, GLPK and JAOS return the same answer for the same model.

Each case here was a real divergence, found by running the four solvers on the
same small model (2026-09-24):

- HiGHS dropped the constant of the objective: 2 where the others said 102.
- A constraint naming a variable on both sides (``xa >= 0.3*xa + 0.3*xb``) was
  refused by HiGHS, skipped without a word, and the model without it was solved
  and called optimal: 10 where the others said 7.
- Bounds on a binary were dropped by all four, so a plant closed with
  ``upper_bound: 0`` came back open.
- SCIP called a hard model "infeasible" when it had only run out of time.
- HiGHS threw away the answer it held when the time limit hit.
- HiGHS called an unbounded model "infeasible".
- SCIP reported a gap of 1e20 where the others reported 1.0.
- GLPK called an unbounded integer model an error.
"""

from __future__ import annotations

import random

import pytest

from app.domains.solver.adapters._cli_solver import relative_gap
from app.domains.solver.adapters.cbc import CBCAdapter
from app.domains.solver.adapters.glpk import GLPKAdapter
from app.domains.solver.adapters.highs import HiGHSAdapter
from app.domains.solver.adapters.jaos import JAOSAdapter
from app.domains.solver.adapters.scip import SCIPAdapter
from app.domains.solver.services.expression_parser import ExpressionParser
from app.domains.solver.services.problem_validation import iter_problem_errors
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableType,
)

pytestmark = pytest.mark.unit

ADAPTERS = {
    "scip": SCIPAdapter,
    "highs": HiGHSAdapter,
    "cbc": CBCAdapter,
    "glpk": GLPKAdapter,
    "jaos": JAOSAdapter,
}


@pytest.fixture(params=sorted(ADAPTERS))
def adapter(request: pytest.FixtureRequest):
    instance = ADAPTERS[request.param]()
    if not instance.is_available():
        pytest.skip(f"{request.param} is not installed here")
    return instance


def _problem(variables, sense, objective, constraints, **options) -> OptimizationProblem:
    return OptimizationProblem(
        variables=variables,
        objective=Objective(sense=sense, expression=objective),
        constraints=[Constraint(name=f"r{i}", expression=c) for i, c in enumerate(constraints)],
        options=SolverOptions(**options),
    )


def _continuous(name: str, upper: float | None = None) -> Variable:
    return Variable(name=name, lower_bound=0, upper_bound=upper)


def test_the_objective_constant_is_part_of_the_answer(adapter) -> None:
    result = adapter.solve(
        _problem(
            [_continuous("x", 10), _continuous("y", 10)],
            ObjectiveSense.MINIMIZE,
            "3*x + 2*y + 100",
            ["x + y >= 1"],
        )
    )
    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(102.0)


def test_a_variable_on_both_sides_of_a_constraint_is_one_coefficient(adapter) -> None:
    result = adapter.solve(
        _problem(
            [_continuous("xa"), _continuous("xb")],
            ObjectiveSense.MAXIMIZE,
            "xb",
            ["xa + xb <= 10", "xa >= 0.3*xa + 0.3*xb"],
        )
    )
    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(7.0)
    assert result.solution["xa"] == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("bounds", "expected_a", "expected_objective"),
    [
        ({"upper_bound": 0}, 0, 5.0),  # closed: the cheaper plant is forbidden
        ({"lower_bound": 1}, 1, -15.0),  # forced open
        ({}, 1, -15.0),  # free: the solver picks it
    ],
)
def test_the_bounds_of_a_binary_are_kept(adapter, bounds, expected_a, expected_objective) -> None:
    problem = OptimizationProblem(
        variables=[
            Variable(name="open_a", type=VariableType.BINARY, **bounds),
            Variable(name="open_b", type=VariableType.BINARY),
        ],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="5*open_b - 15*open_a"),
        constraints=[Constraint(name="one", expression="open_a + open_b >= 1")],
    )
    assert iter_problem_errors(problem) == []
    result = adapter.solve(problem)
    assert result.status is SolverStatus.OPTIMAL
    assert round(result.solution["open_a"]) == expected_a
    assert result.objective_value == pytest.approx(expected_objective)


def _market_split(with_slack: bool) -> OptimizationProblem:
    """Equality rows over binaries: no solver closes this in two seconds.

    Without slack no solver finds any feasible point. With slack every solver
    finds one at once and cannot prove it optimal, so the run ends on its time
    limit holding an answer.
    """
    generator = random.Random(7)
    rows, width = 5, 40
    coefficients = [[generator.randint(0, 99) for _ in range(width)] for _ in range(rows)]
    variables = [Variable(name=f"b{j}", type=VariableType.BINARY) for j in range(width)]
    objective = "b0"
    constraints = []
    for i, row in enumerate(coefficients):
        lhs = " + ".join(f"{row[j]}*b{j}" for j in range(width))
        if with_slack:
            lhs += f" + sp{i} - sm{i}"
        constraints.append(f"{lhs} == {sum(row) // 2}")
    if with_slack:
        variables += [_continuous(f"sp{i}") for i in range(rows)]
        variables += [_continuous(f"sm{i}") for i in range(rows)]
        objective = " + ".join(f"sp{i} + sm{i}" for i in range(rows))
    return _problem(
        variables,
        ObjectiveSense.MINIMIZE,
        objective,
        constraints,
        time_limit_seconds=2,
        gap_tolerance=0.0,
        threads=1,
    )


def test_running_out_of_time_is_not_infeasibility(adapter) -> None:
    result = adapter.solve(_market_split(with_slack=False))
    assert result.status is SolverStatus.TIME_LIMIT
    assert result.objective_value is None


def test_a_time_limited_run_returns_the_answer_it_holds(adapter) -> None:
    result = adapter.solve(_market_split(with_slack=True))
    assert result.status is SolverStatus.TIME_LIMIT
    assert result.objective_value is not None
    assert len(result.solution) == 50
    assert result.dual_bound is not None
    # One formula for every solver: SCIP's own gap said 1e20 here.
    assert result.gap == pytest.approx(relative_gap(result.objective_value, result.dual_bound))
    assert result.gap <= 1.0


def test_an_unbounded_model_is_called_unbounded(adapter) -> None:
    # GLPK said "error" here: glpsol prints "LP HAS UNBOUNDED PRIMAL SOLUTION"
    # for an integer model, and the adapter did not know that line.
    result = adapter.solve(
        _problem(
            [Variable(name="x", type=VariableType.INTEGER, lower_bound=0), _continuous("y")],
            ObjectiveSense.MAXIMIZE,
            "x + y",
            ["x - y <= 3"],
        )
    )
    assert result.status is SolverStatus.UNBOUNDED


def test_highs_refuses_an_input_it_rejected_instead_of_skipping_it() -> None:
    import highspy

    from app.domains.solver.adapters.highs import _checked

    _checked(highspy.HighsStatus.kOk, "row")
    _checked(highspy.HighsStatus.kWarning, "row")
    with pytest.raises(ValueError, match="rejected the row"):
        _checked(highspy.HighsStatus.kError, "row")


def test_a_parsed_constraint_names_each_variable_once() -> None:
    parsed = ExpressionParser().parse_constraint("xa >= 0.3*(xa + xb)")
    names = [term.variables[0] for term in parsed.lhs.terms]
    assert sorted(names) == ["xa", "xb"]
    coefficients = {term.variables[0]: term.coefficient for term in parsed.lhs.terms}
    assert coefficients["xa"] == pytest.approx(0.7)
    assert coefficients["xb"] == pytest.approx(-0.3)


def test_scientific_notation_is_a_number_not_a_variable() -> None:
    problem = _problem(
        [_continuous("x", 10), _continuous("y", 10)],
        ObjectiveSense.MINIMIZE,
        "5e-05*x + 1.5E3*y + 1e+2",
        ["2.5e-3*x + y >= 1e-1"],
    )
    assert iter_problem_errors(problem) == []

    broken = _problem(
        [_continuous("x", 10)], ObjectiveSense.MINIMIZE, "5e-05*x + 2e-3*ghost", ["x >= 0"]
    )
    errors = iter_problem_errors(broken)
    assert len(errors) == 1
    assert "ghost" in errors[0]
    assert "'e'" not in errors[0]


def _rows(named: bool) -> list[Constraint]:
    expressions = ["x + y <= 4", "x <= 100", "y <= 50"]
    return [
        Constraint(name=f"row{i}" if named else None, expression=expression)
        for i, expression in enumerate(expressions)
    ]


@pytest.mark.parametrize("integer", [False, True])
def test_an_unnamed_row_gets_its_own_binding_flag_and_price(integer) -> None:
    """Unnamed rows were read one position off: c0 in one place, c1 in another.

    SCIP's MIP binding flags then described the row before, and the reduced
    costs found no price for any unnamed row.
    """
    kind = VariableType.INTEGER if integer else VariableType.CONTINUOUS

    def solve(named: bool):
        problem = OptimizationProblem(
            variables=[
                Variable(name="x", type=kind, lower_bound=0),
                Variable(name="y", type=kind, lower_bound=0),
            ],
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="y - x"),
            constraints=_rows(named),
        )
        return SCIPAdapter().solve(problem).sensitivity

    named, unnamed = solve(True), solve(False)
    assert [c.name for c in unnamed.constraints] == ["c1", "c2", "c3"]
    assert [c.is_binding for c in unnamed.constraints] == [True, False, False]
    assert [c.is_binding for c in unnamed.constraints] == [c.is_binding for c in named.constraints]
    assert [c.shadow_price for c in unnamed.constraints] == [
        c.shadow_price for c in named.constraints
    ]
    assert {v.name: v.reduced_cost for v in unnamed.variables} == {
        v.name: v.reduced_cost for v in named.variables
    }
