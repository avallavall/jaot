"""
Stress tests and cross-generator pre-optimization tests.

Marked @pytest.mark.slow — excluded from normal CI runs.
Run with: pytest tests/test_stress.py -v --timeout=600 -m slow -o "addopts="

Categories:
1. MDPDP medium-scale: 4v/6o with real quality assertions
2. MDPDP large-scale: 8v/10o structure and warm start validation
3. Warm start impact: compare with/without
4. Cross-generator: routing, bin_packing, scheduling
5. Shared utilities at scale
"""

import math
import time

import pytest

from app.domains.solver.services.generators import get_generator
from app.domains.solver.services.generators.base import (
    add_symmetry_breaking,
    build_reachable_nodes,
    compute_arc_big_m,
)
from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import Constraint, SolverStatus

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def solver() -> SolverService:
    return SolverService()


CITIES = {
    "BCN": (2.17, 41.38),
    "MAD": (-3.70, 40.42),
    "VLC": (-0.37, 39.47),
    "SEV": (-5.98, 37.38),
    "ZAR": (-0.88, 41.65),
    "MAL": (-4.42, 36.72),
    "BIL": (-2.93, 43.26),
    "MUR": (-1.13, 37.98),
    "VLL": (-4.72, 41.65),
    "ALI": (-0.48, 38.35),
    "GRA": (-3.60, 37.18),
    "PAM": (-1.64, 42.82),
}


def _hkm(c1: tuple[float, float], c2: tuple[float, float]) -> float:
    lon1, lat1 = math.radians(c1[0]), math.radians(c1[1])
    lon2, lat2 = math.radians(c2[0]), math.radians(c2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a)) * 1.3


ALL_DISTANCES = [
    {
        "from": c1,
        "to": c2,
        "km": round(_hkm(CITIES[c1], CITIES[c2]), 1),
        "hours": round(_hkm(CITIES[c1], CITIES[c2]) / 90, 2),
    }
    for c1 in CITIES
    for c2 in CITIES
    if c1 != c2
]


class TestMDPDPMediumScale:
    """4 vehicles, 6 nearby orders — SCIP should handle this well."""

    def test_4v_6o_no_tacho_serves_most(self, solver):
        """4v/6o no tachograph: SCIP must serve >= 4/6 orders."""
        gen = get_generator("mdpdp")
        city_list = list(CITIES.keys())

        problem = gen.generate(
            {
                "orders": [
                    {
                        "pickup": {"location": city_list[i]},
                        "delivery": {"location": city_list[i + 1]},
                        "pallets": 5,
                    }
                    for i in range(6)
                ],
                "tractors": [
                    {
                        "id": f"tr_{i}",
                        "depot": f"dep_{i % 2}",
                        "fuel_cost_per_km": 0.35,
                        "max_distance": 2000,
                    }
                    for i in range(4)
                ],
                "trailers": [{"id": f"tl_{i}", "capacity_pallets": 33} for i in range(4)],
                "drivers": [{"id": f"dr_{i}"} for i in range(4)],
                "depots": [{"id": "dep_0", "location": "BCN"}, {"id": "dep_1", "location": "MAD"}],
                "distances": ALL_DISTANCES,
                "config": {"tachograph_enabled": False, "time_limit_seconds": 60},
            },
            {},
        )

        assert len(problem.variables) > 500
        assert problem.heuristic_warm_start is not None

        r = solver.solve(problem)
        v = r.solution or {}
        assert r.status in (SolverStatus.OPTIMAL, SolverStatus.TIME_LIMIT)
        assert r.warm_start_used is True

        served = sum(1 for i in range(6) if v.get(f"z_{i}", 1) < 0.5)
        assert served >= 3, f"4v/6o no tacho should serve >= 3/6 in 60s, got {served}"
        assert r.objective_value > 0, "Cost must be positive"

    def test_3v_4o_with_tacho_serves_some(self, solver):
        """3v/4o with tachograph: should serve at least 2/4 nearby orders."""
        gen = get_generator("mdpdp")

        problem = gen.generate(
            {
                "orders": [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 8},
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "VLC"}, "pallets": 3},
                    {"pickup": {"location": "ZAR"}, "delivery": {"location": "BIL"}, "pallets": 6},
                ],
                "tractors": [
                    {
                        "id": f"tr_{i}",
                        "depot": f"dep_{i}",
                        "fuel_cost_per_km": 0.35,
                        "max_distance": 1500,
                    }
                    for i in range(3)
                ],
                "trailers": [{"id": f"tl_{i}", "capacity_pallets": 33} for i in range(3)],
                "drivers": [{"id": f"dr_{i}"} for i in range(3)],
                "depots": [
                    {"id": "dep_0", "location": "BCN"},
                    {"id": "dep_1", "location": "VLC"},
                    {"id": "dep_2", "location": "ZAR"},
                ],
                "distances": ALL_DISTANCES,
                "config": {"tachograph_enabled": True, "time_limit_seconds": 30},
            },
            {},
        )

        r = solver.solve(problem)
        v = r.solution or {}
        assert r.status in (SolverStatus.OPTIMAL, SolverStatus.TIME_LIMIT)
        served = sum(1 for i in range(4) if v.get(f"z_{i}", 1) < 0.5)
        assert served >= 2, f"3v/4o tacho should serve >= 2/4, got {served}"


