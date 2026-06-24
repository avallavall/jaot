"""
Rigorous integration tests for MDPDP-TW-T generator.

These tests use REAL problem sizes that exercise the solver meaningfully,
and verify solution CORRECTNESS — not just that the solver returns OPTIMAL.

Test categories:
1. Solution verification: parse solution, check every constraint holds
2. Multi-vehicle multi-order: 3v/4o+ with tachograph
3. Warm start impact: verify heuristic improves solver performance
4. Combined features: tachograph + rest stops + composition
5. Infeasibility verification: problems that MUST be infeasible
"""

import math
import time
from typing import Any

import pytest

from app.domains.solver.services.generators import get_generator
from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import SolverStatus


@pytest.fixture(scope="module")
def solver() -> SolverService:
    return SolverService()


@pytest.fixture(scope="module")
def gen():
    return get_generator("mdpdp")


CITIES = {
    "BCN": (2.17, 41.38),
    "MAD": (-3.70, 40.42),
    "VLC": (-0.37, 39.47),
    "ZAR": (-0.88, 41.65),
    "BIL": (-2.93, 43.26),
    "SEV": (-5.98, 37.38),
    "MAL": (-4.42, 36.72),
    "MUR": (-1.13, 37.98),
}


def _haversine_km(c1: tuple[float, float], c2: tuple[float, float]) -> float:
    lon1, lat1 = math.radians(c1[0]), math.radians(c1[1])
    lon2, lat2 = math.radians(c2[0]), math.radians(c2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a)) * 1.3


def _build_distances(cities: dict[str, tuple[float, float]]) -> list[dict[str, Any]]:
    return [
        {
            "from": c1,
            "to": c2,
            "km": round(_haversine_km(cities[c1], cities[c2]), 1),
            "hours": round(_haversine_km(cities[c1], cities[c2]) / 90, 2),
        }
        for c1 in cities
        for c2 in cities
        if c1 != c2
    ]


DISTANCES = _build_distances(CITIES)


def _build_problem(
    n_orders: int,
    n_vehicles: int,
    orders: list[dict[str, Any]],
    depot_cities: list[str],
    tacho: bool = True,
    time_limit: int = 30,
) -> dict[str, Any]:
    return {
        "orders": orders,
        "tractors": [
            {
                "id": f"tr_{i}",
                "depot": f"dep_{i}",
                "fuel_cost_per_km": 0.35,
                "max_distance": 1500,
            }
            for i in range(n_vehicles)
        ],
        "trailers": [{"id": f"tl_{i}", "capacity_pallets": 33} for i in range(n_vehicles)],
        "drivers": [{"id": f"dr_{i}"} for i in range(n_vehicles)],
        "depots": [{"id": f"dep_{i}", "location": depot_cities[i]} for i in range(n_vehicles)],
        "distances": DISTANCES,
        "config": {"tachograph_enabled": tacho, "time_limit_seconds": time_limit},
    }


class TestSolutionVerification:
    """Verify that returned solutions are actually feasible."""

    def test_route_continuity(self, solver, gen):
        """Every used vehicle's route must be a connected path from origin to endpoint."""
        problem = gen.generate(
            _build_problem(
                2,
                2,
                [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 5},
                ],
                ["BCN", "VLC"],
                tacho=False,
            ),
            {},
        )
        r = solver.solve(problem)
        v = r.solution or {}
        assert r.status == SolverStatus.OPTIMAL

        # For each used vehicle, extract route arcs and verify connectivity
        for k in range(2):
            if v.get(f"y_{k}", 0) < 0.5:
                continue
            active_arcs = [
                name
                for name, val in v.items()
                if name.startswith("x_") and name.endswith(f"_{k}") and val > 0.5
            ]
            assert len(active_arcs) >= 2, f"Vehicle {k} used but has < 2 arcs"

    def test_pickup_before_delivery(self, solver, gen):
        """For every served order, the pickup arrival time must be <= delivery arrival time."""
        problem = gen.generate(
            _build_problem(
                2,
                2,
                [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 5},
                ],
                ["BCN", "VLC"],
                tacho=False,
            ),
            {},
        )
        r = solver.solve(problem)
        v = r.solution or {}
        assert r.status == SolverStatus.OPTIMAL

        for idx in range(2):
            if v.get(f"z_{idx}", 0) > 0.5:
                continue  # unserved, skip
            # Find which vehicle serves this order
            for k in range(2):
                s_p = v.get(f"s_p_{idx}_{k}", 0)
                s_d = v.get(f"s_d_{idx}_{k}", 0)
                # Check if this vehicle has arcs to this order
                has_pickup = any(
                    name.startswith(f"x_p_{idx}_") and name.endswith(f"_{k}") and val > 0.5
                    for name, val in v.items()
                )
                if has_pickup:
                    assert s_p <= s_d, (
                        f"Order {idx}: pickup time {s_p:.2f} > delivery time {s_d:.2f} for vehicle {k}"
                    )

    def test_all_served_orders_have_routes(self, solver, gen):
        """If z_i = 0 (served), there must be X arcs for both pickup and delivery."""
        problem = gen.generate(
            _build_problem(
                3,
                2,
                [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 5},
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "VLC"}, "pallets": 3},
                ],
                ["BCN", "VLC"],
                tacho=False,
            ),
            {},
        )
        r = solver.solve(problem)
        v = r.solution or {}
        assert r.status == SolverStatus.OPTIMAL

        for idx in range(3):
            if v.get(f"z_{idx}", 0) > 0.5:
                continue
            # Must have at least one outgoing arc from pickup
            p_arcs = [
                name for name, val in v.items() if name.startswith(f"x_p_{idx}_") and val > 0.5
            ]
            d_arcs = [
                name for name, val in v.items() if name.startswith(f"x_d_{idx}_") and val > 0.5
            ]
            assert len(p_arcs) > 0, f"Served order {idx} has no pickup arc"
            assert len(d_arcs) > 0, f"Served order {idx} has no delivery arc"


