"""A solver's sentinel values must never be published as prices.

Production (QA 2026-08-02) served ``shadow_price: -1e+99`` — SCIP's
``SCIP_INVALID`` answered through ``getDualSolVal`` — for a model with two
constraints sharing one name, and the derivation then priced the reduced cost
at ``2e+99``. The solve itself was and is correct (both rows apply); it is the
published numbers that must be None when the solver has none to give.
"""

import math

import pytest

from app.domains.solver.adapters.scip import SCIPAdapter
from app.domains.solver.sensitivity_values import publishable_value
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverStatus,
    Variable,
    VariableType,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
        (-1e99, None),  # SCIP_INVALID, the sentinel production served as a price
        (1e99, None),
        (1e20, None),  # SCIP's infinity — the smallest sentinel magnitude
        (-0.0, -0.0),
        (0.0, 0.0),
        (3.5, 3.5),
        (-1e6, -1e6),  # large but real prices survive
    ],
)
def test_publishable_value(value, expected):
    result = publishable_value(value)
    if expected is None:
        assert result is None, f"{value!r} is a sentinel and must publish as None"
    else:
        assert result == expected and math.isfinite(result)


def _dup_name_problem(first: str, second: str) -> OptimizationProblem:
    return OptimizationProblem(
        name="dup_names",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
        constraints=[
            Constraint(name="c1", expression=first),
            Constraint(name="c1", expression=second),
        ],
    )


@pytest.mark.unit
# CONTRACT-TEST: a sensitivity number the user can read is a number they can act on.
def test_duplicate_constraint_names_publish_no_sentinel_prices():
    """The exact production reproduction: the solve applies BOTH same-name rows
    (objective 2.0, not 3.0), and the collapsed sensitivity row answers None —
    never SCIP_INVALID dressed as a price."""
    result = SCIPAdapter().solve(_dup_name_problem("x <= 3", "x <= 2"))

    assert result.status == SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(2.0)

    sens = result.sensitivity
    assert sens is not None
    for row in sens.constraints:
        assert row.shadow_price is None or abs(row.shadow_price) < 1e20, (
            f"{row.name}: {row.shadow_price!r} is a sentinel, not a price"
        )
    for var in sens.variables:
        assert var.reduced_cost is None or abs(var.reduced_cost) < 1e20, (
            f"{var.name}: {var.reduced_cost!r} is a sentinel, not a price"
        )
    # This exact shape is known to make SCIP answer SCIP_INVALID for the row:
    # the honest publication is None, not a number.
    assert sens.constraints[0].shadow_price is None


@pytest.mark.unit
def test_unique_names_still_publish_real_duals():
    """The guard must not eat real prices.

    The M-6 model, verified against production: ``max 3x+2y+z`` s.t.
    ``x+y<=4``, ``y+z<=6``, ``x`` capped by a row — duals 1, 1 and 2. (A model
    trivial enough for presolve to finish alone has no LP, hence no duals — so
    the control needs one the simplex actually solves.)
    """
    problem = OptimizationProblem(
        name="m6_lp",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="z", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="3*x + 2*y + 1*z"),
        constraints=[
            Constraint(name="c1", expression="x + y <= 4"),
            Constraint(name="c2", expression="y + z <= 6"),
            Constraint(name="cap_x", expression="x <= 3"),
        ],
    )
    result = SCIPAdapter().solve(problem)

    assert result.status == SolverStatus.OPTIMAL
    sens = result.sensitivity
    assert sens is not None
    duals = {c.name: c.shadow_price for c in sens.constraints}
    assert duals["c1"] == pytest.approx(1.0)
    assert duals["c2"] == pytest.approx(1.0)
    assert duals["cap_x"] == pytest.approx(2.0)
