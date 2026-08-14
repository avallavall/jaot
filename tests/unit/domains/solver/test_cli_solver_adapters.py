"""Contract tests for CBC and GLPK, run against the real binaries.

Both adapters drive a command-line program, so there is nothing to mock that
would prove anything: the whole risk lives in what the program prints. These
tests therefore run ``cbc`` and ``glpsol`` for real and are parametrized over
both, because the contract they have to meet is the same one.

The binaries come from the Debian packages ``coinor-cbc`` and ``glpk-utils``.
They are installed in the API and worker images and by the CI test job. Without
them these tests skip, which is why the CI workflow installs them explicitly —
a skipped solver test proves nothing.
"""

from __future__ import annotations

import random

import pytest

from app.domains.solver.adapters.cbc import CBCAdapter
from app.domains.solver.adapters.glpk import GLPKAdapter
from app.domains.solver.adapters.scip import SCIPAdapter
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

ADAPTER_CLASSES = {"cbc": CBCAdapter, "glpk": GLPKAdapter}


@pytest.fixture(params=sorted(ADAPTER_CLASSES))
def adapter(request: pytest.FixtureRequest):
    """One adapter per solver, skipped when its binary is not installed."""
    instance = ADAPTER_CLASSES[request.param]()
    if not instance.is_available():
        pytest.skip(f"{request.param} binary not installed — apt-get install coinor-cbc glpk-utils")
    return instance


def _milp() -> OptimizationProblem:
    """A model whose only optimum is 29.5, with the names that broke things before.

    ``e12`` looks like a number in exponent notation, the long name is the shape
    the JModel compiler produces, and ``never_used_anywhere`` appears in no
    constraint and no objective term — a variable a writer could quietly drop.
    """
    return OptimizationProblem(
        name="milp",
        variables=[
            Variable(name="x_cont", lower_bound=0, upper_bound=10),
            Variable(name="y_int", type=VariableType.INTEGER, lower_bound=0, upper_bound=5),
            Variable(name="z_bin", type=VariableType.BINARY),
            Variable(name="e12", lower_bound=-3, upper_bound=3),
            Variable(name="assign_veryveryverylongname_o107_d42_k9", lower_bound=0),
            Variable(name="never_used_anywhere", lower_bound=0, upper_bound=2),
        ],
        objective=Objective(
            sense=ObjectiveSense.MAXIMIZE,
            expression=(
                "3*x_cont + 2*y_int + 5*z_bin + e12 + 0.5*assign_veryveryverylongname_o107_d42_k9"
            ),
        ),
        constraints=[
            Constraint(name="cap", expression="x_cont + y_int + z_bin <= 8"),
            Constraint(
                name="eq_row",
                expression="e12 + assign_veryveryverylongname_o107_d42_k9 == 4",
            ),
            Constraint(name="lower_row", expression="x_cont - 2*y_int >= -3"),
        ],
    )


def _lp() -> OptimizationProblem:
    return OptimizationProblem(
        name="lp",
        variables=[Variable(name=n, lower_bound=0, upper_bound=10) for n in ("a", "b", "c")],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="3*a + 2*b + c"),
        constraints=[
            Constraint(name="r1", expression="a + b <= 4"),
            Constraint(name="r2", expression="b + c <= 6"),
        ],
    )


def _market_split(time_limit: float) -> OptimizationProblem:
    """Six equality rows over fifty binaries: neither solver finishes this.

    Market split is the standard small model that is hard on purpose. The
    coefficients come from a seeded generator so every machine gets the same
    model; an arithmetic pattern was tried first and both solvers proved it
    infeasible in milliseconds, which tests nothing.

    Measured with a five-second limit: CBC explores about 33,000 nodes and GLPK
    about 17,000, and neither finds a feasible point. If a future solver version
    ever cracks this in five seconds, make the model harder — do not soften the
    assertions, or the time-limit path stops being tested at all.
    """
    generator = random.Random(7)
    coefficients = [[generator.randint(0, 99) for _ in range(50)] for _ in range(6)]
    return OptimizationProblem(
        name="market_split",
        variables=[Variable(name=f"b{j}", type=VariableType.BINARY) for j in range(50)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="b0"),
        constraints=[
            Constraint(
                name=f"ms{i}",
                expression=" + ".join(f"{row[j]}*b{j}" for j in range(50)) + f" == {sum(row) // 2}",
            )
            for i, row in enumerate(coefficients)
        ],
        options=SolverOptions(time_limit_seconds=time_limit, gap_tolerance=0.0, threads=1),
    )


def test_both_adapters_declare_what_they_are(adapter) -> None:
    caps = adapter.capabilities

    assert caps.name in ADAPTER_CLASSES
    assert caps.supports_continuous is True
    assert caps.supports_integer is True
    assert caps.supports_binary is True
    # Neither solver reads a quadratic LP file, and neither claims to.
    assert caps.supports_quadratic is False
    assert caps.supports_multi_objective is False
    assert caps.supports_progress is False