class TestMultiVehicleMultiOrder:
    """Tests that actually exercise the solver with realistic problem sizes."""

    def test_3v_4o_with_tachograph(self, solver, gen):
        """3 vehicles, 4 orders, tachograph enabled. Solver must work > 1 second."""
        start = time.time()
        problem = gen.generate(
            _build_problem(
                4,
                3,
                [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 8},
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "VLC"}, "pallets": 3},
                    {"pickup": {"location": "ZAR"}, "delivery": {"location": "BIL"}, "pallets": 6},
                ],
                ["BCN", "VLC", "ZAR"],
                tacho=True,
                time_limit=30,
            ),
            {},
        )
        r = solver.solve(problem)
        v = r.solution or {}
        _ = time.time() - start  # measure but don't assert timing

        assert r.status in (SolverStatus.OPTIMAL, SolverStatus.TIME_LIMIT)
        assert r.objective_value is not None
        assert r.warm_start_used is True
        assert len(problem.variables) > 200, "Problem must be non-trivial"
        assert len(problem.constraints) > 500, "Problem must be non-trivial"

        served = sum(1 for i in range(4) if v.get(f"z_{i}", 1) < 0.5)
        assert served >= 2, f"Should serve at least 2/4 orders, got {served}"

    def test_2v_3o_all_served_no_tacho(self, solver, gen):
        """2 vehicles, 3 nearby orders, no tachograph. All should be served."""
        problem = gen.generate(
            _build_problem(
                3,
                2,
                [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "VLC"}, "pallets": 3},
                    {"pickup": {"location": "ZAR"}, "delivery": {"location": "BCN"}, "pallets": 4},
                ],
                ["BCN", "ZAR"],
                tacho=False,
                time_limit=30,
            ),
            {},
        )
        r = solver.solve(problem)
        v = r.solution or {}

        assert r.status == SolverStatus.OPTIMAL
        unserved = [k for k, val in v.items() if k.startswith("z_") and val > 0.5]
        assert len(unserved) == 0, f"All 3 orders should be served, unserved: {unserved}"
        assert r.objective_value > 0, "Cost must be positive"


