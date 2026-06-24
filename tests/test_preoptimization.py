"""
Tests for Pilar 2.5 pre-optimization utilities in base.py.

Covers:
1. build_reachable_nodes: edge cases, empty arcs, multi-vehicle
2. compute_arc_big_m: correctness, non-positive M guard, edge values
3. add_symmetry_breaking: groups, single-element groups, empty groups
4. Reachability pruning integration with MDPDP
5. S2 vehicle-order compatibility filter edge cases
6. Per-arc big-M correctness in constraints
"""

import pytest

from app.domains.solver.services.generators import get_generator
from app.domains.solver.services.generators.base import (
    add_symmetry_breaking,
    build_reachable_nodes,
    compute_arc_big_m,
)
from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import Constraint, SolverStatus


@pytest.fixture(scope="module")
def solver() -> SolverService:
    return SolverService()


@pytest.fixture(scope="module")
def gen():
    return get_generator("mdpdp")


# 1. build_reachable_nodes


class TestBuildReachableNodes:
    def test_basic_reachability(self):
        arcs = [("a", "b", 0), ("b", "c", 0), ("d", "e", 1)]
        r = build_reachable_nodes(arcs)
        assert r[0] == {"a", "b", "c"}
        assert r[1] == {"d", "e"}

    def test_empty_arcs_returns_empty(self):
        r = build_reachable_nodes([])
        assert len(r) == 0

    def test_missing_vehicle_returns_empty_set(self):
        """Vehicle with no arcs should return empty set, not KeyError."""
        arcs = [("a", "b", 0)]
        r = build_reachable_nodes(arcs)
        assert r[99] == set()  # defaultdict returns empty set

    def test_single_arc(self):
        arcs = [("x", "y", 5)]
        r = build_reachable_nodes(arcs)
        assert r[5] == {"x", "y"}

    def test_self_loop(self):
        arcs = [("a", "a", 0)]
        r = build_reachable_nodes(arcs)
        assert r[0] == {"a"}


# 2. compute_arc_big_m


class TestComputeArcBigM:
    def test_basic_computation(self):
        node_i = {"service_time": 0.5, "earliest": 0}
        node_j = {"earliest": 0, "latest": 24}
        m = compute_arc_big_m(node_i, node_j, travel_time=3.0, planning_horizon=30.0)
        # M = 30 + 0.5 + 3.0 - 0 + 1.0 = 34.5
        assert m == pytest.approx(34.5)

    def test_tighter_with_positive_earliest(self):
        node_i = {"service_time": 0.5}
        node_j_early = {"earliest": 10}
        node_j_zero = {"earliest": 0}
        m_early = compute_arc_big_m(node_i, node_j_early, 3.0, 30.0)
        m_zero = compute_arc_big_m(node_i, node_j_zero, 3.0, 30.0)
        assert m_early < m_zero  # tighter when earliest > 0

    def test_zero_travel_zero_service(self):
        m = compute_arc_big_m({}, {}, travel_time=0, planning_horizon=24.0)
        # M = 24 + 0 + 0 - 0 + 1 = 25
        assert m == pytest.approx(25.0)

    def test_non_positive_m_raises(self):
        """If earliest_j > planning_horizon, M would be non-positive."""
        with pytest.raises(ValueError, match="non-positive"):
            compute_arc_big_m({}, {"earliest": 100}, travel_time=0, planning_horizon=10.0)

    def test_always_positive(self):
        """M should always be positive for valid inputs."""
        m = compute_arc_big_m(
            {"service_time": 0}, {"earliest": 23.9}, travel_time=0, planning_horizon=24.0
        )
        assert m > 0


# 3. add_symmetry_breaking


