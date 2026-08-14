"""HiGHS reports how much work it did, not only the answer.

Until 2026-08-14 the adapter returned no iterations, no nodes and no gap, so a
HiGHS run showed blanks wherever SCIP showed numbers. It surfaced in the solver
comparer, whose point is that seconds depend on the machine while the work count
does not — half the table was empty for one of the two solvers.
"""

from __future__ import annotations

import pytest

from app.domains.solver.adapters.highs import HiGHSAdapter
from app.schemas.optimization import (
    Constraint,
    Objective,
    OptimizationProblem,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableType,
)


def _lp() -> OptimizationProblem:
    return OptimizationProblem(
        name="counters-lp",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0),
        ],
        constraints=[
            Constraint(expression="3*x + 2*y <= 60"),
            Constraint(expression="x + 2*y <= 50"),
        ],
        objective=Objective(expression="12*x + 9*y", sense="maximize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False),
    )


def _mip() -> OptimizationProblem:
    return OptimizationProblem(
        name="counters-mip",
        variables=[
            Variable(name="a", type=VariableType.INTEGER, lower_bound=0.0, upper_bound=40.0),
            Variable(name="b", type=VariableType.INTEGER, lower_bound=0.0, upper_bound=40.0),
            Variable(name="c", type=VariableType.BINARY),
        ],
        constraints=[
            Constraint(expression="3*a + 2*b + 5*c <= 61"),
            Constraint(expression="a + 2*b + 3*c <= 47"),
            Constraint(expression="a - b <= 7"),
        ],
        objective=Objective(expression="12*a + 9*b + 4*c", sense="maximize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False),
    )


# CONTRACT-TEST: an LP solved by HiGHS reports its simplex iterations. A blank
# there is what made the comparison table half empty.
def test_an_lp_reports_its_iterations() -> None:
    result = HiGHSAdapter().solve(_lp())

    assert result.status == SolverStatus.OPTIMAL, result.error_message
    assert result.iterations is not None
    assert result.iterations > 0


# CONTRACT-TEST: an LP has no branch-and-bound tree, so its node count stays
# absent. HiGHS returns 0, and 0 would read as "explored no nodes" when the
# truth is that there was nothing to explore.
def test_an_lp_reports_no_node_count() -> None:
    result = HiGHSAdapter().solve(_lp())

    assert result.nodes is None
    assert result.gap is None


def test_a_mip_reports_nodes_and_a_finite_gap() -> None:
    result = HiGHSAdapter().solve(_mip())

    assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE), result.error_message
    assert result.nodes is not None
    assert result.nodes >= 0
    assert result.gap is not None
    assert result.gap == pytest.approx(0.0, abs=1e-3)
