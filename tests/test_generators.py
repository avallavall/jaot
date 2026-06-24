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