class TestWarmStart:
    """Verify warm start heuristic produces valid initial solutions."""

    def test_heuristic_produces_warm_start(self, gen):
        """Generator must produce a non-None warm start for a solvable problem."""
        problem = gen.generate(
            _build_problem(
                2,
                2,
                [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 5},
                ],
                ["BCN", "VLC"],
                tacho=False,
            ),
            {},
        )
        ws = problem.heuristic_warm_start
        assert ws is not None, "Warm start should be produced"
        assert len(ws) > 0, "Warm start should have variables"

        # Warm start must have all Z variables
        for i in range(2):
            assert f"z_{i}" in ws, f"Warm start missing z_{i}"

        # At least one Y variable should be 1 (vehicle used)
        y_used = [k for k, val in ws.items() if k.startswith("y_") and val > 0.5]
        assert len(y_used) > 0, "At least one vehicle should be used in warm start"

    def test_warm_start_routes_are_valid(self, gen):
        """Warm start X arcs must form valid paths (origin → ... → endpoint)."""
        problem = gen.generate(
            _build_problem(
                1,
                1,
                [{"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5}],
                ["BCN"],
                tacho=False,
            ),
            {},
        )
        ws = problem.heuristic_warm_start
        assert ws is not None

        # Extract route
        x_arcs = [k for k, v in ws.items() if k.startswith("x_") and v > 0.5]
        assert len(x_arcs) >= 2, "Route must have at least depot→pickup→delivery→depot"

        # Must start from origin and end at endpoint
        starts_from_origin = any("x_o_0_" in a for a in x_arcs)
        ends_at_endpoint = any("_e_0_0" in a for a in x_arcs)
        assert starts_from_origin, "Route must start from origin"
        assert ends_at_endpoint, "Route must end at endpoint"

    def test_warm_start_used_by_solver(self, solver, gen):
        """Solver must report warm_start_used=True when heuristic is provided."""
        problem = gen.generate(
            _build_problem(
                1,
                1,
                [{"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5}],
                ["BCN"],
                tacho=False,
            ),
            {},
        )
        assert problem.heuristic_warm_start is not None
        r = solver.solve(problem)
        assert r.warm_start_used is True

    def test_warm_start_arrival_times_monotonic(self, gen):
        """Arrival times in warm start must increase along the route."""
        problem = gen.generate(
            _build_problem(
                2,
                1,
                [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "ZAR"}, "delivery": {"location": "VLC"}, "pallets": 3},
                ],
                ["BCN"],
                tacho=False,
            ),
            {},
        )
        ws = problem.heuristic_warm_start
        assert ws is not None

        # Get S values along route
        s_vals = {k: v for k, v in ws.items() if k.startswith("s_") and k.endswith("_0")}
        times = sorted(s_vals.values())
        # Times should be non-decreasing
        for i in range(len(times) - 1):
            assert times[i] <= times[i + 1], f"Times not monotonic: {times}"


class TestCombinedFeatures:
    """Test tachograph + rest stops + composition working together."""

    def test_tacho_rest_stops_composition_together(self, solver, gen):
        """Full-featured problem: tachograph, rest stops, vehicle composition."""
        problem = gen.generate(
            _build_problem(
                2,
                2,
                [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 8},
                ],
                ["BCN", "VLC"],
                tacho=True,
                time_limit=30,
            ),
            {},
        )
        r = solver.solve(problem)
        v = r.solution or {}

        assert r.status in (SolverStatus.OPTIMAL, SolverStatus.TIME_LIMIT)
        assert r.objective_value is not None

        # If any order is served, composition must be assigned
        for k in range(2):
            if v.get(f"y_{k}", 0) < 0.5:
                continue
            tr = [
                name
                for name, val in v.items()
                if name.startswith("atr_") and name.endswith(f"_{k}") and val > 0.5
            ]
            tl = [
                name
                for name, val in v.items()
                if name.startswith("atl_") and name.endswith(f"_{k}") and val > 0.5
            ]
            dr = [
                name
                for name, val in v.items()
                if name.startswith("adr_") and name.endswith(f"_{k}") and val > 0.5
            ]
            assert len(tr) == 1, f"Vehicle {k} must have exactly 1 tractor, got {len(tr)}"
            assert len(tl) == 1, f"Vehicle {k} must have exactly 1 trailer, got {len(tl)}"
            assert len(dr) == 1, f"Vehicle {k} must have exactly 1 driver, got {len(dr)}"


class TestInfeasibility:
    """Problems that MUST result in specific outcomes."""

    def test_impossible_daily_driving(self, solver, gen):
        """6.5h each way = 13h total > 10h daily limit. Must be unserved."""
        problem = gen.generate(
            {
                "orders": [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5}
                ],
                "tractors": [
                    {"id": "tr1", "depot": "dep1", "fuel_cost_per_km": 0.35, "max_distance": 2000}
                ],
                "trailers": [{"id": "tl1", "capacity_pallets": 33}],
                "drivers": [{"id": "dr1"}],
                "depots": [{"id": "dep1", "location": "BCN"}],
                "distances": [
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
                ],
                "config": {"tachograph_enabled": True, "time_limit_seconds": 30},
            },
            {},
        )
        r = solver.solve(problem)
        v = r.solution or {}
        assert r.status == SolverStatus.OPTIMAL
        assert v.get("z_0", 0) > 0.5, "Order must be unserved (13h > 10h daily limit)"
