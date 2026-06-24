"""
Tests for the Universal SCIP Solver Service

Run with: pytest tests/test_solver.py -v
"""

import pytest

from app.domains.solver.services.solver_service import SolverService
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverOptions,
    SolverStatus,
    Variable,
    VariableType,
)


class TestSolverService:
    """Tests for the solver service."""

    def setup_method(self):
        self.solver = SolverService()

    def test_simple_linear_maximize(self):
        """Test simple linear maximization problem."""
        problem = OptimizationProblem(
            name="simple_max",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="3*x + 2*y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[
                Constraint(expression="x + y <= 4"),
                Constraint(expression="2*x + y <= 5"),
            ],
        )

        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.objective_value is not None
        assert abs(result.objective_value - 9.0) < 0.01  # Expected: x=1, y=3 -> 3+6=9
        assert result.solution is not None
        assert abs(result.solution["x"] - 1.0) < 0.01
        assert abs(result.solution["y"] - 3.0) < 0.01

    def test_simple_linear_minimize(self):
        """Test simple linear minimization problem.

        Minimize 2x + 3y subject to x + y >= 5, x >= 2, x,y >= 0.
        Optimal: push y to 0 (y costs more than x), x=5.
        """
        problem = OptimizationProblem(
            name="simple_min",
            objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="2*x + 3*y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[
                Constraint(expression="x + y >= 5"),
                Constraint(expression="x >= 2"),
            ],
        )

        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.objective_value == pytest.approx(10.0, abs=0.01)
        assert result.solution is not None
        assert result.solution["x"] == pytest.approx(5.0, abs=0.01)
        assert result.solution["y"] == pytest.approx(0.0, abs=0.01)

    def test_integer_programming(self):
        """Test integer programming problem.

        Maximize 5x + 3y subject to 2x + y <= 10, 0 <= x,y <= 10 (integer).
        Since y's coefficient (3) per unit of constraint (1) beats x's (5 per 2),
        the optimum is x=0, y=10 with obj=30.
        """
        problem = OptimizationProblem(
            name="integer_test",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="5*x + 3*y"),
            variables=[
                Variable(name="x", type=VariableType.INTEGER, lower_bound=0, upper_bound=10),
                Variable(name="y", type=VariableType.INTEGER, lower_bound=0, upper_bound=10),
            ],
            constraints=[
                Constraint(expression="2*x + y <= 10"),
            ],
        )

        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None
        assert result.objective_value == pytest.approx(30.0, abs=0.01)
        assert result.solution["x"] == pytest.approx(0.0, abs=0.01)
        assert result.solution["y"] == pytest.approx(10.0, abs=0.01)

    def test_binary_knapsack(self):
        """Test binary knapsack problem."""
        problem = OptimizationProblem(
            name="knapsack",
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE, expression="60*item1 + 100*item2 + 120*item3"
            ),
            variables=[
                Variable(name="item1", type=VariableType.BINARY),
                Variable(name="item2", type=VariableType.BINARY),
                Variable(name="item3", type=VariableType.BINARY),
            ],
            constraints=[
                Constraint(expression="10*item1 + 20*item2 + 30*item3 <= 50"),
            ],
        )

        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.objective_value is not None
        # Optimal: item2=1, item3=1 -> 100+120=220
        assert abs(result.objective_value - 220.0) < 0.01
        assert result.solution is not None
        # Binary values should be 0 or 1
        for val in result.solution.values():
            assert val in [0, 1, 0.0, 1.0]

    def test_infeasible_problem(self):
        """Test that infeasible problems are detected."""
        problem = OptimizationProblem(
            name="infeasible",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0),
            ],
            constraints=[
                Constraint(expression="x >= 10"),
                Constraint(expression="x <= 5"),
            ],
        )

        result = self.solver.solve(problem)

        assert result.status == SolverStatus.INFEASIBLE

    def test_time_limit(self):
        """Test that time limit is respected."""
        problem = OptimizationProblem(
            name="time_test",
            objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x + y"),
            variables=[
                Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=100),
                Variable(name="y", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=100),
            ],
            constraints=[
                Constraint(expression="x + y <= 150"),
            ],
            options=SolverOptions(time_limit_seconds=1),
        )

        result = self.solver.solve(problem)

        # Should complete quickly, not hit time limit
        assert result.status in [SolverStatus.OPTIMAL, SolverStatus.FEASIBLE]
        assert result.solve_time_seconds < 2  # Should be much faster

    def test_production_planning(self):
        """Test a realistic production planning problem."""
        problem = OptimizationProblem(
            name="production",
            description="Maximize profit from production",
            objective=Objective(
                sense=ObjectiveSense.MAXIMIZE, expression="50*chairs + 80*tables + 120*desks"
            ),
            variables=[
                Variable(name="chairs", type=VariableType.INTEGER, lower_bound=0, upper_bound=100),
                Variable(name="tables", type=VariableType.INTEGER, lower_bound=0, upper_bound=60),
                Variable(name="desks", type=VariableType.INTEGER, lower_bound=10, upper_bound=40),
            ],
            constraints=[
                Constraint(name="wood", expression="2*chairs + 5*tables + 8*desks <= 500"),
                Constraint(name="labor", expression="1*chairs + 2*tables + 3*desks <= 200"),
                Constraint(name="screws", expression="8*chairs + 12*tables + 20*desks <= 1000"),
            ],
        )

        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.objective_value is not None
        assert result.objective_value > 0
        assert result.solution is not None

        # Verify constraints are satisfied
        sol = result.solution
        assert 2 * sol["chairs"] + 5 * sol["tables"] + 8 * sol["desks"] <= 500
        assert 1 * sol["chairs"] + 2 * sol["tables"] + 3 * sol["desks"] <= 200
        assert 8 * sol["chairs"] + 12 * sol["tables"] + 20 * sol["desks"] <= 1000

        # Verify bounds
        assert 0 <= sol["chairs"] <= 100
        assert 0 <= sol["tables"] <= 60
        assert 10 <= sol["desks"] <= 40