class TestAddSymmetryBreaking:
    def test_basic_pair(self):
        constraints: list[Constraint] = []
        add_symmetry_breaking(constraints, {0: "y_0", 1: "y_1"}, [[0, 1]])
        assert len(constraints) == 1
        assert "y_0" in constraints[0].expression
        assert "y_1" in constraints[0].expression

    def test_triple_group(self):
        constraints: list[Constraint] = []
        add_symmetry_breaking(constraints, {0: "y_0", 1: "y_1", 2: "y_2"}, [[0, 1, 2]])
        assert len(constraints) == 2  # y_0 >= y_1, y_1 >= y_2

    def test_single_element_group_skipped(self):
        constraints: list[Constraint] = []
        add_symmetry_breaking(constraints, {0: "y_0"}, [[0]])
        assert len(constraints) == 0

    def test_empty_group_skipped(self):
        constraints: list[Constraint] = []
        add_symmetry_breaking(constraints, {}, [[]])
        assert len(constraints) == 0

    def test_multiple_groups(self):
        constraints: list[Constraint] = []
        add_symmetry_breaking(
            constraints, {0: "y_0", 1: "y_1", 2: "y_2", 3: "y_3"}, [[0, 1], [2, 3]]
        )
        assert len(constraints) == 2

    def test_missing_var_in_group_skipped(self):
        constraints: list[Constraint] = []
        add_symmetry_breaking(constraints, {0: "y_0"}, [[0, 99]])  # 99 not in vars
        assert len(constraints) == 0


class TestReachabilityPruning:
    def test_unreachable_vehicle_gets_no_s_vars(self, gen):
        """With 2 vehicles but only 1 depot's city in distances,
        the other vehicle should have fewer S variables."""
        problem = gen.generate(
            {
                "orders": [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5}
                ],
                "tractors": [
                    {"id": "tr1", "depot": "dep1", "fuel_cost_per_km": 0.35, "max_distance": 1500},
                    {"id": "tr2", "depot": "dep2", "fuel_cost_per_km": 0.35, "max_distance": 1500},
                ],
                "trailers": [
                    {"id": "tl1", "capacity_pallets": 33},
                    {"id": "tl2", "capacity_pallets": 33},
                ],
                "drivers": [{"id": "dr1"}, {"id": "dr2"}],
                "depots": [{"id": "dep1", "location": "BCN"}, {"id": "dep2", "location": "SEV"}],
                "distances": [
                    {"from": "BCN", "to": "ZAR", "km": 300, "hours": 3.0},
                    {"from": "ZAR", "to": "BCN", "km": 300, "hours": 3.0},
                ],
                "config": {"tachograph_enabled": False, "time_limit_seconds": 30},
            },
            {},
        )
        # Vehicle 1 (SEV depot) can't reach BCN/ZAR — no distance entries
        # S2 filter should remove its arcs to the order
        s_vars_v0 = [
            v.name for v in problem.variables if v.name.startswith("s_") and v.name.endswith("_0")
        ]
        s_vars_v1 = [
            v.name for v in problem.variables if v.name.startswith("s_") and v.name.endswith("_1")
        ]
        # Vehicle 1 should have fewer S vars (only its own depot nodes)
        assert len(s_vars_v1) < len(s_vars_v0)


class TestS2Filter:
    def test_same_location_depot_pickup_not_filtered(self, solver, gen):
        """Depot and pickup at same location should never be filtered."""
        r, v = _solve(
            solver,
            gen,
            {
                "tractors": [
                    {"id": "tr1", "depot": "dep1", "fuel_cost_per_km": 0.35, "max_distance": 1500}
                ],
                "trailers": [{"id": "tl1", "capacity_pallets": 33}],
                "drivers": [{"id": "dr1"}],
                "depots": [{"id": "dep1", "location": "BCN"}],
                "orders": [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5}
                ],
                "distances": [
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
                ],
                "config": {"tachograph_enabled": False, "time_limit_seconds": 30},
            },
        )
        assert r.status == SolverStatus.OPTIMAL
        assert r.objective_value == pytest.approx(434.0, abs=0.1)

    def test_far_depot_order_filtered(self, gen):
        """Vehicle at far depot with tight time window should be filtered."""
        problem = gen.generate(
            {
                "tractors": [
                    {"id": "tr1", "depot": "dep1", "fuel_cost_per_km": 0.35, "max_distance": 1500}
                ],
                "trailers": [{"id": "tl1", "capacity_pallets": 33}],
                "drivers": [{"id": "dr1"}],
                "depots": [{"id": "dep1", "location": "COR"}],
                "orders": [
                    {
                        "pickup": {"location": "BCN", "latest": 2},
                        "delivery": {"location": "MAD"},
                        "pallets": 5,
                    }
                ],
                "distances": [
                    {"from": "COR", "to": "BCN", "km": 1200, "hours": 12},
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                    {"from": "MAD", "to": "COR", "km": 800, "hours": 8},
                ],
                "config": {"tachograph_enabled": False, "time_limit_seconds": 30},
            },
            {},
        )
        # COR→BCN takes 12h but pickup latest is 2h (+ 4h tardiness = 6h max)
        # 12h > 6h → vehicle-order pair should be filtered → only z_0 arc
        x_vars = [
            v.name
            for v in problem.variables
            if v.name.startswith("x_p_") or v.name.startswith("x_d_")
        ]
        assert len(x_vars) == 0, "Order arcs should be filtered (depot too far)"


