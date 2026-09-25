"""The Pareto front each solver returns: both ends present, nothing dominated.

# CONTRACT-TEST: a multi-objective front contains both lexicographic ends and no
# point another returned point beats.

Found by driving the multi-objective page (2026-09-25) on one small model,
max 3x+5y (profit) against min 2x+4y (emissions):

- Weighted mode with two points returned (10, 8). (12, 8) is feasible: same
  emissions, more profit. The zero-weight end let the solver pick any point
  that tied on emissions, and it picked a dominated one.
- Epsilon mode never reached the best emissions (8). Its grid stopped one step
  short, so the chart ended at 10.6.

Every solver JAOT ships runs the scalarized subproblems, so every solver is
checked.
"""

from __future__ import annotations

import pytest

from app.domains.solver.adapters import registry
from app.domains.solver.adapters.cbc import CBCAdapter
from app.domains.solver.adapters.glpk import GLPKAdapter
from app.domains.solver.adapters.highs import HiGHSAdapter
from app.domains.solver.adapters.jaos import JAOSAdapter
from app.domains.solver.adapters.scip import SCIPAdapter
from app.domains.solver.services.solver_service import (
    MultiObjectiveSolveError,
    SolverService,
)
from app.schemas.optimization import (
    MultiObjectiveConfig,
    ObjectiveSense,
    ObjectiveSpec,
    OptimizationProblem,
    ParetoPoint,
    SolverStatus,
)

pytestmark = pytest.mark.unit

ADAPTERS = {
    "scip": SCIPAdapter,
    "highs": HiGHSAdapter,
    "cbc": CBCAdapter,
    "glpk": GLPKAdapter,
    "jaos": JAOSAdapter,
}

#: The two lexicographic ends of the model below, as (profit, emissions).
BEST_PROFIT_END = (44.0, 34.0)  # x=3, y=7
BEST_EMISSIONS_END = (12.0, 8.0)  # x=4, y=0 — (10, 8) at x=0, y=2 ties on emissions


@pytest.fixture(params=sorted(ADAPTERS))
def solver(request: pytest.FixtureRequest) -> str:
    adapter = ADAPTERS[request.param]()
    if not adapter.is_available():
        pytest.skip(f"{request.param} is not installed in this image")
    registry.register(request.param, adapter)
    return request.param


def _problem(x_type: str = "continuous") -> OptimizationProblem:
    return OptimizationProblem.model_validate(
        {
            "name": "profit_vs_emissions",
            "objective": {"sense": "maximize", "expression": "3*x + 5*y"},
            "variables": [
                {"name": "x", "type": x_type, "lower_bound": 0},
                {"name": "y", "type": "continuous", "lower_bound": 0},
            ],
            "constraints": [
                {"expression": "x + y <= 10"},
                {"expression": "x <= 8"},
                {"expression": "y <= 7"},
                {"expression": "x + 2*y >= 4"},
            ],
        }
    )


def _config(mode: str, n_points: int, weights: tuple[float, float] | None = None):
    w1, w2 = weights if weights else (None, None)
    return MultiObjectiveConfig(
        mode=mode,
        n_points=n_points,
        objectives=[
            ObjectiveSpec(
                expression="3*x + 5*y", sense=ObjectiveSense.MAXIMIZE, label="P", weight=w1
            ),
            ObjectiveSpec(
                expression="2*x + 4*y", sense=ObjectiveSense.MINIMIZE, label="E", weight=w2
            ),
        ],
    )


def _pairs(points: list[ParetoPoint]) -> list[tuple[float, float]]:
    return [(round(p.f1, 4), round(p.f2, 4)) for p in points]


def _dominated(points: list[ParetoPoint]) -> list[tuple[tuple, tuple]]:
    """Every (loser, winner) pair where the winner is at least as good on both
    objectives (profit up, emissions down) and better on one."""
    tol = 1e-6
    found = []
    for a in points:
        for b in points:
            if a is b:
                continue
            no_worse = b.f1 >= a.f1 - tol and b.f2 <= a.f2 + tol
            better = b.f1 > a.f1 + tol or b.f2 < a.f2 - tol
            if no_worse and better:
                found.append(((a.f1, a.f2), (b.f1, b.f2)))
    return found


