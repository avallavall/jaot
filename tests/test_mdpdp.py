"""
Rigorous tests for the MDPDP-TW-T generator.

Tests cover:
1. Known-answer: analytically verifiable optimal costs
2. Tachograph: break insertion, daily limits, forced breaks
3. Rest stops: automatic insertion on long arcs, route through rest stops
4. Composition: tractor/trailer/driver assignment
5. Edge cases: empty inputs, mismatched resources, NaN inputs
6. Infeasibility: daily driving limit, no feasible vehicle

Every test uses the REAL solver — no mocks.
"""

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


def _base_input(**overrides):
    """Build minimal MDPDP input with sensible defaults."""
    data = {
        "tractors": [
            {"id": "tr1", "depot": "dep1", "fuel_cost_per_km": 0.35, "max_distance": 1500}
        ],
        "trailers": [{"id": "tl1", "capacity_pallets": 33}],
        "drivers": [{"id": "dr1"}],
        "depots": [{"id": "dep1", "location": "BCN"}],
        "config": {"tachograph_enabled": False, "time_limit_seconds": 60},
    }
    data.update(overrides)
    return data


def _solve(solver, gen, user_input):
    """Generate and solve, return (result, solution_dict)."""
    problem = gen.generate(user_input, {})
    result = solver.solve(problem)
    return result, result.solution or {}


class TestMDPDPKnownAnswer:
    """Verify analytically known optimal costs."""

    def test_single_order_round_trip_cost(self, solver, gen):
        """BCN→MAD 620km × 2 × 0.35 EUR/km = 434 EUR."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
                ],
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        assert r.objective_value == pytest.approx(434.0, abs=0.1)

    def test_same_location_pickup_delivery_zero_distance(self, solver, gen):
        """Pickup and delivery at same location = only depot round trip cost."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "BCN"}, "pallets": 1}
                ],
                distances=[],
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        # All arcs are same-location (BCN→BCN), distance=0
        assert r.objective_value == pytest.approx(0.0, abs=0.1)

    def test_two_orders_two_vehicles(self, solver, gen):
        """Each vehicle serves one order from its depot."""
        r, v = _solve(
            solver,
            gen,
            {
                "orders": [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 5},
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
                "depots": [{"id": "dep1", "location": "BCN"}, {"id": "dep2", "location": "VLC"}],
                "distances": [
                    {"from": "BCN", "to": "ZAR", "km": 300, "hours": 3.0},
                    {"from": "ZAR", "to": "BCN", "km": 300, "hours": 3.0},
                    {"from": "VLC", "to": "MAD", "km": 350, "hours": 3.5},
                    {"from": "MAD", "to": "VLC", "km": 350, "hours": 3.5},
                    {"from": "BCN", "to": "VLC", "km": 350, "hours": 3.5},
                    {"from": "VLC", "to": "BCN", "km": 350, "hours": 3.5},
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 4.2},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 4.2},
                    {"from": "ZAR", "to": "VLC", "km": 350, "hours": 3.5},
                    {"from": "VLC", "to": "ZAR", "km": 350, "hours": 3.5},
                    {"from": "ZAR", "to": "MAD", "km": 325, "hours": 3.2},
                    {"from": "MAD", "to": "ZAR", "km": 325, "hours": 3.2},
                ],
                "config": {"tachograph_enabled": False, "time_limit_seconds": 60},
            },
        )
        assert r.status == SolverStatus.OPTIMAL
        unserved = [k for k, val in v.items() if k.startswith("z_") and val > 0.5]
        assert len(unserved) == 0, "Both orders should be served"
        assert r.objective_value > 0, "Cost must be positive with real distances"