class TestTemplateEngine:
    """Tests for the template engine."""

    def setup_method(self):
        from app.domains.solver.services.template_engine import TemplateEngine

        self.engine = TemplateEngine()

    def test_knapsack_template(self):
        """Test knapsack template generation."""
        template = {"generator": "knapsack"}
        user_input = {
            "capacity": 50,
            "items": [
                {"name": "laptop", "value": 600, "weight": 10},
                {"name": "camera", "value": 500, "weight": 5},
            ],
        }

        problem = self.engine.render(template, user_input)

        assert problem.name == "knapsack"
        assert len(problem.variables) == 2
        assert all(v.type == VariableType.BINARY for v in problem.variables)
        assert len(problem.constraints) == 1
        assert problem.objective.sense == ObjectiveSense.MAXIMIZE

    def test_budget_allocation_template(self):
        """Test budget allocation template generation."""
        template = {"generator": "budget_allocation"}
        user_input = {
            "total_budget": 100000,
            "departments": [
                {
                    "name": "Marketing",
                    "min_allocation": 10000,
                    "max_allocation": 40000,
                    "expected_roi": 1.5,
                },
                {
                    "name": "RnD",
                    "min_allocation": 20000,
                    "max_allocation": 50000,
                    "expected_roi": 2.0,
                },
            ],
            "objective": "maximize_roi",
        }

        problem = self.engine.render(template, user_input)

        assert problem.name == "budget_allocation"
        assert len(problem.variables) == 2
        assert len(problem.constraints) >= 1  # At least total budget constraint
        assert problem.objective.sense == ObjectiveSense.MAXIMIZE

    def test_production_template(self):
        """Test production planning template generation."""
        template = {"generator": "production"}
        user_input = {
            "products": [
                {
                    "name": "widget",
                    "profit_per_unit": 50,
                    "min_production": 0,
                    "max_production": 100,
                },
                {"name": "gadget", "profit_per_unit": 80, "min_production": 10},
            ],
            "resources": [
                {"name": "labor", "available": 200, "usage": {"widget": 2, "gadget": 3}},
            ],
        }

        problem = self.engine.render(template, user_input)

        assert problem.name == "production_planning"
        assert len(problem.variables) == 2
        assert problem.objective.sense == ObjectiveSense.MAXIMIZE


