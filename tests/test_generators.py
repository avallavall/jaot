"""
Tests for parametric base generator system.

Tests cover:
- BaseGenerator.sanitize_name produces valid identifiers
- Each generator produces a valid OptimizationProblem
- GeneratorRegistry maps type strings to generator instances
- Generator params for domain customization
- All 15 generators (9 extracted + 6 new) + GenericGenerator
"""

import pytest

from app.domains.solver.services.generators import get_generator
from app.domains.solver.services.generators.assignment import AssignmentGenerator
from app.domains.solver.services.generators.base import (
    GeneratorRegistry,
    GenericGenerator,
)
from app.domains.solver.services.generators.bin_packing import BinPackingGenerator
from app.domains.solver.services.generators.blending import BlendingGenerator
from app.domains.solver.services.generators.covering import CoveringGenerator
from app.domains.solver.services.generators.cutting_stock import CuttingStockGenerator
from app.domains.solver.services.generators.facility_location import FacilityLocationGenerator
from app.domains.solver.services.generators.knapsack import KnapsackGenerator
from app.domains.solver.services.generators.lot_sizing import LotSizingGenerator
from app.domains.solver.services.generators.network_flow import NetworkFlowGenerator
from app.domains.solver.services.generators.portfolio import PortfolioGenerator
from app.domains.solver.services.generators.procurement import ProcurementGenerator
from app.domains.solver.services.generators.production import ProductionGenerator
from app.domains.solver.services.generators.routing import RoutingGenerator
from app.domains.solver.services.generators.scheduling import SchedulingGenerator
from app.domains.solver.services.generators.set_cover import SetCoverGenerator
from app.schemas.optimization import (
    ObjectiveSense,
    OptimizationProblem,
    VariableType,
)


def _assert_valid_problem(problem: OptimizationProblem) -> None:
    """Assert that a generated problem has valid structure."""
    assert isinstance(problem, OptimizationProblem)
    assert len(problem.variables) > 0
    assert problem.objective is not None
    assert problem.objective.expression != ""
    assert problem.objective.sense in (ObjectiveSense.MINIMIZE, ObjectiveSense.MAXIMIZE)
    names = [v.name for v in problem.variables]
    assert len(names) == len(set(names)), f"Duplicate variable names: {names}"
    for v in problem.variables:
        assert v.name.replace("_", "").isalnum(), f"Invalid var name: {v.name}"
        assert not v.name[0].isdigit(), f"Var name starts with digit: {v.name}"


class TestBaseGeneratorSanitizeName:
    def test_spaces_become_underscores(self) -> None:
        gen = GenericGenerator()
        assert gen.sanitize_name("hello world") == "hello_world"

    def test_special_chars_replaced(self) -> None:
        gen = GenericGenerator()
        assert gen.sanitize_name("cafe-latte!") == "cafe_latte_"

    def test_digit_prefix_gets_v_prefix(self) -> None:
        gen = GenericGenerator()
        result = gen.sanitize_name("1st_place")
        assert result.startswith("v_")

    def test_produces_valid_identifier(self) -> None:
        gen = GenericGenerator()
        for name in ["Hello World", "99 problems", "a+b=c", "  spaces  ", "MixedCase"]:
            result = gen.sanitize_name(name)
            assert result.replace("_", "").isalnum() or result == ""
            if result:
                assert not result[0].isdigit()


class TestGeneratorRegistry:
    def test_get_assignment_returns_assignment_generator(self) -> None:
        gen = GeneratorRegistry.get("assignment")
        assert isinstance(gen, AssignmentGenerator)

    def test_get_unknown_returns_generic_generator(self) -> None:
        gen = GeneratorRegistry.get("unknown_type_xyz")
        assert isinstance(gen, GenericGenerator)

    def test_get_generator_convenience_function(self) -> None:
        gen = get_generator("knapsack")
        assert isinstance(gen, KnapsackGenerator)

    def test_all_expected_generators_registered(self) -> None:
        expected = {
            "assignment",
            "scheduling",
            "routing",
            "blending",
            "knapsack",
            "production",
            "portfolio",
            "bin_packing",
            "budget_allocation",
            "generic",
            "covering",
            "network_flow",
            "facility_location",
            "cutting_stock",
            "set_cover",
            "lot_sizing",
        }
        for name in expected:
            gen = GeneratorRegistry.get(name)
            assert not isinstance(gen, GenericGenerator) or name == "generic", (
                f"Generator '{name}' not registered (got GenericGenerator fallback)"
            )