class TestMDPDPTachograph:
    """Verify EC 561/2006 tachograph constraint enforcement."""

    def test_short_route_no_break_needed(self, solver, gen):
        """3h each way, 6h total. Each leg < 4.5h → no break needed on legs."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "ZAR", "km": 300, "hours": 3.0},
                    {"from": "ZAR", "to": "BCN", "km": 300, "hours": 3.0},
                ],
                config={"tachograph_enabled": True, "time_limit_seconds": 60},
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        unserved = [k for k, val in v.items() if k.startswith("z_") and val > 0.5]
        assert len(unserved) == 0
        assert r.objective_value == pytest.approx(210.0, abs=0.1)

    def test_medium_route_break_at_delivery(self, solver, gen):
        """3.5h each way, 7h total. Continuous > 4.5h triggers break."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "VLC"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "VLC", "km": 350, "hours": 3.5},
                    {"from": "VLC", "to": "BCN", "km": 350, "hours": 3.5},
                ],
                config={"tachograph_enabled": True, "time_limit_seconds": 60},
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        unserved = [k for k, val in v.items() if k.startswith("z_") and val > 0.5]
        assert len(unserved) == 0
        breaks = [k for k, val in v.items() if k.startswith("brk_") and val > 0.5]
        assert len(breaks) > 0, "Break required for 7h continuous driving"

    def test_daily_limit_blocks_long_round_trip(self, solver, gen):
        """6.5h each way = 13h total > 10h daily limit → unserved."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
                ],
                config={"tachograph_enabled": True, "time_limit_seconds": 60},
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        unserved = [k for k, val in v.items() if k.startswith("z_") and val > 0.5]
        assert len(unserved) == 1, "Order infeasible due to 10h daily limit"

    def test_tacho_disabled_allows_long_route(self, solver, gen):
        """Same 6.5h route without tachograph → served normally."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
                ],
                config={"tachograph_enabled": False, "time_limit_seconds": 60},
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        unserved = [k for k, val in v.items() if k.startswith("z_") and val > 0.5]
        assert len(unserved) == 0
        assert r.objective_value == pytest.approx(434.0, abs=0.1)


class TestMDPDPRestStops:
    """Verify automatic rest-stop insertion on long arcs."""

    def test_5h_arc_gets_rest_stop(self, solver, gen):
        """5h arc (>4h threshold) → rest stop inserted, order served."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAL"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "MAL", "km": 500, "hours": 5.0},
                    {"from": "MAL", "to": "BCN", "km": 500, "hours": 5.0},
                ],
                config={"tachograph_enabled": True, "time_limit_seconds": 60},
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        unserved = [k for k, val in v.items() if k.startswith("z_") and val > 0.5]
        assert len(unserved) == 0, "Order should be served via rest stop"
        # Route must include a rest-stop node
        rst_arcs = [k for k, val in v.items() if k.startswith("x_") and "rst_" in k and val > 0.5]
        assert len(rst_arcs) > 0, "Route must pass through rest stop"

    def test_rest_stop_blocks_direct_arc(self, solver, gen):
        """Direct arc BCN→MAL (5h) must be blocked — only split arcs allowed."""
        problem = gen.generate(
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAL"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "MAL", "km": 500, "hours": 5.0},
                    {"from": "MAL", "to": "BCN", "km": 500, "hours": 5.0},
                ],
                config={"tachograph_enabled": True},
            ),
            {},
        )
        # No direct x_p_0_d_0 arc (BCN→MAL pickup→delivery) should exist
        direct_arcs = [v.name for v in problem.variables if v.name.startswith("x_p_0_d_0")]
        assert len(direct_arcs) == 0, "Direct long arc should be blocked"

    def test_short_arc_no_rest_stop(self, solver, gen):
        """3h arc (< 4h threshold) → no rest stops inserted."""
        problem = gen.generate(
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "ZAR", "km": 300, "hours": 3.0},
                    {"from": "ZAR", "to": "BCN", "km": 300, "hours": 3.0},
                ],
                config={"tachograph_enabled": True},
            ),
            {},
        )
        rst_vars = [v.name for v in problem.variables if "rst_" in v.name]
        assert len(rst_vars) == 0, "No rest stops needed for short arcs"

    def test_4_5h_fast_route_served_with_rest_stops(self, solver, gen):
        """4.5h each way = 9h total ≤ 10h daily with extension → served."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 4.5},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 4.5},
                ],
                config={"tachograph_enabled": True, "time_limit_seconds": 60},
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        unserved = [k for k, val in v.items() if k.startswith("z_") and val > 0.5]
        assert len(unserved) == 0, "9h daily driving feasible with extension"


class TestMDPDPComposition:
    """Verify vehicle composition (tractor + trailer + driver)."""

    def test_composition_assigned_when_vehicle_used(self, solver, gen):
        """Used vehicle must have exactly 1 tractor, 1 trailer, 1 driver."""
        r, v = _solve(
            solver,
            gen,
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "ZAR", "km": 300, "hours": 3.0},
                    {"from": "ZAR", "to": "BCN", "km": 300, "hours": 3.0},
                ],
            ),
        )
        assert r.status == SolverStatus.OPTIMAL
        tractors = [k for k, val in v.items() if k.startswith("atr_") and val > 0.5]
        trailers = [k for k, val in v.items() if k.startswith("atl_") and val > 0.5]
        drivers_assigned = [k for k, val in v.items() if k.startswith("adr_") and val > 0.5]
        assert len(tractors) == 1
        assert len(trailers) == 1
        assert len(drivers_assigned) == 1