class TestEndToEnd:
    """End-to-end tests combining template + solver."""

    def setup_method(self):
        from app.domains.solver.services.template_engine import TemplateEngine

        self.engine = TemplateEngine()
        self.solver = SolverService()

    def test_knapsack_e2e(self):
        """Test complete knapsack workflow."""
        template = {"generator": "knapsack"}
        user_input = {
            "capacity": 50,
            "items": [
                {"name": "laptop", "value": 600, "weight": 10},
                {"name": "camera", "value": 500, "weight": 5},
                {"name": "headphones", "value": 150, "weight": 2},
                {"name": "tablet", "value": 400, "weight": 8},
            ],
        }

        problem = self.engine.render(template, user_input)
        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.objective_value == 1650  # All items fit: 600+500+150+400

        # Verify all items selected (total weight = 25 < 50)
        assert result.solution["laptop"] == 1
        assert result.solution["camera"] == 1
        assert result.solution["headphones"] == 1
        assert result.solution["tablet"] == 1

    def test_budget_allocation_e2e(self):
        """Test complete budget allocation workflow."""
        template = {"generator": "budget_allocation"}
        user_input = {
            "total_budget": 100000,
            "departments": [
                {
                    "name": "Marketing",
                    "min_allocation": 10000,
                    "max_allocation": 40000,
                    "expected_roi": 1.5,
                },
                {
                    "name": "RnD",
                    "min_allocation": 20000,
                    "max_allocation": 50000,
                    "expected_roi": 2.0,
                },
                {
                    "name": "Operations",
                    "min_allocation": 15000,
                    "max_allocation": 35000,
                    "expected_roi": 1.2,
                },
            ],
            "objective": "maximize_roi",
        }

        problem = self.engine.render(template, user_input)
        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None

        # Verify budget constraint
        total_allocated = sum(result.solution.values())
        assert total_allocated <= 100000 + 0.01  # Allow small floating point error

        # R&D should get max (highest ROI)
        assert result.solution["rnd"] == 50000