class TestPerArcBigM:
    def test_tighter_earliest_produces_tighter_constraint(self, gen):
        """Orders with earliest > 0 on delivery should produce strictly tighter big-M.

        Big-M formula: M = horizon + service_time + travel_time - a_j + 1
        A larger a_j (delivery earliest) produces a smaller M.
        We extract the M value by finding the arc time-propagation constraint
        for the pickup->delivery arc and comparing the numeric M directly.
        """
        import re

        base_body = {
            "tractors": [
                {"id": "tr1", "depot": "dep1", "fuel_cost_per_km": 0.35, "max_distance": 1500}
            ],
            "trailers": [{"id": "tl1", "capacity_pallets": 33}],
            "drivers": [{"id": "dr1"}],
            "depots": [{"id": "dep1", "location": "BCN"}],
            "distances": [
                {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
            ],
            "config": {"tachograph_enabled": False},
        }
        p1 = gen.generate(
            {
                **base_body,
                "orders": [
                    {
                        "pickup": {"location": "BCN", "earliest": 0},
                        "delivery": {"location": "MAD", "earliest": 0},
                        "pallets": 5,
                    }
                ],
            },
            {},
        )
        p2 = gen.generate(
            {
                **base_body,
                "orders": [
                    {
                        "pickup": {"location": "BCN", "earliest": 0},
                        "delivery": {"location": "MAD", "earliest": 10},
                        "pallets": 5,
                    }
                ],
            },
            {},
        )

        def _pickup_delivery_m(problem) -> float:
            """Extract the big-M coefficient from the pickup->delivery time constraint.

            The constraint is c14_time_p_0_d_0_0 with shape
              s_p_0_0 + M*x_p_0_d_0_0 + -1*s_d_0_0 <= M - 0 - 6.5
            """
            for c in problem.constraints:
                if c.name != "c14_time_p_0_d_0_0":
                    continue
                match = re.search(r"([0-9]+(?:\.[0-9]+)?)\*x_p_0_d_0_0", c.expression)
                assert match, f"Cannot find M in c14_time_p_0_d_0_0: {c.expression}"
                return float(match.group(1))
            raise AssertionError("Pickup->delivery time constraint not found")

        m1 = _pickup_delivery_m(p1)
        m2 = _pickup_delivery_m(p2)
        assert m2 < m1, f"Expected m2 < m1 (delivery earliest=10 tighter), got m1={m1}, m2={m2}"

        # Both problems remain solvable with the same objective.
        r1 = SolverService().solve(p1)
        r2 = SolverService().solve(p2)
        assert r1.status == SolverStatus.OPTIMAL
        assert r2.status == SolverStatus.OPTIMAL
        assert r1.objective_value == pytest.approx(434.0, abs=0.1)
        assert r2.objective_value == pytest.approx(434.0, abs=0.1)


def _solve(solver, gen, user_input):
    problem = gen.generate(user_input, {})
    result = solver.solve(problem)
    return result, result.solution or {}
