"""auto_router unit tests — Phase 7.4 / D-11 decision tree.

Covers the post-BYOL select_solver() that uses worker-health probe
instead of SolverLicense DB rows (D-11). No DB required — the function
is pure given a mocked worker-probe result.

Decision tree (post-Phase-7.4):
    1. All CONTINUOUS + linear   -> ("highs",  lp_routed_to_highs,         False)
    2. Quadratic + worker UP     -> ("hexaly", quadratic_routed_to_hexaly,  False)
    3. Quadratic + worker DOWN   -> ("scip",   hexaly_unavailable_fallback, True)
    4. MIP / BINARY + linear     -> ("scip",   milp_routed_to_scip,        False)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.domains.solver.services.auto_router import (
    AUTO_REASON_FALLBACK,
    AUTO_REASON_LP,
    AUTO_REASON_MIP,
    AUTO_REASON_QUADRATIC,
    select_solver,
)
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)


def _lp_problem() -> OptimizationProblem:
    return OptimizationProblem(
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
        ],
        objective=Objective(expression="2*x + 3*y", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="x + y <= 5", name="budget")],
    )


def _quadratic_problem() -> OptimizationProblem:
    return OptimizationProblem(
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
        ],
        objective=Objective(expression="x * y", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="x + y <= 10", name="budget")],
    )


def _mip_problem() -> OptimizationProblem:
    return OptimizationProblem(
        variables=[
            Variable(name="a", type=VariableType.INTEGER, lower_bound=0.0, upper_bound=5.0),
            Variable(name="b", type=VariableType.INTEGER, lower_bound=0.0, upper_bound=5.0),
        ],
        objective=Objective(expression="a + b", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="a + b <= 7", name="bud")],
    )


def _binary_problem() -> OptimizationProblem:
    return OptimizationProblem(
        variables=[
            Variable(name="b1", type=VariableType.BINARY, lower_bound=0.0, upper_bound=1.0),
            Variable(name="b2", type=VariableType.BINARY, lower_bound=0.0, upper_bound=1.0),
        ],
        objective=Objective(expression="b1 + b2", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="b1 + b2 <= 1", name="c")],
    )


# Helper: patch the Hexaly worker probe

# Patch the source-level probe in worker_health (the gate uses it too,
# so a single target covers both code paths). Returns (bool, str | None).
_PROBE_TARGET = "app.domains.solver.services.worker_health._probe_hexaly_worker"


# D-07 / D-11 decision-tree coverage (no DB, no SolverLicense rows)


def test_auto_router_lp_picks_highs():
    """All-CONTINUOUS + linear objective/constraints -> HiGHS (branch 1)."""
    name, reason, fallback = select_solver(_lp_problem())
    assert name == "highs"
    assert reason == AUTO_REASON_LP
    assert fallback is False


def test_auto_router_quadratic_with_worker_up_picks_hexaly():
    """Quadratic objective + Hexaly worker healthy -> Hexaly (branch 2)."""
    with patch(_PROBE_TARGET, return_value=(True, None)):
        name, reason, fallback = select_solver(_quadratic_problem())
    assert name == "hexaly"
    assert reason == AUTO_REASON_QUADRATIC
    assert fallback is False


def test_auto_router_quadratic_with_worker_down_picks_scip():
    """Quadratic objective + Hexaly worker down -> SCIP fallback (branch 3)."""
    with patch(_PROBE_TARGET, return_value=(False, "test_probe_off")):
        name, reason, fallback = select_solver(_quadratic_problem())
    assert name == "scip"
    assert reason == AUTO_REASON_FALLBACK
    assert fallback is True


def test_auto_router_mip_picks_scip():
    """INTEGER variables + linear -> SCIP default (branch 4)."""
    name, reason, fallback = select_solver(_mip_problem())
    assert name == "scip"
    assert reason == AUTO_REASON_MIP
    assert fallback is False


def test_auto_router_binary_picks_scip():
    """BINARY variables + linear -> SCIP default (branch 4, mixed not LP)."""
    name, reason, fallback = select_solver(_binary_problem())
    assert name == "scip"
    assert reason == AUTO_REASON_MIP
    assert fallback is False


def test_auto_router_quadratic_constraint_detected():
    """Linear objective but quadratic constraint 'x*y <= 10' classifies as quadratic."""
    problem = OptimizationProblem(
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
        ],
        objective=Objective(expression="x + y", sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="x * y <= 10", name="nonlinear")],
    )
    with patch(_PROBE_TARGET, return_value=(True, None)):
        name, reason, fallback = select_solver(problem)
    assert name == "hexaly"
    assert reason == AUTO_REASON_QUADRATIC


@pytest.mark.parametrize("expr", ["x * x", "x**2", "2 * x * x"])
def test_auto_router_x_squared_detected(expr: str):
    """Pitfall 5: x*x / x**2 / 2*x*x are all quadratic — worker-down -> SCIP."""
    problem = OptimizationProblem(
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0, upper_bound=10.0),
        ],
        objective=Objective(expression=expr, sense=ObjectiveSense.MAXIMIZE),
        constraints=[Constraint(expression="x <= 10", name="c")],
    )
    with patch(_PROBE_TARGET, return_value=(False, "test_probe_off")):
        name, reason, fallback = select_solver(problem)
    assert name == "scip"
    assert reason == AUTO_REASON_FALLBACK
    assert fallback is True


def test_auto_router_no_db_access():
    """select_solver must NOT take a DB session — Phase 7.4 / D-11 invariant.

    Pre-7.4 the router consulted ``solver_licenses`` rows for BYOL routing.
    Phase 7.4 replaces that with a worker-health probe so the function is
    DB-free. We enforce the invariant statically (signature) AND
    behaviorally (call without a db_session fixture and check the LP path
    returns HiGHS without raising).
    """
    import inspect

    # Static check: the signature must NOT advertise a `db` parameter. A
    # future maintainer adding `db: Session = None` would silently re-couple
    # the router to the request scope — fail loudly here.
    sig = inspect.signature(select_solver)
    assert "db" not in sig.parameters, (
        "select_solver must remain DB-free (D-11). "
        "If you need session-scoped state, route it through worker_health."
    )

    # Behavioral check: LP path returns HiGHS without any probe / DB access.
    name, reason, fallback = select_solver(_lp_problem())
    assert name == "highs"
    assert reason == AUTO_REASON_LP
    assert fallback is False


# The routing policy names its solvers directly — "lp_routed_to_highs" is a
# stable public slug, so the tree cannot be made dynamic without changing the
# API contract for branches that never fire in practice. What CAN rot silently
# is the assumption underneath each branch: that the solver it names is actually
# able to do the job. These tests turn those tacit assumptions into invariants,
# so an adapter that changes what it supports fails here instead of in
# production.


# Capabilities are read off the adapter CLASSES rather than the registry: the
# registry is populated by create_app(), which a unit test does not run, and the
# declaration is what we actually want to pin.


# CONTRACT-TEST: branch 3 falls back to SCIP for a QUADRATIC problem. That is
# only sound while SCIP declares it handles quadratics.
def test_quadratic_fallback_target_actually_supports_quadratics():
    from app.domains.solver.adapters.scip import SCIPAdapter

    assert SCIPAdapter.capabilities.supports_quadratic is True, (
        "auto_router falls back to SCIP for quadratic problems "
        f"({AUTO_REASON_FALLBACK}); SCIP no longer declares supports_quadratic, "
        "so that branch would now route work to a solver that cannot do it."
    )


# CONTRACT-TEST: branch 1 sends every LP to HiGHS unconditionally, with no
# availability check, because HiGHS ships in the base image and is registered
# unconditionally at startup.
def test_lp_branch_target_is_registered_unconditionally_and_linear_capable():
    import inspect

    from app.domains.solver import adapters
    from app.domains.solver.adapters.highs import HiGHSAdapter

    assert HiGHSAdapter.capabilities.supports_continuous is True

    source = inspect.getsource(adapters.register_default_adapters)
    assert 'registry.register("highs", HiGHSAdapter())' in source, (
        f"auto_router routes every LP to HiGHS ({AUTO_REASON_LP}) with no "
        "availability check, on the assumption HiGHS always registers. If that "
        "registration became conditional, the branch could route to a solver "
        "that is not there."
    )


# CONTRACT-TEST: branch 2 prefers Hexaly for quadratics. The preference is a
# product decision, but it must at least be true that Hexaly can do it.
def test_quadratic_preference_target_declares_quadratic_support():
    from app.domains.solver.adapters.hexaly import HexalyAdapter

    # Read the class attribute: the SDK is a lazy import, so this needs neither
    # the proprietary package nor the licence file.
    assert HexalyAdapter.capabilities.supports_quadratic is True, (
        f"auto_router prefers Hexaly for quadratic problems ({AUTO_REASON_QUADRATIC})."
    )
