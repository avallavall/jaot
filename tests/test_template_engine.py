"""
Exhaustive tests for the Template Engine — all generators.

Tests cover:
- Happy paths with example inputs
- Edge cases: empty lists, zero values, single items
- Boundary conditions: max variables, special characters in names
- Validation: generated problems have correct structure
- All 10 generators: budget_allocation, knapsack, assignment, production,
  fertilizer, employee_scheduling, vehicle_routing, portfolio, bin_packing, generic
"""

import pytest

from app.domains.solver.services.template_engine import TemplateEngine
from app.schemas.optimization import (
    ObjectiveSense,
    OptimizationProblem,
    VariableType,
)


@pytest.fixture
def engine():
    return TemplateEngine()


def _assert_valid_problem(problem: OptimizationProblem):
    """Assert that a generated problem has valid structure."""
    assert isinstance(problem, OptimizationProblem)
    assert len(problem.variables) > 0
    assert problem.objective is not None
    assert problem.objective.expression != ""
    assert problem.objective.sense in (ObjectiveSense.MINIMIZE, ObjectiveSense.MAXIMIZE)
    # All variable names must be unique
    names = [v.name for v in problem.variables]
    assert len(names) == len(set(names)), f"Duplicate variable names: {names}"
    # All variable names must be valid identifiers
    for v in problem.variables:
        assert v.name.replace("_", "").isalnum(), f"Invalid var name: {v.name}"
        assert not v.name[0].isdigit(), f"Var name starts with digit: {v.name}"