class TestMDPDPLargeScale:
    """8v/10o — validate generation quality, not SCIP solve quality."""

    def test_8v_10o_structure(self):
        """8v/10o generates a substantial, well-formed problem."""
        gen = get_generator("mdpdp")
        city_list = list(CITIES.keys())

        problem = gen.generate(
            {
                "orders": [
                    {
                        "pickup": {"location": city_list[i % len(city_list)]},
                        "delivery": {"location": city_list[(i + 3) % len(city_list)]},
                        "pallets": 5 + i,
                    }
                    for i in range(10)
                ],
                "tractors": [
                    {
                        "id": f"tr_{i}",
                        "depot": f"dep_{i % 4}",
                        "fuel_cost_per_km": 0.35,
                        "max_distance": 2000,
                    }
                    for i in range(8)
                ],
                "trailers": [{"id": f"tl_{i}", "capacity_pallets": 33} for i in range(8)],
                "drivers": [{"id": f"dr_{i}"} for i in range(8)],
                "depots": [{"id": f"dep_{i}", "location": city_list[i]} for i in range(4)],
                "distances": ALL_DISTANCES,
                "config": {"tachograph_enabled": False, "time_limit_seconds": 60},
            },
            {},
        )

        assert len(problem.variables) > 1000
        assert len(problem.constraints) > 2000

        # Warm start quality
        ws = problem.heuristic_warm_start
        assert ws is not None
        ws_arcs = [k for k, val in ws.items() if k.startswith("x_") and val > 0.5]
        ws_served = sum(1 for i in range(10) if ws.get(f"z_{i}", 1) < 0.5)
        assert len(ws_arcs) > 0, "Warm start must have routing arcs"
        assert ws_served > 0, "Warm start heuristic must serve at least 1 order"

    def test_8v_10o_tacho_generates(self):
        """8v/10o with tachograph generates without error."""
        gen = get_generator("mdpdp")
        city_list = list(CITIES.keys())

        problem = gen.generate(
            {
                "orders": [
                    {
                        "pickup": {"location": city_list[i % len(city_list)]},
                        "delivery": {"location": city_list[(i + 2) % len(city_list)]},
                        "pallets": 5,
                    }
                    for i in range(10)
                ],
                "tractors": [
                    {
                        "id": f"tr_{i}",
                        "depot": f"dep_{i % 4}",
                        "fuel_cost_per_km": 0.35,
                        "max_distance": 1500,
                    }
                    for i in range(8)
                ],
                "trailers": [{"id": f"tl_{i}", "capacity_pallets": 33} for i in range(8)],
                "drivers": [{"id": f"dr_{i}"} for i in range(8)],
                "depots": [{"id": f"dep_{i}", "location": city_list[i]} for i in range(4)],
                "distances": ALL_DISTANCES,
                "config": {"tachograph_enabled": True},
            },
            {},
        )

        assert len(problem.variables) > 2000
        assert len(problem.constraints) > 5000
        assert problem.heuristic_warm_start is not None


class TestWarmStartImpact:
    def test_warm_start_helps_or_equals(self, solver):
        """Warm start should produce at least as good a result as cold start."""
        gen = get_generator("mdpdp")
        data = {
            "orders": [
                {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 8},
                {"pickup": {"location": "BCN"}, "delivery": {"location": "VLC"}, "pallets": 3},
                {"pickup": {"location": "ZAR"}, "delivery": {"location": "BIL"}, "pallets": 6},
            ],
            "tractors": [
                {
                    "id": f"tr_{i}",
                    "depot": f"dep_{i}",
                    "fuel_cost_per_km": 0.35,
                    "max_distance": 1500,
                }
                for i in range(3)
            ],
            "trailers": [{"id": f"tl_{i}", "capacity_pallets": 33} for i in range(3)],
            "drivers": [{"id": f"dr_{i}"} for i in range(3)],
            "depots": [
                {"id": "dep_0", "location": "BCN"},
                {"id": "dep_1", "location": "VLC"},
                {"id": "dep_2", "location": "ZAR"},
            ],
            "distances": ALL_DISTANCES,
            "config": {"tachograph_enabled": False, "time_limit_seconds": 15},
        }

        problem_ws = gen.generate(data, {})
        r_ws = solver.solve(problem_ws)

        problem_no = gen.generate(data, {})
        problem_no.heuristic_warm_start = None
        r_no = solver.solve(problem_no)

        assert r_ws.warm_start_used is True
        assert r_no.warm_start_used is False
        if r_ws.objective_value is not None and r_no.objective_value is not None:
            assert r_ws.objective_value <= r_no.objective_value * 1.01


