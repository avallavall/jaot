"""Test stubs for SOLV-04 — SCIPAdapter structural conformance.

These tests are Wave 0 stubs (RED phase). They will fail at import time or
assertion time because app.domains.solver.adapters.scip does not yet exist.
Plans 02 and 03 must turn them green.
"""

import inspect

import pytest


@pytest.mark.unit
def test_scip_adapter_capabilities_fields() -> None:
    """SCIPAdapter.capabilities must expose correct SolverCapabilities values for SCIP."""
    from app.domains.solver.adapters.scip import SCIPAdapter

    adapter = SCIPAdapter()

    assert adapter.capabilities.name == "scip"
    assert adapter.capabilities.supports_continuous is True
    assert adapter.capabilities.supports_integer is True
    assert adapter.capabilities.supports_binary is True
    assert adapter.capabilities.supports_quadratic is True
    assert adapter.capabilities.supports_sensitivity is True
    assert adapter.capabilities.supports_warm_start is True
    assert adapter.capabilities.supports_multi_objective is False


@pytest.mark.unit
def test_scip_adapter_is_available() -> None:
    """SCIPAdapter.is_available() must return True when pyscipopt is installed."""
    from app.domains.solver.adapters.scip import SCIPAdapter

    # pyscipopt is installed in the dev environment, so this must be True
    assert SCIPAdapter().is_available() is True


@pytest.mark.unit
def test_scip_adapter_solve_signature() -> None:
    """SCIPAdapter.solve must accept (self, problem, *, warm_start=None)."""
    from app.domains.solver.adapters.scip import SCIPAdapter

    sig = inspect.signature(SCIPAdapter.solve)
    params = dict(sig.parameters)

    assert "problem" in params, "solve() must have a 'problem' parameter"
    assert "warm_start" in params, "solve() must have a 'warm_start' parameter"

    warm_start_param = params["warm_start"]
    assert warm_start_param.kind == inspect.Parameter.KEYWORD_ONLY, (
        "warm_start must be a keyword-only argument"
    )
    assert warm_start_param.default is None, "warm_start default must be None"


@pytest.mark.unit
def test_scip_adapter_solves_simple_problem() -> None:
    """SCIPAdapter.solve() must solve a simple LP to optimality with correct values."""
    from app.domains.solver.adapters.scip import SCIPAdapter
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        SolverStatus,
        Variable,
        VariableType,
    )

    problem = OptimizationProblem(
        name="simple_lp",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + 2*y"),
        constraints=[
            Constraint(name="sum_limit", expression="x + y <= 4"),
        ],
    )

    adapter = SCIPAdapter()
    result = adapter.solve(problem)

    assert result.status == SolverStatus.OPTIMAL, f"Expected OPTIMAL, got {result.status}"
    assert result.objective_value == pytest.approx(8.0, abs=1e-6), (
        f"Expected objective 8.0, got {result.objective_value}"
    )
    assert result.solution is not None
    assert result.solution["y"] == pytest.approx(4.0, abs=1e-6), (
        f"Expected y=4.0, got {result.solution['y']}"
    )
    assert result.solution["x"] == pytest.approx(0.0, abs=1e-6), (
        f"Expected x=0.0, got {result.solution['x']}"
    )


@pytest.mark.unit
def test_scip_adapter_accepts_warm_start_kwarg() -> None:
    """SCIPAdapter.solve() must accept warm_start kwarg and report warm_start_used=True."""
    from app.domains.solver.adapters.scip import SCIPAdapter
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    problem = OptimizationProblem(
        name="warm_start_test",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + 2*y"),
        constraints=[
            Constraint(name="sum_limit", expression="x + y <= 4"),
        ],
    )

    adapter = SCIPAdapter()
    result = adapter.solve(problem, warm_start={"x": 1.0, "y": 2.0})

    assert result.warm_start_used is True, (
        "warm_start_used must be True when warm_start dict is provided (D-01)"
    )