class TestFertilizerMixing:
    """Tests for fertilizer mixing optimization."""

    def setup_method(self):
        from app.domains.solver.services.template_engine import TemplateEngine

        self.engine = TemplateEngine()
        self.solver = SolverService()

    def test_simple_npk_blend(self):
        """Test basic NPK fertilizer blend."""
        template = {"generator": "fertilizer"}
        user_input = {
            "nutrients": [
                {"id": "N", "name": "Nitrogen"},
                {"id": "P", "name": "Phosphorus"},
                {"id": "K", "name": "Potassium"},
            ],
            "raw_materials": [
                {
                    "id": "urea",
                    "name": "Urea",
                    "price_per_ton": 350,
                    "stock_max": 5000,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [
                        {"id": "N", "percentage": 46.0},
                        {"id": "P", "percentage": 0.0},
                        {"id": "K", "percentage": 0.0},
                    ],
                },
                {
                    "id": "dap",
                    "name": "DAP",
                    "price_per_ton": 480,
                    "stock_max": 3000,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [
                        {"id": "N", "percentage": 18.0},
                        {"id": "P", "percentage": 46.0},
                        {"id": "K", "percentage": 0.0},
                    ],
                },
                {
                    "id": "mop",
                    "name": "MOP",
                    "price_per_ton": 320,
                    "stock_max": 4000,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [
                        {"id": "N", "percentage": 0.0},
                        {"id": "P", "percentage": 0.0},
                        {"id": "K", "percentage": 60.0},
                    ],
                },
                {
                    "id": "filler",
                    "name": "Filler",
                    "price_per_ton": 50,
                    "stock_max": -1,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [
                        {"id": "N", "percentage": 0.0},
                        {"id": "P", "percentage": 0.0},
                        {"id": "K", "percentage": 0.0},
                    ],
                },
            ],
            "target_nutrients": [
                {"id": "N", "min": 15.0, "max": 20.0},
                {"id": "P", "min": 10.0, "max": 15.0},
                {"id": "K", "min": 12.0, "max": 18.0},
            ],
            "mix_quantity_min": 1000,
            "mix_quantity_max": 1000,
        }

        problem = self.engine.render(template, user_input)
        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution is not None

        # Verify total quantity
        total = sum(result.solution.values())
        assert abs(total - 1000) < 0.1

        # Verify nutrient percentages
        n_total = result.solution["urea"] * 0.46 + result.solution["dap"] * 0.18
        p_total = result.solution["dap"] * 0.46
        k_total = result.solution["mop"] * 0.60

        n_pct = (n_total / total) * 100
        p_pct = (p_total / total) * 100
        k_pct = (k_total / total) * 100

        assert 15.0 - 0.01 <= n_pct <= 20.0 + 0.01, f"N% = {n_pct}"
        assert 10.0 - 0.01 <= p_pct <= 15.0 + 0.01, f"P% = {p_pct}"
        assert 12.0 - 0.01 <= k_pct <= 18.0 + 0.01, f"K% = {k_pct}"

    def test_single_nutrient_min_only(self):
        """Test with only minimum nutrient constraint."""
        template = {"generator": "fertilizer"}
        user_input = {
            "nutrients": [{"id": "N", "name": "Nitrogen"}],
            "raw_materials": [
                {
                    "id": "urea",
                    "name": "Urea",
                    "price_per_ton": 350,
                    "stock_max": 1000,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [{"id": "N", "percentage": 46.0}],
                },
                {
                    "id": "filler",
                    "name": "Filler",
                    "price_per_ton": 50,
                    "stock_max": -1,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [{"id": "N", "percentage": 0.0}],
                },
            ],
            "target_nutrients": [{"id": "N", "min": 15.0, "max": 0}],  # Only min
            "mix_quantity_min": 100,
            "mix_quantity_max": 500,
        }

        problem = self.engine.render(template, user_input)
        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL

        # Should use minimum urea to meet 15% N at minimum cost
        total = sum(result.solution.values())
        n_pct = (result.solution["urea"] * 0.46 / total) * 100
        assert n_pct >= 15.0 - 0.1

    def test_cost_minimization(self):
        """Test that solver minimizes cost."""
        template = {"generator": "fertilizer"}
        user_input = {
            "nutrients": [{"id": "N", "name": "Nitrogen"}],
            "raw_materials": [
                {
                    "id": "expensive",
                    "name": "Expensive N",
                    "price_per_ton": 500,
                    "stock_max": -1,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [{"id": "N", "percentage": 46.0}],
                },
                {
                    "id": "cheap",
                    "name": "Cheap N",
                    "price_per_ton": 200,
                    "stock_max": -1,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [{"id": "N", "percentage": 46.0}],
                },
            ],
            "target_nutrients": [{"id": "N", "min": 20.0, "max": 50.0}],
            "mix_quantity_min": 100,
            "mix_quantity_max": 100,
        }

        problem = self.engine.render(template, user_input)
        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        # Should use only cheap material
        assert result.solution["expensive"] < 0.1
        assert result.solution["cheap"] > 40  # Needs ~43.5 kg for 20% N in 100kg

    def test_stock_constraint(self):
        """Test that stock limits are respected."""
        template = {"generator": "fertilizer"}
        user_input = {
            "nutrients": [{"id": "N", "name": "Nitrogen"}],
            "raw_materials": [
                {
                    "id": "limited",
                    "name": "Limited Stock",
                    "price_per_ton": 100,
                    "stock_max": 50,  # Only 50kg available
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [{"id": "N", "percentage": 46.0}],
                },
                {
                    "id": "filler",
                    "name": "Filler",
                    "price_per_ton": 50,
                    "stock_max": -1,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [{"id": "N", "percentage": 0.0}],
                },
            ],
            "target_nutrients": [{"id": "N", "min": 10.0, "max": 30.0}],
            "mix_quantity_min": 100,
            "mix_quantity_max": 200,
        }

        problem = self.engine.render(template, user_input)
        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution["limited"] <= 50 + 0.1  # Respect stock limit

    def test_quantity_min_constraint(self):
        """Test that material minimum quantities are respected."""
        template = {"generator": "fertilizer"}
        user_input = {
            "nutrients": [{"id": "N", "name": "Nitrogen"}],
            "raw_materials": [
                {
                    "id": "mandatory",
                    "name": "Mandatory Material",
                    "price_per_ton": 300,
                    "stock_max": -1,
                    "quantity_min": 100,  # Must use at least 100kg
                    "quantity_max": -1,
                    "nutrient_percentages": [{"id": "N", "percentage": 20.0}],
                },
                {
                    "id": "filler",
                    "name": "Filler",
                    "price_per_ton": 50,
                    "stock_max": -1,
                    "quantity_min": 0,
                    "quantity_max": -1,
                    "nutrient_percentages": [{"id": "N", "percentage": 0.0}],
                },
            ],
            "target_nutrients": [{"id": "N", "min": 5.0, "max": 25.0}],
            "mix_quantity_min": 200,
            "mix_quantity_max": 500,
        }

        problem = self.engine.render(template, user_input)
        result = self.solver.solve(problem)

        assert result.status == SolverStatus.OPTIMAL
        assert result.solution["mandatory"] >= 100 - 0.1  # Respect min quantity


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