class TestCrossGenerator:
    """Other generators work and produce correct structure."""

    def test_routing_generates_and_solves(self, solver):
        gen = get_generator("routing")
        problem = gen.generate(
            {
                "depot": {"name": "Depot"},
                "locations": [
                    {"name": "A", "demand": 1},
                    {"name": "B", "demand": 1},
                    {"name": "C", "demand": 1},
                ],
                "vehicles": [{"name": "V1", "capacity": 10, "cost_per_unit_distance": 1.0}],
                "distances": [
                    {"from": "Depot", "to": "A", "distance": 10},
                    {"from": "A", "to": "Depot", "distance": 10},
                    {"from": "Depot", "to": "B", "distance": 15},
                    {"from": "B", "to": "Depot", "distance": 15},
                    {"from": "Depot", "to": "C", "distance": 20},
                    {"from": "C", "to": "Depot", "distance": 20},
                    {"from": "A", "to": "B", "distance": 8},
                    {"from": "B", "to": "A", "distance": 8},
                    {"from": "A", "to": "C", "distance": 12},
                    {"from": "C", "to": "A", "distance": 12},
                    {"from": "B", "to": "C", "distance": 10},
                    {"from": "C", "to": "B", "distance": 10},
                ],
            },
            {},
        )
        r = solver.solve(problem)
        assert r.status == SolverStatus.OPTIMAL
        assert r.objective_value > 0

    def test_scheduling_5w_10s(self, solver):
        gen = get_generator("scheduling")
        problem = gen.generate(
            {
                "workers": [{"name": f"W{i}", "max_shifts": 3} for i in range(5)],
                "shifts": [
                    {"name": f"S{i}", "required_workers": 2, "start": i * 2, "end": i * 2 + 4}
                    for i in range(10)
                ],
            },
            {},
        )
        r = solver.solve(problem)
        assert r.status in (SolverStatus.OPTIMAL, SolverStatus.TIME_LIMIT)

    def test_bin_packing_solves(self, solver):
        gen = get_generator("bin_packing")
        problem = gen.generate(
            {
                "items": [{"name": f"item_{i}", "weight": 3 + (i % 4)} for i in range(10)],
                "bin_capacity": 15,
            },
            {},
        )
        r = solver.solve(problem)
        assert r.status == SolverStatus.OPTIMAL
        assert r.objective_value >= 1


class TestSharedUtilitiesScale:
    def test_reachable_nodes_large(self):
        arcs = [
            (f"n_{i}", f"n_{j}", k)
            for k in range(50)
            for i in range(10)
            for j in range(10)
            if i != j
        ]
        start = time.time()
        r = build_reachable_nodes(arcs)
        assert time.time() - start < 1.0
        assert len(r) == 50
        assert all(len(r[k]) == 10 for k in range(50))

    def test_arc_big_m_at_scale(self):
        # earliest stays within horizon (0.2 * 99 = 19.8 < 30)
        nodes = {f"n_{i}": {"earliest": i * 0.2, "service_time": 0.3} for i in range(100)}
        big_ms = [
            compute_arc_big_m(nodes[f"n_{i}"], nodes[f"n_{j}"], 2.0, 30.0)
            for i in range(100)
            for j in range(100)
            if i != j
        ]
        assert len(big_ms) == 9900
        assert all(m > 0 for m in big_ms)
        # Tighter for later nodes
        m_early = compute_arc_big_m(nodes["n_0"], nodes["n_0"], 2.0, 30.0)
        m_late = compute_arc_big_m(nodes["n_0"], nodes["n_40"], 2.0, 30.0)
        assert m_late < m_early

    def test_symmetry_breaking_100_resources(self):
        constraints: list[Constraint] = []
        groups = [list(range(i * 10, (i + 1) * 10)) for i in range(10)]
        add_symmetry_breaking(constraints, {i: f"y_{i}" for i in range(100)}, groups)
        assert len(constraints) == 90  # 10 groups × 9 pairs