class TestAssignmentGenerator:
    def test_produces_binary_variables_for_worker_task_pairs(self) -> None:
        gen = AssignmentGenerator()
        user_input = {
            "workers": [{"name": "Alice"}, {"name": "Bob"}],
            "tasks": [{"name": "T1"}, {"name": "T2"}],
            "costs": {"alice_t1": 5, "alice_t2": 3, "bob_t1": 7, "bob_t2": 2},
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        assert len(problem.variables) == 4
        assert all(v.type == VariableType.BINARY for v in problem.variables)


class TestSchedulingGenerator:
    def test_produces_shift_coverage_constraints(self) -> None:
        gen = SchedulingGenerator()
        user_input = {
            "employees": [
                {"name": "Alice", "hourly_cost": 25, "max_hours": 40},
                {"name": "Bob", "hourly_cost": 22, "max_hours": 40},
            ],
            "shifts": [
                {"name": "morning", "duration_hours": 8, "min_employees": 1, "max_employees": 2},
                {"name": "evening", "duration_hours": 8, "min_employees": 1},
            ],
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        coverage = [c for c in problem.constraints if c.name and "min_cover" in c.name]
        assert len(coverage) == 2

    # CONTRACT-TEST: a single-list input schedules the list, never assigns it to itself.
    def test_single_list_input_routes_to_task_scheduling(self) -> None:
        """Measured before the fix: six shipped templates (stands, blocks, trial
        phases…) fed the SAME list to both roles through the employee fallback
        and served an X-assigned-to-X model that answered nothing the card asked."""
        problem = SchedulingGenerator().generate(
            {
                "stands": [{"name": "S1"}, {"name": "S2"}, {"name": "S3"}],
                "num_periods": 4,
            },
            {},
        )
        _assert_valid_problem(problem)
        assert problem.name == "task_scheduling"
        # The self-assignment disease had variables like s1_s2.
        names = {v.name for v in problem.variables}
        assert "s1_s2" not in names
        assert "start_s1" in names

    def test_task_scheduling_honors_crews_and_prerequisites(self) -> None:
        """The renovation card promises three crews and dependency order. The
        old model wrote neither — its only resource row was a fabricated
        'sum of starts' bound — so it answered 'everything starts at once,
        done in 5 days'. The true optimum is 10: the critical path is 9 and
        the three-crew limit costs one more day."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        tasks = [
            {"name": "Demo-A", "duration": 3, "prerequisites": []},
            {"name": "Plumbing-A", "duration": 4, "prerequisites": ["Demo-A"]},
            {"name": "Electrical-A", "duration": 3, "prerequisites": ["Demo-A"]},
            {"name": "Painting-A", "duration": 2, "prerequisites": ["Plumbing-A", "Electrical-A"]},
            {"name": "Demo-B", "duration": 2, "prerequisites": []},
            {"name": "Plumbing-B", "duration": 5, "prerequisites": ["Demo-B"]},
            {"name": "Flooring-B", "duration": 3, "prerequisites": ["Demo-B"]},
            {"name": "Painting-B", "duration": 2, "prerequisites": ["Plumbing-B", "Flooring-B"]},
        ]
        problem = SchedulingGenerator().generate(
            {"tasks": tasks, "num_crews": 3, "time_horizon": 15}, {}
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        assert result.objective_value == pytest.approx(10.0)

        def norm(raw: str) -> str:
            return raw.lower().replace("-", "_")

        starts = {
            k[len("start_") :]: v for k, v in result.solution.items() if k.startswith("start_")
        }
        durations = {norm(t["name"]): t["duration"] for t in tasks}
        for task in tasks:
            for prereq in task["prerequisites"]:
                assert (
                    starts[norm(task["name"])]
                    >= starts[norm(prereq)] + durations[norm(prereq)] - 1e-6
                ), f"{task['name']} starts before its prerequisite {prereq} finishes"
        # The three-crew limit is real: no period runs more than three tasks.
        for t in range(15):
            active = sum(
                1
                for name, duration in durations.items()
                if starts[name] <= t < starts[name] + duration
            )
            assert active <= 3, f"period {t} runs {active} tasks with 3 crews"


class TestRoutingGenerator:
    def test_produces_mtz_subtour_elimination(self) -> None:
        gen = RoutingGenerator()
        user_input = {
            "depot": {"name": "depot"},
            "locations": [
                {"name": "A", "demand": 3},
                {"name": "B", "demand": 5},
            ],
            "vehicles": [{"name": "truck1", "capacity": 10, "cost_per_unit_distance": 1.0}],
            "distances": {
                "depot_a": 10,
                "depot_b": 20,
                "a_depot": 10,
                "b_depot": 20,
                "a_b": 15,
                "b_a": 15,
            },
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        mtz = [c for c in problem.constraints if c.name and "mtz_" in c.name]
        assert len(mtz) > 0

    @staticmethod
    def _all_pairs_distances(nodes: list[str], distance: float = 10) -> list[dict]:
        return [{"from": i, "to": j, "distance": distance} for i in nodes for j in nodes if i != j]

    # CONTRACT-TEST: a mixed fleet is not capped by its smallest vehicle.
    def test_heterogeneous_fleet_stays_feasible(self) -> None:
        """Measured before the fix: three customers of demand 6 and a cap-100
        truck went INFEASIBLE the moment an idle cap-6 van existed in the fleet.
        The shared-u MTZ rows used each vehicle's OWN capacity as big-M, so on
        x=0 pairs the smallest vehicle's rows capped every route in the model.
        """
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = RoutingGenerator().generate(
            {
                "depot": {"name": "depot"},
                "locations": [
                    {"name": "A", "demand": 6},
                    {"name": "B", "demand": 6},
                    {"name": "C", "demand": 6},
                ],
                "vehicles": [
                    {"name": "big", "capacity": 100, "cost_per_unit_distance": 1.0},
                    {"name": "small", "capacity": 6, "cost_per_unit_distance": 1.0},
                ],
                "distances": self._all_pairs_distances(["depot", "A", "B", "C"]),
            },
            {},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal", (
            f"a cap-100 truck can serve 18 units of demand; got {result.status}"
        )
        # One route of four arcs at distance 10: the truck takes all three.
        assert result.objective_value == pytest.approx(40.0)

    def test_each_vehicle_held_to_its_own_capacity(self) -> None:
        """The cheap cap-10 van must not carry 100 units of demand. Before the
        fix nothing enforced a vehicle's own capacity — u is bounded by the
        fleet-wide max — so the tempting-but-illegal answer cost 3.0."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = RoutingGenerator().generate(
            {
                "depot": {"name": "depot"},
                "locations": [{"name": "A", "demand": 50}, {"name": "B", "demand": 50}],
                "vehicles": [
                    {"name": "big", "capacity": 100, "cost_per_unit_distance": 1.0},
                    {"name": "small", "capacity": 10, "cost_per_unit_distance": 0.1},
                ],
                "distances": self._all_pairs_distances(["depot", "A", "B"]),
            },
            {},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        assert result.objective_value == pytest.approx(30.0), (
            "the only legal answer is the big truck taking both stops"
        )
        small_arcs = [
            name
            for name, value in (result.solution or {}).items()
            if name.startswith("x_small_") and value > 0.5
        ]
        assert small_arcs == [], f"the cap-10 van carried demand: {small_arcs}"


class TestBlendingGenerator:
    def test_produces_nutrient_constraints(self) -> None:
        gen = BlendingGenerator()
        user_input = {
            "nutrients": [{"id": "N"}],
            "raw_materials": [
                {
                    "id": "urea",
                    "price_per_ton": 300,
                    "nutrient_percentages": [{"id": "N", "percentage": 46}],
                },
                {
                    "id": "dap",
                    "price_per_ton": 500,
                    "nutrient_percentages": [{"id": "N", "percentage": 18}],
                },
            ],
            "target_nutrients": [{"id": "N", "min": 20, "max": 30}],
            "mix_quantity_min": 100,
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        nutrient_constraints = [
            c for c in problem.constraints if c.name and ("min_N" in c.name or "max_N" in c.name)
        ]
        assert len(nutrient_constraints) >= 1


class TestKnapsackGenerator:
    def test_produces_capacity_constraint(self) -> None:
        gen = KnapsackGenerator()
        user_input = {
            "items": [
                {"name": "gem", "value": 100, "weight": 5},
                {"name": "ring", "value": 80, "weight": 3},
            ],
            "capacity": 7,
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        cap = [c for c in problem.constraints if c.name == "capacity"]
        assert len(cap) == 1
        assert "<=" in cap[0].expression


class TestProductionGenerator:
    def test_produces_resource_constraints(self) -> None:
        gen = ProductionGenerator()
        user_input = {
            "products": [
                {"name": "widget", "profit_per_unit": 10, "max_production": 100},
            ],
            "resources": [
                {"name": "material", "available": 500, "usage": {"widget": 5}},
            ],
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        resource_constraints = [c for c in problem.constraints if c.name == "material"]
        assert len(resource_constraints) == 1


class TestPortfolioGenerator:
    def test_produces_budget_and_risk_constraints(self) -> None:
        gen = PortfolioGenerator()
        user_input = {
            "assets": [
                {"name": "stocks", "expected_return": 0.10, "risk": 0.15, "max_allocation": 0.6},
                {"name": "bonds", "expected_return": 0.03, "risk": 0.04, "max_allocation": 0.8},
            ],
            "total_budget": 100000,
            "max_risk": 0.12,
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        budget = [c for c in problem.constraints if c.name == "budget"]
        assert len(budget) == 1
        risk = [c for c in problem.constraints if c.name == "max_risk"]
        assert len(risk) == 1


class TestBinPackingGenerator:
    def test_produces_capacity_and_symmetry_constraints(self) -> None:
        gen = BinPackingGenerator()
        user_input = {
            "items": [
                {"name": "item_1", "size": 40},
                {"name": "item_2", "size": 30},
                {"name": "item_3", "size": 50},
            ],
            "bin_capacity": 100,
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        cap = [c for c in problem.constraints if c.name and "capacity" in c.name]
        assert len(cap) > 0
        sym = [c for c in problem.constraints if c.name and "symmetry" in c.name]
        assert len(sym) > 0


class TestGenericGenerator:
    def test_validates_required_fields(self) -> None:
        gen = GenericGenerator()
        user_input = {
            "name": "test",
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
            "objective": {"sense": "maximize", "expression": "x"},
            "constraints": [{"expression": "x <= 10"}],
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)

    def test_missing_variables_raises_error(self) -> None:
        gen = GenericGenerator()
        user_input = {"name": "bad", "objective": {"sense": "maximize", "expression": "x"}}
        with pytest.raises(ValueError, match="variables"):
            gen.generate(user_input, {})

    def test_missing_objective_raises_error(self) -> None:
        gen = GenericGenerator()
        user_input = {
            "name": "bad",
            "variables": [{"name": "x", "type": "continuous"}],
        }
        with pytest.raises(ValueError, match="objective"):
            gen.generate(user_input, {})


class TestCoveringGenerator:
    def test_produces_set_covering_constraints(self) -> None:
        gen = CoveringGenerator()
        user_input = {
            "sets": [
                {"name": "s1", "cost": 10, "covers": [0, 1]},
                {"name": "s2", "cost": 15, "covers": [1, 2]},
                {"name": "s3", "cost": 8, "covers": [0, 2]},
            ],
            "num_elements": 3,
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        cover = [c for c in problem.constraints if c.name and "cover_" in c.name]
        assert len(cover) == 3  # one per element
        assert problem.objective.sense == ObjectiveSense.MINIMIZE


class TestNetworkFlowGenerator:
    def test_produces_flow_conservation_constraints(self) -> None:
        gen = NetworkFlowGenerator()
        user_input = {
            "nodes": [
                {"name": "source", "supply": 10},
                {"name": "mid", "supply": 0},
                {"name": "sink", "supply": -10},
            ],
            "arcs": [
                {"from": "source", "to": "mid", "cost": 2, "capacity": 15},
                {"from": "mid", "to": "sink", "cost": 3, "capacity": 15},
            ],
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        flow = [c for c in problem.constraints if c.name and "flow_" in c.name]
        assert len(flow) == 3  # one per node
        assert problem.objective.sense == ObjectiveSense.MINIMIZE


class TestFacilityLocationGenerator:
    def test_produces_facility_assignment_and_capacity_constraints(self) -> None:
        gen = FacilityLocationGenerator()
        user_input = {
            "facilities": [
                {"name": "f1", "fixed_cost": 100, "capacity": 50},
                {"name": "f2", "fixed_cost": 150, "capacity": 80},
            ],
            "customers": [
                {"name": "c1", "demand": 20},
                {"name": "c2", "demand": 30},
            ],
            "transport_costs": {
                "f1_c1": 5,
                "f1_c2": 8,
                "f2_c1": 7,
                "f2_c2": 3,
            },
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        # Demand constraints
        demand = [c for c in problem.constraints if c.name and "demand_" in c.name]
        assert len(demand) == 2
        # Capacity constraints
        cap = [c for c in problem.constraints if c.name and "capacity_" in c.name]
        assert len(cap) == 2


class TestCuttingStockGenerator:
    def test_produces_pattern_based_cutting_constraints(self) -> None:
        gen = CuttingStockGenerator()
        user_input = {
            "stock_length": 100,
            "items": [
                {"name": "small", "length": 30, "demand": 5},
                {"name": "medium", "length": 45, "demand": 3},
            ],
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        demand = [c for c in problem.constraints if c.name and "demand_" in c.name]
        assert len(demand) >= 2


class TestSetCoverGenerator:
    def test_produces_coverage_constraints(self) -> None:
        gen = SetCoverGenerator()
        user_input = {
            "sets": [
                {"name": "s1", "cost": 10, "elements": ["a", "b"]},
                {"name": "s2", "cost": 15, "elements": ["b", "c"]},
                {"name": "s3", "cost": 12, "elements": ["a", "c"]},
            ],
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        cover = [c for c in problem.constraints if c.name and "cover_" in c.name]
        assert len(cover) == 3  # a, b, c
        assert problem.objective.sense == ObjectiveSense.MINIMIZE


class TestLotSizingGenerator:
    def test_produces_setup_costs_and_inventory_balance(self) -> None:
        gen = LotSizingGenerator()
        user_input = {
            "periods": 3,
            "demand": [10, 20, 15],
            "production_cost": 5,
            "setup_cost": 50,
            "holding_cost": 2,
            "capacity": 30,
        }
        problem = gen.generate(user_input, {})
        _assert_valid_problem(problem)
        balance = [c for c in problem.constraints if c.name and "balance_" in c.name]
        assert len(balance) == 3  # one per period
        setup = [c for c in problem.constraints if c.name and "setup_" in c.name]
        assert len(setup) == 3  # one per period

    def test_setup_link_uses_remaining_demand_not_total(self) -> None:
        """Producing more than the demand still ahead is never useful, so the
        setup big-M declines with the horizon instead of sitting at total
        demand for every period. Measured on 24 periods: root LP bound
        3675 → 5968 at the identical MIP optimum — same rows, tighter model."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = LotSizingGenerator().generate(
            {
                "periods": 3,
                "demand": [10, 20, 30],
                "production_cost": 1,
                "setup_cost": 100,
                "holding_cost": 1,
            },
            {},
        )
        links = {
            c.name: c.expression for c in problem.constraints if "setup_link" in (c.name or "")
        }
        assert "60" in links["setup_link_0"]  # full remaining demand
        assert "50" in links["setup_link_1"]  # 20 + 30 still ahead
        assert "30" in links["setup_link_2"]  # only the last period's demand

        # The tightening must not move the optimum: produce 30 at t0 and 30 at
        # t2 → two setups (200) + production (60) + holding (20) = 280? No —
        # produce all 60 at t0 is cheaper: 100 + 60 + (50+30) = 240.
        result = SCIPAdapter().solve(problem)
        assert result.status.value == "optimal"
        assert result.objective_value == pytest.approx(240.0)


class TestBlendingCardFormats:
    """The three blending cards that answered an optimal cost of 0.

    Their costs (cost_per_liter / cost_per_tonne) went unread — buying was
    free — and their batch/tonnage target only capped the mix, so producing
    NOTHING satisfied every ratio spec.
    """

    def test_ore_style_input_produces_a_real_blend(self) -> None:
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = BlendingGenerator().generate(
            {
                "sources": [
                    {"name": "cheap", "cost_per_tonne": 10, "composition": {"iron": 58.0}},
                    {"name": "rich", "cost_per_tonne": 15, "composition": {"iron": 65.0}},
                ],
                "quality_specs": [{"parameter": "iron", "min_value": 62.0}],
                "target_tonnage": 100,
            },
            {},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        # Blend 100 t at iron >= 62: 4/7 rich + 3/7 cheap
        # -> cost 10*(300/7) + 15*(400/7) = 9000/7.
        assert result.objective_value == pytest.approx(9000 / 7, rel=1e-6)
        total = result.solution["cheap"] + result.solution["rich"]
        assert total == pytest.approx(100.0)

    def test_nutrients_dict_and_per_kg_specs_are_read(self) -> None:
        problem = BlendingGenerator().generate(
            {
                "ingredients": [
                    {"name": "flour", "cost_per_kg": 1, "nutrients": {"protein": 10.0}},
                    {"name": "whey", "cost_per_kg": 6, "nutrients": {"protein": 80.0}},
                ],
                "specifications": [{"nutrient": "protein", "min_per_kg": 12.0}],
                "batch_size": 50,
            },
            {},
        )
        names = {c.name for c in problem.constraints}
        assert "min_protein" in names, "the per-kg spec produced no constraint"
        assert "mix_quantity_min" in names, "the batch size does not force production"


class TestNetworkFlowNodeLists:
    def test_supply_lists_survive_a_preferred_arc_key(self) -> None:
        """`routes` matched a preferred arc key, and the depot/mill lists were
        then thrown away: every node got supply 0 and the optimal flow was to
        move nothing (measured: the timber card answered cost 0). A surplus at
        the sources must also not make the model infeasible — sources may keep
        what nobody demands."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = NetworkFlowGenerator().generate(
            {
                "depots": [
                    {"name": "north", "supply": 60},
                    {"name": "south", "supply": 50},
                ],
                "mills": [{"name": "mill", "demand": 80}],
                "routes": [
                    {"from_depot": "north", "to_mill": "mill", "cost_per_m3": 1, "capacity": 100},
                    {"from_depot": "south", "to_mill": "mill", "cost_per_m3": 2, "capacity": 100},
                ],
            },
            {},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        # All 60 cheap units, then 20 expensive ones: 60*1 + 20*2.
        assert result.objective_value == pytest.approx(100.0)


class TestLotSizingMultiItem:
    def test_sku_lists_build_a_real_multi_item_model(self) -> None:
        """SKU-list inputs fell through to the single-item reader, which found
        no top-level demand and served a one-period model of nothing — two
        shipped cards answered an optimal cost of 0."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = LotSizingGenerator().generate(
            {
                "skus": [
                    {
                        "name": "hub",
                        "demand": [20, 30],
                        "ordering_cost": 100,
                        "unit_cost": 2,
                        "holding_cost": 1,
                    },
                    {
                        "name": "stand",
                        "demand": [10, 10],
                        "ordering_cost": 50,
                        "unit_cost": 5,
                        "holding_cost": 1,
                    },
                ],
                "num_periods": 2,
            },
            {},
        )
        assert problem.name == "multi_item_lot_sizing"
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        # hub: one order of 50 (100 + 100 + holding 30) beats two orders (300).
        # stand: one order of 20 (50 + 100 + 10) beats two (250).
        assert result.objective_value == pytest.approx(230.0 + 160.0)

    def test_reactor_limit_couples_the_items(self) -> None:
        problem = LotSizingGenerator().generate(
            {
                "products": [
                    {"name": "a", "demand": [10, 10], "setup_cost": 1},
                    {"name": "b", "demand": [10, 10], "setup_cost": 1},
                    {"name": "c", "demand": [0, 10], "setup_cost": 1},
                ],
                "num_periods": 2,
                "num_reactors": 2,
            },
            {},
        )
        reactor_rows = [c for c in problem.constraints if c.name and c.name.startswith("reactors_")]
        assert len(reactor_rows) == 2, "one shared-lines row per period"
        assert all("<= 2" in c.expression for c in reactor_rows)


class TestPeriodSelectionGenerator:
    """The honest model behind the harvest/mine/track cards, which used to be
    served as an X-assigned-to-X scheduling model or an empty makespan."""

    def test_select_mode_respects_precedence_capacity_and_grade(self) -> None:
        from app.domains.solver.adapters.scip import SCIPAdapter
        from app.domains.solver.services.generators.period_selection import (
            PeriodSelectionGenerator,
        )

        problem = PeriodSelectionGenerator().generate(
            {
                "blocks": [
                    {"name": "top", "tonnage": 60, "grade": 2.5, "value": 100},
                    {
                        "name": "deep",
                        "tonnage": 60,
                        "grade": 3.0,
                        "value": 500,
                        "requires": ["top"],
                    },
                    {"name": "lean", "tonnage": 60, "grade": 1.0, "value": 400},
                ],
                "num_periods": 2,
                "plant_capacity": 60,
                "min_grade": 2.0,
            },
            {},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        # Only one block fits per period. The lean block (grade 1.0) can never
        # meet the 2.0 floor alone, so the best plan is top in p1, deep in p2:
        # 100 + 500 = 600 — even though lean alone is worth 400.
        assert result.objective_value == pytest.approx(600.0)
        assert result.solution["x_top_p1"] == pytest.approx(1.0)
        assert result.solution["x_deep_p2"] == pytest.approx(1.0)

    def test_assign_mode_fits_every_item_before_its_deadline(self) -> None:
        from app.domains.solver.adapters.scip import SCIPAdapter
        from app.domains.solver.services.generators.period_selection import (
            PeriodSelectionGenerator,
        )

        problem = PeriodSelectionGenerator().generate(
            {
                "sections": [
                    {
                        "name": "urgent",
                        "duration_hours": 8,
                        "deadline_day": 5,
                        "trains_affected": 30,
                    },
                    {
                        "name": "later",
                        "duration_hours": 6,
                        "deadline_day": 20,
                        "trains_affected": 5,
                    },
                ],
                "maintenance_windows": [
                    {"day": 3, "duration_hours": 8},
                    {"day": 10, "duration_hours": 8},
                ],
            },
            {"mode": "assign"},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        # urgent (deadline day 5) can only take the day-3 window; later lands
        # on day 10. Objective: 30*3 + 5*10.
        assert result.objective_value == pytest.approx(140.0)

    def test_assign_mode_refuses_an_impossible_deadline(self) -> None:
        from app.domains.solver.services.generators.period_selection import (
            PeriodSelectionGenerator,
        )

        with pytest.raises(ValueError, match="no admissible period"):
            PeriodSelectionGenerator().generate(
                {
                    "sections": [{"name": "s", "duration_hours": 4, "deadline_day": 2}],
                    "maintenance_windows": [{"day": 9, "duration_hours": 8}],
                },
                {"mode": "assign"},
            )


class TestNetworkDesignGenerator:
    def test_two_edge_connectivity_needs_the_whole_triangle(self) -> None:
        """A triangle is the smallest 2-edge-connected graph: dropping any edge
        leaves a bridge, so all three must be bought."""
        from app.domains.solver.adapters.scip import SCIPAdapter
        from app.domains.solver.services.generators.network_design import (
            NetworkDesignGenerator,
        )

        problem = NetworkDesignGenerator().generate(
            {
                "nodes": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
                "candidate_edges": [
                    {"from_node": "a", "to_node": "b", "cost": 10},
                    {"from_node": "b", "to_node": "c", "cost": 20},
                    {"from_node": "a", "to_node": "c", "cost": 30},
                ],
                "min_paths": 2,
            },
            {},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        assert result.objective_value == pytest.approx(60.0)

    def test_a_cheap_detour_beats_an_expensive_direct_edge(self) -> None:
        from app.domains.solver.adapters.scip import SCIPAdapter
        from app.domains.solver.services.generators.network_design import (
            NetworkDesignGenerator,
        )

        problem = NetworkDesignGenerator().generate(
            {
                "nodes": [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}],
                "candidate_edges": [
                    {"from_node": "a", "to_node": "b", "cost": 10},
                    {"from_node": "b", "to_node": "c", "cost": 10},
                    {"from_node": "c", "to_node": "d", "cost": 10},
                    {"from_node": "d", "to_node": "a", "cost": 10},
                    {"from_node": "a", "to_node": "c", "cost": 100},
                ],
                "min_paths": 2,
            },
            {},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        # The 4-cycle (cost 40) is 2-edge-connected; the 100-cost chord stays out.
        assert result.objective_value == pytest.approx(40.0)
        assert result.solution.get("e_a_c", 0) == pytest.approx(0.0)


class TestNetworkFlowMaxFlowMode:
    def test_maximizes_flow_instead_of_verifying_it(self) -> None:
        """The shipped card had zero costs and supplies equal to the known
        answer, so min-cost mode merely verified a flow of that value and
        answered an optimal cost of 0. In max_flow mode the objective IS the
        flow value, proven by the solver."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = NetworkFlowGenerator().generate(
            {
                "nodes": [
                    {"id": "s", "supply": 100},
                    {"id": "a", "supply": 0},
                    {"id": "b", "supply": 0},
                    {"id": "t", "supply": -100},
                ],
                "arcs": [
                    {"from": "s", "to": "a", "cost": 0, "capacity": 5},
                    {"from": "s", "to": "b", "cost": 0, "capacity": 3},
                    {"from": "a", "to": "t", "cost": 0, "capacity": 4},
                    {"from": "b", "to": "t", "cost": 0, "capacity": 5},
                ],
            },
            {"mode": "max_flow"},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        assert problem.name == "max_flow"
        # min(5,4) + min(3,5) = 7, well under the loose 100 caps.
        assert result.objective_value == pytest.approx(7.0)


class TestCuttingStockPatternEnumeration:
    def test_mixed_patterns_beat_the_old_pair_shapes(self) -> None:
        """The old set (single-item patterns plus one arbitrary pair shape)
        could not cut A+B+C from one stock, so this instance needed 3 stocks;
        the full maximal-pattern set does it in 2."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = CuttingStockGenerator().generate(
            {
                "stock_length": 10,
                "items": [
                    {"name": "A", "length": 5, "demand": 2},
                    {"name": "B", "length": 3, "demand": 2},
                    {"name": "C", "length": 2, "demand": 2},
                ],
            },
            {},
        )
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        assert result.objective_value == pytest.approx(2.0)
        assert "truncated" not in (problem.description or "")


class TestCoveringUncoverable:
    def test_an_element_no_set_covers_is_an_error_not_a_silent_pass(self) -> None:
        """It used to be skipped, and the answer came back optimal with the
        element uncovered — the one thing a covering model exists to prevent."""
        with pytest.raises(ValueError, match="No set covers"):
            CoveringGenerator().generate(
                {
                    "sets": [{"name": "s1", "cost": 1, "covers": [0, 1]}],
                    "num_elements": 3,  # element 2 appears in no set
                },
                {},
            )


class TestSchedulingLineAssignment:
    def test_lines_are_resources_with_their_hour_budgets(self) -> None:
        """The production-line card ships lines with available_hours and orders
        with production_hours; both went unread — lines were not a recognized
        resource list, budgets defaulted to 40 and durations to 8."""
        from app.domains.solver.adapters.scip import SCIPAdapter

        problem = SchedulingGenerator().generate(
            {
                "orders": [
                    {"name": "o1", "production_hours": 6},
                    {"name": "o2", "production_hours": 6},
                    {"name": "o3", "production_hours": 6},
                ],
                "lines": [
                    {"name": "l1", "available_hours": 12},
                    {"name": "l2", "available_hours": 12},
                ],
            },
            {},
        )
        assert problem.name == "employee_scheduling"
        result = SCIPAdapter().solve(problem)

        assert result.status.value == "optimal"
        # 18 hours of work at the default rate of 20 — and no line over 12h,
        # which forces a 2+1 split (all three on one line would need 18h).
        assert result.objective_value == pytest.approx(360.0)


class TestProcurementGenerator:
    def test_material_and_supplier_rows_do_not_alias_by_name(self) -> None:
        """Rows were built by name prefix/suffix matching, so material "steel"
        also swallowed every "…_stainless_steel" variable and a supplier's cap
        row swallowed any supplier whose name extends it. Bookkeeping is now
        explicit per (supplier, material) pair."""
        problem = ProcurementGenerator().generate(
            {
                "suppliers": [
                    {
                        "name": "acme",
                        "pricing": {"steel": 1, "stainless_steel": 1},
                        "max_total_supply": 100,
                    },
                    {"name": "acme_2", "pricing": {"steel": 1, "stainless_steel": 1}},
                ],
                "materials": [
                    {"name": "steel", "demand": 10},
                    {"name": "stainless_steel", "demand": 5},
                ],
            },
            {},
        )
        rows = {c.name: c.expression for c in problem.constraints}

        assert "stainless" not in rows["demand_steel"], (
            "buying stainless steel must not satisfy the steel demand"
        )
        assert "acme_2" not in rows["cap_acme"], (
            "acme_2's purchases must not consume acme's capacity"
        )
        # And the rows still hold their own pairs.
        assert "acme_steel" in rows["demand_steel"]
        assert "acme_2_steel" in rows["demand_steel"]


class TestTemplateEngineRegistryDispatch:
    """Test that TemplateEngine dispatches to correct generator via registry."""

    def test_dispatches_to_assignment_generator(self) -> None:
        from app.domains.solver.services.template_engine import TemplateEngine

        engine = TemplateEngine()
        template = {"generator": "assignment"}
        user_input = {
            "workers": [{"name": "A"}, {"name": "B"}],
            "tasks": [{"name": "T1"}],
            "costs": {},
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.name == "assignment"

    def test_dispatches_to_knapsack_generator(self) -> None:
        from app.domains.solver.services.template_engine import TemplateEngine

        engine = TemplateEngine()
        template = {"generator": "knapsack"}
        user_input = {
            "items": [{"name": "gem", "value": 100, "weight": 5}],
            "capacity": 10,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.name == "knapsack"

    def test_passes_generator_params_from_template(self) -> None:
        from app.domains.solver.services.template_engine import TemplateEngine

        engine = TemplateEngine()
        template = {
            "generator": "assignment",
            "generator_params": {"description": "Custom from template"},
        }
        user_input = {
            "workers": [{"name": "A"}],
            "tasks": [{"name": "T1"}],
            "costs": {},
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)

    def test_backward_compat_employee_scheduling(self) -> None:
        from app.domains.solver.services.template_engine import TemplateEngine

        engine = TemplateEngine()
        template = {"generator": "employee_scheduling"}
        user_input = {
            "employees": [{"name": "A", "hourly_cost": 20, "max_hours": 40}],
            "shifts": [{"name": "s1", "duration_hours": 8, "min_employees": 1}],
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.name == "employee_scheduling"

    def test_backward_compat_fertilizer(self) -> None:
        from app.domains.solver.services.template_engine import TemplateEngine

        engine = TemplateEngine()
        template = {"generator": "fertilizer"}
        user_input = {
            "raw_materials": [
                {"id": "rm1", "price_per_ton": 100, "nutrient_percentages": []},
            ],
            "target_nutrients": [],
            "mix_quantity_min": 10,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)

    def test_new_generator_covering_via_engine(self) -> None:
        from app.domains.solver.services.template_engine import TemplateEngine

        engine = TemplateEngine()
        template = {"generator": "covering"}
        user_input = {
            "sets": [{"name": "s1", "cost": 5, "covers": [0]}],
            "num_elements": 1,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