def test_solves_a_milp_to_the_known_optimum(adapter) -> None:
    result = adapter.solve(_milp())

    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(29.5)
    assert result.dual_bound == pytest.approx(29.5)
    assert result.gap == pytest.approx(0.0, abs=1e-9)


def test_every_declared_variable_comes_back_with_a_value(adapter) -> None:
    """Including one that appears in no constraint and in no objective term."""
    problem = _milp()

    result = adapter.solve(problem)

    assert result.solution is not None
    assert set(result.solution) == {v.name for v in problem.variables}
    assert result.variables is not None
    assert len(result.variables) == len(problem.variables)


def test_agrees_with_scip_on_the_same_model(adapter) -> None:
    """# CONTRACT-TEST: a new solver that disagrees with SCIP is wrong, not new.

    The comparison page exists to put these numbers side by side. If two
    solvers report different optima for one model, at least one of them is
    being read incorrectly.
    """
    problem = _milp()

    reference = SCIPAdapter().solve(problem)
    result = adapter.solve(problem)

    assert reference.status is SolverStatus.OPTIMAL
    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(reference.objective_value)


def test_solves_a_pure_lp_and_counts_no_branch_and_bound_nodes(adapter) -> None:
    """An LP has no tree, so reporting "0 nodes" would claim work that never existed."""
    result = adapter.solve(_lp())

    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(18.0)
    assert result.nodes is None


def test_reports_infeasible_without_inventing_an_objective(adapter) -> None:
    problem = OptimizationProblem(
        name="infeasible",
        variables=[Variable(name="a", type=VariableType.INTEGER, lower_bound=0, upper_bound=5)],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="a"),
        constraints=[
            Constraint(name="lo", expression="a >= 4"),
            Constraint(name="hi", expression="a <= 2"),
        ],
    )

    result = adapter.solve(problem)

    assert result.status is SolverStatus.INFEASIBLE
    assert result.objective_value is None
    assert result.solution is None
    assert result.dual_bound is None


def test_reports_unbounded(adapter) -> None:
    problem = OptimizationProblem(
        name="unbounded",
        variables=[Variable(name="a", lower_bound=0)],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="a"),
        constraints=[Constraint(name="r", expression="a >= 1")],
    )

    result = adapter.solve(problem)

    assert result.status is SolverStatus.UNBOUNDED
    assert result.objective_value is None


def test_refuses_a_quadratic_model_instead_of_answering_it(adapter) -> None:
    """# CONTRACT-TEST: a model the solver cannot read must never come back solved.

    CBC reads an LP file whose only row is quadratic, drops what it does not
    understand and reports "Optimal" on the remains — a wrong answer with no
    error attached. Both adapters refuse the model before it reaches the binary.
    """
    problem = OptimizationProblem(
        name="quadratic",
        variables=[
            Variable(name="x", lower_bound=0, upper_bound=5),
            Variable(name="y", lower_bound=0, upper_bound=5),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y"),
        constraints=[Constraint(name="c1", expression="x*y <= 6")],
    )

    result = adapter.solve(problem)

    assert result.status is SolverStatus.ERROR
    assert result.objective_value is None
    assert "quadratic" in (result.error_message or "").lower()


def test_stops_at_the_time_limit_and_reports_the_bound_it_proved(adapter) -> None:
    result = adapter.solve(_market_split(time_limit=5))

    assert result.status is SolverStatus.TIME_LIMIT
    # Nothing was found, so there is no objective — but the search did prove a
    # bound, and that bound is the whole content of a run stopped by its limit.
    assert result.objective_value is None
    assert result.dual_bound is not None
    assert result.iterations is not None and result.iterations > 0
    assert result.nodes is not None and result.nodes > 0


def test_two_solves_in_one_process_give_the_same_answer(adapter) -> None:
    """# CONTRACT-TEST: the second solve in a process must equal the first.

    HiGHS pins its thread count on the first solve of a process, and every
    later solve asking for a different count failed in silence. A worker solves
    over and over without restarting, so this is checked on every adapter now.
    """
    problem = _milp()

    first = adapter.solve(problem)
    second = adapter.solve(problem)

    assert first.status is second.status is SolverStatus.OPTIMAL
    assert first.objective_value == pytest.approx(second.objective_value)
    assert first.solution == second.solution


def test_reports_missing_binary_instead_of_pretending_to_solve(monkeypatch) -> None:
    """An image built without the packages must fail with a sentence, not a stack."""
    instance = CBCAdapter()
    monkeypatch.setattr(instance, "_binary", None)
    monkeypatch.setattr(instance, "_looked_up", True)

    assert instance.is_available() is False

    result = instance.solve(_lp())
    assert result.status is SolverStatus.ERROR
    assert "not installed" in (result.error_message or "")