# ---------------------------------------------------------------------------
# CONTRACT-TEST: shadow prices and reduced costs must be the ones the LP has, or
# be absent — never zeros nobody computed. SCIP's presolve is allowed to remove
# rows and columns, and `getDualSolVal` / `getVarRedcost` then answer 0 for what
# it removed, indistinguishable from a genuine zero. With the aggressive presolve
# this adapter used to configure unconditionally, the LP below was never solved
# at all (0 simplex iterations) and every shadow price came back -0.0 stamped
# `is_approximate=False` — the platform telling the reader that a constraint
# worth 2.0 is worth nothing, on the DEFAULT solver.
#
# Asserted through strong duality rather than against hard-coded duals: the LP is
# degenerate (three rows tight at a two-dimensional vertex), so more than one
# dual vector is valid and pinning one would fail on a legitimate basis change.
# What is NOT negotiable is sum(shadow_price * rhs) == the optimum.
# ---------------------------------------------------------------------------


def _degenerate_lp():
    """max 3x+2y s.t. x+y<=4, x+3y<=6, x<=3 — optimum 11 at (3,1), all rows tight."""
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    return OptimizationProblem(
        name="degenerate_lp",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="3*x + 2*y"),
        constraints=[
            Constraint(name="c1", expression="x + y <= 4"),
            Constraint(name="c2", expression="x + 3*y <= 6"),
            Constraint(name="cap_x", expression="x <= 3"),
        ],
    )


_RHS = {"c1": 4.0, "c2": 6.0, "cap_x": 3.0}


@pytest.mark.unit
def test_scip_lp_shadow_prices_satisfy_strong_duality() -> None:
    from app.domains.solver.adapters.scip import SCIPAdapter
    from app.schemas.optimization import SolverStatus

    result = SCIPAdapter().solve(_degenerate_lp())

    assert result.status == SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(11.0, abs=1e-6)
    assert result.sensitivity is not None
    assert result.sensitivity.is_approximate is False, "a pure LP's duals are exact, not a guess"

    duals = {c.name: c.shadow_price for c in result.sensitivity.constraints}
    assert set(duals) == set(_RHS)
    assert all(v is not None for v in duals.values()), "a missing dual must be None, not 0.0"

    dual_objective = sum(duals[name] * rhs for name, rhs in _RHS.items())
    assert dual_objective == pytest.approx(11.0, abs=1e-6), (
        f"shadow prices {duals} price the optimum at {dual_objective}, not 11.0"
    )


@pytest.mark.unit
def test_scip_lp_reports_the_binding_rows() -> None:
    """All three rows sit exactly on their limit; at least one must be priced."""
    from app.domains.solver.adapters.scip import SCIPAdapter

    result = SCIPAdapter().solve(_degenerate_lp())

    sensitivity = result.sensitivity
    assert sensitivity is not None
    assert any(c.is_binding for c in sensitivity.constraints), (
        "every row is tight at the optimum, yet none was reported as binding"
    )


@pytest.mark.unit
def test_scip_mip_relaxation_duals_are_not_silently_zero() -> None:
    """The MIP path reads its duals off a rebuilt relaxation, which had the same
    fault under SCIP's *default* presolve — and 'approximate' is a statement about
    the relaxation, not a licence to report zeros nobody computed."""
    from app.domains.solver.adapters.scip import SCIPAdapter
    from app.schemas.optimization import VariableType

    problem = _degenerate_lp()
    problem.variables[0].type = VariableType.INTEGER

    result = SCIPAdapter().solve(problem)

    assert result.objective_value == pytest.approx(11.0, abs=1e-6)
    assert result.sensitivity is not None
    assert result.sensitivity.is_approximate is True
    duals = {c.name: c.shadow_price for c in result.sensitivity.constraints}
    dual_objective = sum(duals[name] * rhs for name, rhs in _RHS.items())
    assert dual_objective == pytest.approx(11.0, abs=1e-6), (
        f"relaxation shadow prices {duals} price the optimum at {dual_objective}, not 11.0"
    )