def _has(points: list[ParetoPoint], pair: tuple[float, float]) -> bool:
    return any(abs(p.f1 - pair[0]) < 1e-4 and abs(p.f2 - pair[1]) < 1e-4 for p in points)


class TestWeightedMode:
    def test_two_points_are_the_two_lexicographic_ends(self, solver: str) -> None:
        points = SolverService(solver).solve_multi_objective(_problem(), _config("weighted", 2))

        assert _has(points, BEST_EMISSIONS_END), _pairs(points)
        assert _has(points, BEST_PROFIT_END), _pairs(points)
        assert not _has(points, (10.0, 8.0)), "the dominated tie came back"
        assert _dominated(points) == []

    def test_a_longer_sweep_keeps_both_ends_and_drops_nothing_dominated(self, solver: str) -> None:
        points = SolverService(solver).solve_multi_objective(_problem(), _config("weighted", 10))

        assert _has(points, BEST_EMISSIONS_END), _pairs(points)
        assert _has(points, BEST_PROFIT_END), _pairs(points)
        assert _dominated(points) == []

    def test_the_weights_on_the_objectives_do_not_change_the_sweep(self, solver: str) -> None:
        """Weighted mode sweeps every weight, so the ones sent are not read.

        The page used to ask for them and refuse to solve unless they summed to
        1, and then the server ignored them. The field description now says so,
        and this pins that nothing reads them behind its back.
        """
        service = SolverService(solver)
        heavy_profit = service.solve_multi_objective(
            _problem(), _config("weighted", 5, weights=(0.9, 0.1))
        )
        heavy_emissions = service.solve_multi_objective(
            _problem(), _config("weighted", 5, weights=(0.1, 0.9))
        )

        assert _pairs(heavy_profit) == _pairs(heavy_emissions)


class TestEpsilonMode:
    def test_the_front_reaches_the_best_emissions(self, solver: str) -> None:
        points = SolverService(solver).solve_multi_objective(_problem(), _config("epsilon", 10))

        assert _has(points, BEST_EMISSIONS_END), _pairs(points)
        assert _has(points, BEST_PROFIT_END), _pairs(points)
        assert _dominated(points) == []

    def test_an_integer_variable_keeps_both_ends(self, solver: str) -> None:
        points = SolverService(solver).solve_multi_objective(
            _problem(x_type="integer"), _config("epsilon", 5)
        )

        assert _has(points, BEST_EMISSIONS_END), _pairs(points)
        assert _has(points, BEST_PROFIT_END), _pairs(points)
        assert _dominated(points) == []

    def test_n_points_limits_the_front(self, solver: str) -> None:
        points = SolverService(solver).solve_multi_objective(_problem(), _config("epsilon", 4))

        assert len(points) == 4
        assert [p.f2 for p in points] == sorted((p.f2 for p in points), reverse=True)


class TestAnEmptyFrontSaysWhy:
    def test_an_infeasible_model_is_reported_as_infeasible(self) -> None:
        registry.register("scip", SCIPAdapter())
        problem = _problem()
        problem.constraints.append(
            problem.constraints[0].model_copy(update={"expression": "x >= 20"})
        )

        front = SolverService("scip").solve_pareto_front(problem, _config("epsilon", 3))

        assert front.points == []
        assert front.empty_status == SolverStatus.INFEASIBLE

    def test_a_solver_that_cannot_run_the_model_raises(self) -> None:
        """HiGHS refuses a quadratic term. That used to come back as an empty
        front, stored as "optimal" with no points."""
        registry.register("highs", HiGHSAdapter())
        config = _config("weighted", 3)
        config.objectives[0] = config.objectives[0].model_copy(update={"expression": "x*y"})

        with pytest.raises(MultiObjectiveSolveError, match="quadratic"):
            SolverService("highs").solve_pareto_front(_problem(), config)