class TestMDPDPEdgeCases:
    """Edge cases: validation, empty inputs, NaN."""

    def test_no_orders_raises(self, gen):
        """Empty orders list raises ValueError."""
        with pytest.raises(ValueError, match="orders"):
            gen.generate(_base_input(orders=[]), {})

    def test_mismatched_resources_raises(self, gen):
        """Unequal tractors/trailers/drivers raises ValueError."""
        with pytest.raises(ValueError, match="Mismatched"):
            gen.generate(
                _base_input(
                    tractors=[{"id": "a"}, {"id": "b"}],
                    drivers=[{"id": "c"}],
                    orders=[{"pickup": {"location": "X"}, "delivery": {"location": "Y"}}],
                    distances=[{"from": "X", "to": "Y", "km": 10, "hours": 0.5}],
                ),
                {},
            )

    def test_nan_alpha_raises(self, gen):
        """NaN in config alpha raises ValueError via safe_float."""
        with pytest.raises(ValueError, match="alpha"):
            gen.generate(
                _base_input(
                    orders=[{"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}}],
                    distances=[{"from": "BCN", "to": "MAD", "km": 100, "hours": 1}],
                    config={"alpha": float("nan")},
                ),
                {},
            )

    def test_tachograph_string_false(self, solver, gen):
        """tachograph_enabled='false' (string) should disable tachograph."""
        problem = gen.generate(
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
                ],
                config={"tachograph_enabled": "false"},
            ),
            {},
        )
        # No tachograph variables should exist
        h_vars = [v.name for v in problem.variables if v.name.startswith("h_")]
        assert len(h_vars) == 0, "Tachograph should be disabled with string 'false'"


class TestMDPDPProblemSize:
    """Verify problem generation at different scales."""

    def test_generates_small_problem(self, gen):
        """1 order, 1 vehicle, tachograph disabled: problem size is deterministic."""
        problem = gen.generate(
            _base_input(
                orders=[
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "MAD"}, "pallets": 5}
                ],
                distances=[
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 6.5},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 6.5},
                ],
            ),
            {},
        )
        # Regression anchor for the minimal no-tachograph MDPDP instance.
        assert len(problem.variables) == 18
        assert len(problem.constraints) == 24
        assert problem.objective.expression != "0"

    def test_generates_medium_problem_with_tacho(self, gen):
        """3 orders, 2 vehicles with tachograph: problem size is deterministic."""
        problem = gen.generate(
            {
                "orders": [
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "ZAR"}, "pallets": 5},
                    {"pickup": {"location": "VLC"}, "delivery": {"location": "MAD"}, "pallets": 8},
                    {"pickup": {"location": "BCN"}, "delivery": {"location": "VLC"}, "pallets": 3},
                ],
                "tractors": [
                    {"id": "tr1", "depot": "dep1", "fuel_cost_per_km": 0.35, "max_distance": 1500},
                    {"id": "tr2", "depot": "dep2", "fuel_cost_per_km": 0.32, "max_distance": 1200},
                ],
                "trailers": [
                    {"id": "tl1", "capacity_pallets": 33},
                    {"id": "tl2", "capacity_pallets": 26},
                ],
                "drivers": [{"id": "dr1"}, {"id": "dr2"}],
                "depots": [{"id": "dep1", "location": "BCN"}, {"id": "dep2", "location": "VLC"}],
                "distances": [
                    {"from": "BCN", "to": "ZAR", "km": 300, "hours": 3.0},
                    {"from": "ZAR", "to": "BCN", "km": 300, "hours": 3.0},
                    {"from": "VLC", "to": "MAD", "km": 350, "hours": 3.5},
                    {"from": "MAD", "to": "VLC", "km": 350, "hours": 3.5},
                    {"from": "BCN", "to": "VLC", "km": 350, "hours": 3.5},
                    {"from": "VLC", "to": "BCN", "km": 350, "hours": 3.5},
                    {"from": "BCN", "to": "MAD", "km": 620, "hours": 4.2},
                    {"from": "MAD", "to": "BCN", "km": 620, "hours": 4.2},
                ],
                "config": {"tachograph_enabled": True, "time_limit_seconds": 60},
            },
            {},
        )
        # Regression anchor on exact counts.
        assert len(problem.variables) == 206
        assert len(problem.constraints) == 559
