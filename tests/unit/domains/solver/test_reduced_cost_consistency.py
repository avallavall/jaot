"""Reduced costs must agree with the shadow prices published beside them.

The Sensitivity tab shows both numbers on one screen. Before this, SCIP billed a
capacity written as a *row* twice — once as that row's dual, again as the variable's
reduced cost — while HiGHS priced the same two models correctly. See
``app/domains/solver/reduced_cost.py`` for the measurements.
"""

import pytest

from app.domains.solver.reduced_cost import derive_reduced_costs
from app.domains.solver.services.expression_parser import ExpressionParser
from app.schemas.optimization import Constraint, Objective, OptimizationProblem, Variable

# max 3x + 2y + z  s.t.  x + y <= 4,  y + z <= 6,  x capped at 3.
# Optimum x=3, y=1, z=5, obj=16, with all three rows active.
_OBJECTIVE = "3*x + 2*y + 1*z"


def _problem(*, cap_as_row: bool, sense: str = "maximize", var_type: str = "continuous"):
    variables = [
        Variable(name="x", type=var_type, lower_bound=0, upper_bound=(10 if cap_as_row else 3)),
        Variable(name="y", type=var_type, lower_bound=0, upper_bound=10),
        Variable(name="z", type=var_type, lower_bound=0, upper_bound=10),
    ]
    constraints = [
        Constraint(name="c1", expression="x + y <= 4"),
        Constraint(name="c2", expression="y + z <= 6"),
    ]
    if cap_as_row:
        constraints.append(Constraint(name="cap_x", expression="x <= 3"))
    return OptimizationProblem(
        name="reduced_cost_case",
        variables=variables,
        objective=Objective(sense=sense, expression=_OBJECTIVE),
        constraints=constraints,
        options={"sensitivity_analysis": True},
    )


def _sensitivity(adapter, problem):
    result = adapter.solve(problem)
    assert result.sensitivity is not None, "solver returned no sensitivity"
    duals = {c.name: c.shadow_price for c in result.sensitivity.constraints}
    costs = {v.name: v.reduced_cost for v in result.sensitivity.variables}
    return result, duals, costs


@pytest.mark.unit
class TestDeriveReducedCosts:
    def test_row_cap_is_priced_once(self) -> None:
        """With the cap as a row its dual carries the price, so x's own cost is 0."""
        problem = _problem(cap_as_row=True)
        derived = derive_reduced_costs(
            problem, {"c1": 1.0, "c2": 1.0, "cap_x": 2.0}, ExpressionParser()
        )
        assert derived == {"x": 0.0, "y": 0.0, "z": 0.0}

    def test_bound_cap_leaves_the_price_on_the_variable(self) -> None:
        """With the cap as a column bound there is no row to hold it: x keeps the 2."""
        problem = _problem(cap_as_row=False)
        derived = derive_reduced_costs(problem, {"c1": 1.0, "c2": 1.0}, ExpressionParser())
        assert derived == {"x": 2.0, "y": 0.0, "z": 0.0}

    def test_missing_dual_derives_nothing(self) -> None:
        """A partial derivation would drop a row's price and still read as confident."""
        problem = _problem(cap_as_row=True)
        assert derive_reduced_costs(problem, {"c1": 1.0, "c2": 1.0}, ExpressionParser()) == {}

    def test_quadratic_model_derives_nothing(self) -> None:
        """No single a_ij to price against — the caller keeps the solver's own answer."""
        problem = _problem(cap_as_row=True)
        quadratic = problem.model_copy(
            update={"objective": Objective(sense="maximize", expression="3*x*y + 1*z")}
        )
        assert derive_reduced_costs(quadratic, {"c1": 1.0, "c2": 1.0}, ExpressionParser()) == {}


@pytest.mark.unit
class TestSolversAgreeWithTheirOwnDuals:
    """# CONTRACT-TEST: a published reduced cost never re-bills a row's shadow price."""

    @staticmethod
    def _assert_consistent(adapter, *, cap_as_row: bool) -> None:
        problem = _problem(cap_as_row=cap_as_row)
        _, duals, costs = _sensitivity(adapter, problem)
        implied = derive_reduced_costs(problem, duals, ExpressionParser())
        assert implied, "the case is linear with every dual present — it must derive"
        for name, value in implied.items():
            assert costs[name] == pytest.approx(value, abs=1e-6), (
                f"{name}: published rc {costs[name]} contradicts the duals {duals}, "
                f"which imply {value}"
            )

    def test_scip_row_cap(self) -> None:
        from app.domains.solver.adapters.scip import SCIPAdapter

        self._assert_consistent(SCIPAdapter(), cap_as_row=True)

    def test_scip_bound_cap(self) -> None:
        from app.domains.solver.adapters.scip import SCIPAdapter

        self._assert_consistent(SCIPAdapter(), cap_as_row=False)

    def test_scip_mip_uses_its_relaxation_duals(self) -> None:
        """The MIP path prices against the LP relaxation it published duals from."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = _problem(cap_as_row=True, var_type="integer")
        _, duals, costs = _sensitivity(SCIPAdapter(), problem)
        implied = derive_reduced_costs(problem, duals, ExpressionParser())
        for name, value in implied.items():
            assert costs[name] == pytest.approx(value, abs=1e-6)

    def test_scip_and_highs_report_the_same_reduced_costs(self) -> None:
        """Two solvers, one model: the reader must not get a different answer per solver."""
        from app.domains.solver.adapters.highs import HiGHSAdapter
        from app.domains.solver.adapters.scip import SCIPAdapter

        highs = HiGHSAdapter()
        if not highs.is_available():
            pytest.skip("highspy not installed")
        for cap_as_row in (True, False):
            _, _, scip_costs = _sensitivity(SCIPAdapter(), _problem(cap_as_row=cap_as_row))
            _, _, highs_costs = _sensitivity(highs, _problem(cap_as_row=cap_as_row))
            for name, value in highs_costs.items():
                assert scip_costs[name] == pytest.approx(value, abs=1e-6), (
                    f"cap_as_row={cap_as_row}, {name}: SCIP {scip_costs[name]} vs HiGHS {value}"
                )