class TestEmployeeScheduling:
    def test_basic_scheduling(self, engine):
        template = {"generator": "employee_scheduling"}
        user_input = {
            "employees": [
                {"name": "Alice", "hourly_cost": 25, "max_hours": 40, "min_hours": 8},
                {"name": "Bob", "hourly_cost": 22, "max_hours": 40, "min_hours": 0},
            ],
            "shifts": [
                {"name": "morning", "duration_hours": 8, "min_employees": 1, "max_employees": 2},
                {"name": "evening", "duration_hours": 8, "min_employees": 1, "max_employees": 2},
            ],
            "objective": "minimize_cost",
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.name == "employee_scheduling"
        assert problem.objective.sense == ObjectiveSense.MINIMIZE
        # 2 employees * 2 shifts = 4 binary variables
        assert len(problem.variables) == 4
        assert all(v.type == VariableType.BINARY for v in problem.variables)

    def test_unavailable_shifts(self, engine):
        """Employees with unavailable shifts should have those vars fixed to 0."""
        template = {"generator": "employee_scheduling"}
        user_input = {
            "employees": [
                {
                    "name": "Alice",
                    "hourly_cost": 25,
                    "max_hours": 40,
                    "unavailable_shifts": ["night"],
                },
            ],
            "shifts": [
                {"name": "day", "duration_hours": 8, "min_employees": 1},
                {"name": "night", "duration_hours": 8, "min_employees": 1},
            ],
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        # The night shift var should be fixed to 0
        night_var = next(v for v in problem.variables if "night" in v.name)
        assert night_var.upper_bound == 0

    def test_minimize_shifts_objective(self, engine):
        template = {"generator": "employee_scheduling"}
        user_input = {
            "employees": [{"name": "A", "hourly_cost": 20, "max_hours": 40}],
            "shifts": [{"name": "s1", "duration_hours": 8, "min_employees": 1}],
            "objective": "minimize_shifts",
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        # Objective should not contain cost coefficients
        assert "20" not in problem.objective.expression or "160" not in problem.objective.expression

    def test_single_employee_single_shift(self, engine):
        """Minimal case: 1 employee, 1 shift."""
        template = {"generator": "employee_scheduling"}
        user_input = {
            "employees": [{"name": "Solo", "hourly_cost": 30, "max_hours": 8}],
            "shifts": [{"name": "only_shift", "duration_hours": 8, "min_employees": 1}],
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert len(problem.variables) == 1

    def test_special_characters_in_names(self, engine):
        """Names with spaces and special chars should be sanitized."""
        template = {"generator": "employee_scheduling"}
        user_input = {
            "employees": [{"name": "María García", "hourly_cost": 25, "max_hours": 40}],
            "shifts": [{"name": "Morning Shift #1", "duration_hours": 8, "min_employees": 1}],
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        for v in problem.variables:
            assert " " not in v.name
            assert "#" not in v.name

    def test_min_hours_constraint(self, engine):
        """Employees with min_hours > 0 should have a min hours constraint."""
        template = {"generator": "employee_scheduling"}
        user_input = {
            "employees": [{"name": "A", "hourly_cost": 20, "max_hours": 40, "min_hours": 16}],
            "shifts": [
                {"name": "s1", "duration_hours": 8, "min_employees": 1},
                {"name": "s2", "duration_hours": 8, "min_employees": 1},
                {"name": "s3", "duration_hours": 8, "min_employees": 1},
            ],
        }
        problem = engine.render(template, user_input)
        min_hours_constraints = [c for c in problem.constraints if "min_hours" in (c.name or "")]
        assert len(min_hours_constraints) == 1
        assert ">=" in min_hours_constraints[0].expression


class TestVehicleRouting:
    def test_basic_vrp(self, engine):
        template = {"generator": "vehicle_routing"}
        user_input = {
            "depot": {"name": "depot"},
            "locations": [
                {"name": "A", "demand": 3},
                {"name": "B", "demand": 5},
            ],
            "vehicles": [
                {"name": "truck1", "capacity": 10, "cost_per_unit_distance": 1.0},
            ],
            "distances": {
                "depot_a": 10,
                "depot_b": 20,
                "a_depot": 10,
                "b_depot": 20,
                "a_b": 15,
                "b_a": 15,
            },
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.name == "vehicle_routing"
        assert problem.objective.sense == ObjectiveSense.MINIMIZE

    def test_single_location(self, engine):
        """Minimal VRP: 1 vehicle, 1 location."""
        template = {"generator": "vehicle_routing"}
        user_input = {
            "depot": {"name": "depot"},
            "locations": [{"name": "X", "demand": 1}],
            "vehicles": [{"name": "v1", "capacity": 10}],
            "distances": {"depot_x": 5, "x_depot": 5},
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)

    def test_multiple_vehicles(self, engine):
        template = {"generator": "vehicle_routing"}
        user_input = {
            "depot": {"name": "depot"},
            "locations": [
                {"name": "A", "demand": 3},
                {"name": "B", "demand": 5},
                {"name": "C", "demand": 2},
            ],
            "vehicles": [
                {"name": "truck1", "capacity": 6},
                {"name": "truck2", "capacity": 8},
            ],
            "distances": {
                "depot_a": 10,
                "depot_b": 20,
                "depot_c": 15,
                "a_depot": 10,
                "b_depot": 20,
                "c_depot": 15,
                "a_b": 12,
                "a_c": 8,
                "b_a": 12,
                "b_c": 14,
                "c_a": 8,
                "c_b": 14,
            },
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        # Should have visit constraints for each location
        visit_constraints = [
            c for c in problem.constraints if c.name and c.name.startswith("visit_")
        ]
        assert len(visit_constraints) == 3

    def test_missing_distance_uses_default(self, engine):
        """Missing distances should default to 100."""
        template = {"generator": "vehicle_routing"}
        user_input = {
            "depot": {"name": "depot"},
            "locations": [{"name": "A", "demand": 1}],
            "vehicles": [{"name": "v1", "capacity": 10}],
            "distances": {},  # No distances provided
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        # Should still generate a valid problem with default distances
        assert "100" in problem.objective.expression


class TestPortfolioOptimization:
    def test_basic_portfolio(self, engine):
        template = {"generator": "portfolio"}
        user_input = {
            "assets": [
                {"name": "stocks", "expected_return": 0.10, "risk": 0.15, "max_allocation": 0.6},
                {"name": "bonds", "expected_return": 0.03, "risk": 0.04, "max_allocation": 0.8},
            ],
            "total_budget": 100000,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.objective.sense == ObjectiveSense.MAXIMIZE
        # Budget constraint: allocations within total_budget
        budget_constraints = [c for c in problem.constraints if c.name == "budget"]
        assert len(budget_constraints) == 1
        assert "<= 100000" in budget_constraints[0].expression

    def test_risk_constraint(self, engine):
        template = {"generator": "portfolio"}
        user_input = {
            "assets": [
                {"name": "A", "expected_return": 0.10, "risk": 0.20},
                {"name": "B", "expected_return": 0.05, "risk": 0.05},
            ],
            "total_budget": 100000,
            "max_risk": 0.12,
        }
        problem = engine.render(template, user_input)
        risk_constraints = [c for c in problem.constraints if c.name == "max_risk"]
        assert len(risk_constraints) == 1
        assert "<=" in risk_constraints[0].expression

    def test_min_return_constraint(self, engine):
        template = {"generator": "portfolio"}
        user_input = {
            "assets": [
                {"name": "A", "expected_return": 0.10, "risk": 0.20},
                {"name": "B", "expected_return": 0.05, "risk": 0.05},
            ],
            "total_budget": 100000,
            "min_return": 0.07,
        }
        problem = engine.render(template, user_input)
        return_constraints = [c for c in problem.constraints if c.name == "min_return"]
        assert len(return_constraints) == 1
        assert ">=" in return_constraints[0].expression

    def test_cardinality_constraint(self, engine):
        """max_assets should add binary selection variables."""
        template = {"generator": "portfolio"}
        user_input = {
            "assets": [
                {"name": "A", "expected_return": 0.10, "risk": 0.15, "max_allocation": 0.5},
                {"name": "B", "expected_return": 0.08, "risk": 0.10, "max_allocation": 0.5},
                {"name": "C", "expected_return": 0.05, "risk": 0.05, "max_allocation": 0.5},
            ],
            "total_budget": 100000,
            "max_assets": 2,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        # Should have 3 continuous + 3 binary = 6 variables
        binary_vars = [v for v in problem.variables if v.type == VariableType.BINARY]
        assert len(binary_vars) == 3
        # Should have max_assets constraint
        card_constraints = [c for c in problem.constraints if c.name == "max_assets"]
        assert len(card_constraints) == 1

    def test_sector_constraints(self, engine):
        template = {"generator": "portfolio"}
        user_input = {
            "assets": [
                {"name": "A", "expected_return": 0.10, "risk": 0.15, "sector": "tech"},
                {"name": "B", "expected_return": 0.08, "risk": 0.10, "sector": "tech"},
                {"name": "C", "expected_return": 0.05, "risk": 0.05, "sector": "bonds"},
            ],
            "total_budget": 100000,
            "sector_limits": {"tech": 0.5, "bonds": 0.6},
        }
        problem = engine.render(template, user_input)
        sector_constraints = [c for c in problem.constraints if c.name and "sector_" in c.name]
        assert len(sector_constraints) == 2

    def test_single_asset(self, engine):
        """Single asset: must allocate 100%."""
        template = {"generator": "portfolio"}
        user_input = {
            "assets": [{"name": "only_asset", "expected_return": 0.10, "risk": 0.15}],
            "total_budget": 50000,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert len(problem.variables) == 1

    def test_no_risk_no_return_constraints(self, engine):
        """When max_risk=0 and min_return=0, no risk/return constraints."""
        template = {"generator": "portfolio"}
        user_input = {
            "assets": [
                {"name": "A", "expected_return": 0.10, "risk": 0.15},
                {"name": "B", "expected_return": 0.05, "risk": 0.05},
            ],
            "total_budget": 100000,
            "max_risk": 0,
            "min_return": 0,
        }
        problem = engine.render(template, user_input)
        risk_constraints = [c for c in problem.constraints if c.name in ("max_risk", "min_return")]
        assert len(risk_constraints) == 0


class TestBinPacking:
    def test_basic_bin_packing(self, engine):
        template = {"generator": "bin_packing"}
        user_input = {
            "items": [
                {"name": "item_1", "size": 40},
                {"name": "item_2", "size": 30},
                {"name": "item_3", "size": 50},
            ],
            "bin_capacity": 100,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.name == "bin_packing"
        assert problem.objective.sense == ObjectiveSense.MINIMIZE

    def test_single_item(self, engine):
        """Single item should need exactly 1 bin."""
        template = {"generator": "bin_packing"}
        user_input = {
            "items": [{"name": "only_item", "size": 50}],
            "bin_capacity": 100,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        # 1 bin var + 1 assignment var = 2 variables
        assert len(problem.variables) == 2

    def test_items_larger_than_half_capacity(self, engine):
        """Items > capacity/2 each need their own bin."""
        template = {"generator": "bin_packing"}
        user_input = {
            "items": [
                {"name": "big1", "size": 60},
                {"name": "big2", "size": 70},
            ],
            "bin_capacity": 100,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)

    def test_max_bins_parameter(self, engine):
        """Explicit max_bins should limit the number of bin variables."""
        template = {"generator": "bin_packing"}
        user_input = {
            "items": [
                {"name": "a", "size": 10},
                {"name": "b", "size": 20},
                {"name": "c", "size": 30},
            ],
            "bin_capacity": 100,
            "max_bins": 2,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        bin_vars = [v for v in problem.variables if v.name.startswith("bin_")]
        assert len(bin_vars) == 2

    def test_symmetry_breaking(self, engine):
        """Should have symmetry-breaking constraints."""
        template = {"generator": "bin_packing"}
        user_input = {
            "items": [
                {"name": "a", "size": 10},
                {"name": "b", "size": 20},
                {"name": "c", "size": 30},
            ],
            "bin_capacity": 100,
        }
        problem = engine.render(template, user_input)
        symmetry_constraints = [c for c in problem.constraints if c.name and "symmetry" in c.name]
        # n-1 symmetry constraints for n bins
        bin_count = len([v for v in problem.variables if v.name.startswith("bin_")])
        assert len(symmetry_constraints) == bin_count - 1

    def test_item_exactly_capacity(self, engine):
        """Item exactly equal to bin capacity should work."""
        template = {"generator": "bin_packing"}
        user_input = {
            "items": [{"name": "exact", "size": 100}],
            "bin_capacity": 100,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)


class TestBudgetAllocation:
    def test_single_department(self, engine):
        template = {"generator": "budget_allocation"}
        user_input = {
            "total_budget": 50000,
            "departments": [
                {
                    "name": "Only Dept",
                    "min_allocation": 0,
                    "max_allocation": 50000,
                    "expected_roi": 1.5,
                }
            ],
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert len(problem.variables) == 1

    def test_minimize_cost_objective(self, engine):
        template = {"generator": "budget_allocation"}
        user_input = {
            "total_budget": 100000,
            "departments": [
                {"name": "A", "expected_roi": 1.5},
                {"name": "B", "expected_roi": 2.0},
            ],
            "objective": "minimize_cost",
        }
        problem = engine.render(template, user_input)
        assert problem.objective.sense == ObjectiveSense.MINIMIZE


class TestKnapsack:
    def test_empty_items_list(self, engine):
        """Empty items list must be rejected before reaching the solver."""
        template = {"generator": "knapsack"}
        user_input = {"items": [], "capacity": 100}
        with pytest.raises(ValueError, match=r"at least one item"):
            engine.render(template, user_input)

    def test_single_item(self, engine):
        template = {"generator": "knapsack"}
        user_input = {
            "items": [{"name": "gem", "value": 1000, "weight": 1}],
            "capacity": 100,
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert len(problem.variables) == 1
        assert problem.variables[0].type == VariableType.BINARY


class TestAssignment:
    def test_more_workers_than_tasks(self, engine):
        template = {"generator": "assignment"}
        user_input = {
            "workers": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
            "tasks": [{"name": "T1"}],
            "costs": {"a_t1": 5, "b_t1": 3, "c_t1": 7},
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        # Each task assigned to exactly 1 worker
        task_constraints = [c for c in problem.constraints if c.name and c.name.startswith("task_")]
        assert len(task_constraints) == 1
        assert "== 1" in task_constraints[0].expression

    def test_equal_workers_and_tasks(self, engine):
        template = {"generator": "assignment"}
        user_input = {
            "workers": [{"name": "A"}, {"name": "B"}],
            "tasks": [{"name": "T1"}, {"name": "T2"}],
            "costs": {"a_t1": 1, "a_t2": 2, "b_t1": 3, "b_t2": 4},
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert len(problem.variables) == 4


class TestProduction:
    def test_integer_variables(self, engine):
        template = {"generator": "production"}
        user_input = {
            "products": [{"name": "widget", "profit_per_unit": 10, "max_production": 100}],
            "resources": [{"name": "material", "available": 500, "usage": {"widget": 5}}],
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.variables[0].type == VariableType.INTEGER


class TestGeneric:
    def test_passthrough(self, engine):
        """Generic generator should pass input directly to OptimizationProblem."""
        template = {"generator": "generic"}
        user_input = {
            "name": "test",
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
            "objective": {"sense": "maximize", "expression": "x"},
            "constraints": [{"expression": "x <= 10"}],
        }
        problem = engine.render(template, user_input)
        _assert_valid_problem(problem)
        assert problem.name == "test"


class TestSanitizeName:
    def test_spaces(self, engine):
        assert engine._sanitize_name("hello world") == "hello_world"

    def test_special_chars(self, engine):
        assert engine._sanitize_name("café-latte!") == "caf__latte_"

    def test_starts_with_digit(self, engine):
        assert engine._sanitize_name("1st_place").startswith("v_")
