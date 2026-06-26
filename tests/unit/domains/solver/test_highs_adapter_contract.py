"""HiGHS adapter contract tests — Phase 5 / HIGH-01, HIGH-02.

All tests in this file are RED until app/domains/solver/adapters/highs.py is
implemented (Plan 02). Do NOT skip or xfail — they must FAIL on collection.
"""

from app.schemas.optimization import (
    Constraint,
    Objective,
    OptimizationProblem,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableType,
)


def _lp_problem() -> OptimizationProblem:
    """Small LP: minimize x + y s.t. x + y >= 10, x >= 0, y >= 0."""
    return OptimizationProblem(
        name="test_lp",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0),
            Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0.0),
        ],
        constraints=[
            Constraint(expression="x + y >= 10"),
        ],
        objective=Objective(expression="x + y", sense="minimize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False),
    )


def _mip_problem() -> OptimizationProblem:
    """Small MIP: binary x, maximize x, x <= 1."""
    return OptimizationProblem(
        name="test_mip",
        variables=[
            Variable(name="x", type=VariableType.BINARY),
        ],
        constraints=[
            Constraint(expression="x <= 1"),
        ],
        objective=Objective(expression="x", sense="maximize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False),
    )


def _infeasible_problem() -> OptimizationProblem:
    """Infeasible LP: x >= 10 and x <= 5."""
    return OptimizationProblem(
        name="test_infeasible",
        variables=[
            Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0.0),
        ],
        constraints=[
            Constraint(expression="x >= 10"),
            Constraint(expression="x <= 5"),
        ],
        objective=Objective(expression="x", sense="minimize"),
        options=SolverOptions(time_limit_seconds=30.0, verbose=False),
    )


class TestHiGHSAdapterContract:
    """Protocol conformance and known-answer tests for HiGHSAdapter."""

    def test_highs_adapter_capabilities(self) -> None:
        """HiGHSAdapter.capabilities must satisfy SolverCapabilities contract."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415

        adapter = HiGHSAdapter()
        caps = adapter.capabilities
        assert caps.name == "highs"
        assert caps.supports_continuous is True
        assert caps.supports_integer is True
        assert caps.supports_binary is True

    def test_highs_adapter_is_available(self) -> None:
        """HiGHSAdapter.is_available() returns True when highspy installed."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415

        assert HiGHSAdapter().is_available() is True

    def test_highs_known_answer_lp(self) -> None:
        """LP: minimize x+y s.t. x+y>=10 → optimal value 10.0."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415

        adapter = HiGHSAdapter()
        result = adapter.solve(_lp_problem())
        assert result.status == SolverStatus.OPTIMAL
        assert result.objective_value is not None
        assert abs(result.objective_value - 10.0) < 1e-6

    def test_highs_known_answer_mip(self) -> None:
        """MIP: binary x, maximize x → optimal value 1.0."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415

        adapter = HiGHSAdapter()
        result = adapter.solve(_mip_problem())
        assert result.status == SolverStatus.OPTIMAL
        assert result.objective_value is not None
        assert abs(result.objective_value - 1.0) < 1e-6

    def test_highs_known_infeasible(self) -> None:
        """Infeasible LP returns INFEASIBLE status."""
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415

        adapter = HiGHSAdapter()
        result = adapter.solve(_infeasible_problem())
        assert result.status == SolverStatus.INFEASIBLE

    def test_highs_lp_sensitivity_is_exact(self) -> None:
        """Pure-LP solves must carry exact (non-approximate) sensitivity.

        Regression: the adapter advertised ``supports_sensitivity=True`` but
        never read HiGHS duals, so LP problems auto-routed to HiGHS came back
        with ``result.sensitivity = None`` and an empty UI "Sensitivity" tab.
        """
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415

        result = HiGHSAdapter().solve(_lp_problem())
        assert result.status == SolverStatus.OPTIMAL
        sens = result.sensitivity
        assert sens is not None, "LP solve must produce sensitivity"
        assert sens.is_approximate is False  # HiGHS LP duals are exact
        # One constraint (x + y >= 10), binding at the optimum with a real dual.
        assert len(sens.constraints) == 1
        constraint = sens.constraints[0]
        assert constraint.shadow_price is not None
        assert constraint.is_binding is True
        # Reduced costs present (exact) for both decision variables.
        assert {v.name for v in sens.variables} == {"x", "y"}
        assert all(v.reduced_cost is not None for v in sens.variables)
        assert all(v.is_approximate is False for v in sens.variables)

    def test_highs_mip_has_no_dual_sensitivity(self) -> None:
        """MIP solves carry no meaningful HiGHS duals — sensitivity stays None.

        HiGHS exposes no useful dual solution for a MIP; we must return None
        rather than fabricate misleading shadow prices.
        """
        from app.domains.solver.adapters.highs import HiGHSAdapter  # noqa: PLC0415

        result = HiGHSAdapter().solve(_mip_problem())
        assert result.status == SolverStatus.OPTIMAL
        assert result.sensitivity is None
