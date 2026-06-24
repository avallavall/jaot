"""Regression test for STYLE-01: Pydantic immutability in plan-limit clamp.

Pre-fix: app/api/v2/solve.py lines 80-82 mutated
`problem.options.time_limit_seconds` in place. Per the project coding style,
all state updates MUST be immutable.

This test imports the helper that now returns a NEW problem instance when
a clamp is applied, and asserts the original input is untouched.
"""

from __future__ import annotations

import pytest

from app.api.v2.solve import _clamp_time_limit_to_plan
from app.schemas.optimization import OptimizationProblem, SolverOptions


def _make_problem(time_limit: float) -> OptimizationProblem:
    """Construct a minimal valid OptimizationProblem for the clamp test."""
    from app.schemas.optimization import (
        Objective,
        ObjectiveSense,
        Variable,
        VariableType,
    )

    return OptimizationProblem(
        name="clamp_test",
        variables=[
            Variable(
                name="x",
                type=VariableType.CONTINUOUS,
                lower_bound=0.0,
                upper_bound=10.0,
            )
        ],
        objective=Objective(expression="x", sense=ObjectiveSense.MINIMIZE),
        constraints=[],
        options=SolverOptions(time_limit_seconds=time_limit),
    )


@pytest.mark.unit
def test_clamp_does_not_mutate_original_problem():
    original = _make_problem(999.0)
    plan_max = 300.0

    clamped = _clamp_time_limit_to_plan(original, plan_max)

    # Invariant 1: original is not mutated
    assert original.options.time_limit_seconds == 999.0

    # Invariant 2: clamped is a new object with the expected limit
    assert clamped is not original
    assert clamped.options.time_limit_seconds == plan_max


@pytest.mark.unit
def test_clamp_is_noop_when_within_limit():
    original = _make_problem(100.0)
    plan_max = 300.0

    clamped = _clamp_time_limit_to_plan(original, plan_max)

    # When no clamp is needed, the function may return the original OR a copy.
    # The invariant is: final value correct, nothing corrupted.
    assert clamped.options.time_limit_seconds == 100.0
    assert original.options.time_limit_seconds == 100.0
