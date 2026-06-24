"""Tests for insights service and API endpoint.

Unit tests for generate_insights(), integration tests for
GET /api/v2/solve/insights/{execution_id}.
"""

from app.domains.solver.services.insights import generate_insights
from app.models import ModelExecution
from app.models.optimization_model import ExecutionStatus
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)
from app.shared.utils.id_generator import generate_id


def _simple_problem() -> OptimizationProblem:
    return OptimizationProblem(
        name="insights_test",
        variables=[
            Variable(name="x1", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="x2", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="x3", type=VariableType.INTEGER, lower_bound=0, upper_bound=5),
        ],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x1 + 2*x2 + 3*x3"),
        constraints=[
            Constraint(name="c1", expression="x1 + x2 + x3 <= 15"),
            Constraint(name="c2", expression="x1 + x2 >= 2"),
        ],
    )


def _optimal_result() -> dict:
    return {
        "model": {"x1": 2.0, "x2": 0.0, "x3": 0.0},
        "objective_value": 2.0,
        "solver_status": "optimal",
        "solve_time_seconds": 0.05,
        "gap": 0.0,
    }


def _create_execution(db_session, org_id, **kwargs) -> ModelExecution:
    exe = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org_id,
        input_data=kwargs.get("input_data", _simple_problem().model_dump()),
        result_data=kwargs.get("result_data", _optimal_result()),
        status=kwargs.get("status", ExecutionStatus.COMPLETED.value),
        credits_consumed=1,
        solver_status=kwargs.get("solver_status", "optimal"),
        objective_value=kwargs.get("objective_value", 2.0),
    )
    db_session.add(exe)
    db_session.commit()
    return exe


# UNIT TESTS — generate_insights()


class TestGenerateInsightsOptimal:
    """Insights for an optimal solution."""

    def setup_method(self):
        self.insights = generate_insights(_simple_problem(), _optimal_result())

    def test_has_optimal_insight(self):
        messages = [i.message for i in self.insights]
        assert any("globally optimal" in m for m in messages)

    def test_has_objective_value(self):
        messages = [i.message for i in self.insights]
        assert any("2" in m and "value" in m.lower() for m in messages)

    def test_has_performance_insight(self):
        categories = [i.category for i in self.insights]
        assert "performance" in categories

    def test_optimal_severity_is_success(self):
        optimal = [i for i in self.insights if "globally optimal" in i.message]
        assert optimal[0].severity == "success"


class TestGenerateInsightsFeasible:
    """Insights for a feasible (non-optimal) solution."""

    def test_suggests_more_time(self):
        result = _optimal_result()
        result["solver_status"] = "feasible"
        result["gap"] = 0.15
        insights = generate_insights(_simple_problem(), result)
        messages = [i.message for i in insights]
        assert any("time limit" in m.lower() for m in messages)

    def test_gap_warning(self):
        result = _optimal_result()
        result["gap"] = 0.10
        insights = generate_insights(_simple_problem(), result)
        warnings = [i for i in insights if i.severity == "warning"]
        assert any("gap" in i.message.lower() for i in warnings)


class TestGenerateInsightsInfeasible:
    """Insights for an infeasible problem."""

    def test_infeasible_message(self):
        result = {"solver_status": "infeasible"}
        insights = generate_insights(_simple_problem(), result)
        messages = [i.message for i in insights]
        assert any("infeasible" in m.lower() for m in messages)


class TestGenerateInsightsUnbounded:
    """Insights for an unbounded problem."""

    def test_unbounded_message(self):
        result = {"solver_status": "unbounded"}
        insights = generate_insights(_simple_problem(), result)
        messages = [i.message for i in insights]
        assert any("unbounded" in m.lower() for m in messages)


class TestGenerateInsightsVariables:
    """Variable-specific insights."""

    def test_at_bounds_insight(self):
        """Variables at their bounds should be flagged."""
        problem = _simple_problem()
        result = _optimal_result()
        result["model"] = {"x1": 10.0, "x2": 10.0, "x3": 0.0}  # x1, x2 at upper, x3 at lower
        insights = generate_insights(problem, result)
        messages = [i.message for i in insights]
        assert any("bounds" in m.lower() for m in messages)

    def test_zero_variables_insight(self):
        """Zero variables should be noted."""
        problem = _simple_problem()
        result = _optimal_result()
        result["model"] = {"x1": 5.0, "x2": 0.0, "x3": 0.0}
        insights = generate_insights(problem, result)
        messages = [i.message for i in insights]
        assert any("zero" in m.lower() for m in messages)

    def test_mixed_types_insight(self):
        """Mixed variable types should be reported."""
        insights = generate_insights(_simple_problem(), _optimal_result())
        messages = [i.message for i in insights]
        assert any("mix" in m.lower() or "continuous" in m.lower() for m in messages)


class TestGenerateInsightsSensitivity:
    """Sensitivity/shadow price insights."""

    def test_binding_constraints(self):
        result = _optimal_result()
        result["sensitivity"] = {
            "constraints": [
                {"name": "c1", "shadow_price": -0.5, "is_binding": True},
                {"name": "c2", "shadow_price": 0.0, "is_binding": False},
            ]
        }
        insights = generate_insights(_simple_problem(), result)
        messages = [i.message for i in insights]
        assert any("binding" in m.lower() for m in messages)

    def test_most_impactful_constraint(self):
        result = _optimal_result()
        result["sensitivity"] = {
            "constraints": [
                {"name": "c1", "shadow_price": -2.5, "is_binding": True},
                {"name": "c2", "shadow_price": 0.1, "is_binding": True},
            ]
        }
        insights = generate_insights(_simple_problem(), result)
        messages = [i.message for i in insights]
        assert any("c1" in m and "impactful" in m.lower() for m in messages)


class TestGenerateInsightsEmpty:
    """Edge case: empty or minimal data."""

    def test_empty_result(self):
        insights = generate_insights(_simple_problem(), {})
        assert isinstance(insights, list)

    def test_no_solution(self):
        insights = generate_insights(_simple_problem(), {"solver_status": "error"})
        assert isinstance(insights, list)


class TestInsightsEndpoint:
    """Integration tests for GET /api/v2/solve/insights/{execution_id}."""

    def test_insights_optimal(self, authenticated_client, db_session, test_organization):
        exe = _create_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/insights/{exe.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_id"] == exe.id
        assert len(data["insights"]) > 0
        assert all("category" in i and "message" in i and "severity" in i for i in data["insights"])

    def test_insights_has_categories(self, authenticated_client, db_session, test_organization):
        exe = _create_execution(db_session, test_organization.id)
        resp = authenticated_client.get(f"/api/v2/solve/insights/{exe.id}")
        categories = {i["category"] for i in resp.json()["insights"]}
        assert "objective" in categories

    def test_insights_not_found(self, authenticated_client):
        resp = authenticated_client.get("/api/v2/solve/insights/exe_nonexistent")
        assert resp.status_code == 404

    def test_insights_no_auth(self, client, db_session, test_organization):
        exe = _create_execution(db_session, test_organization.id)
        resp = client.get(f"/api/v2/solve/insights/{exe.id}")
        assert resp.status_code == 401

    def test_insights_infeasible(self, authenticated_client, db_session, test_organization):
        exe = _create_execution(
            db_session,
            test_organization.id,
            result_data={"solver_status": "infeasible"},
            solver_status="infeasible",
            objective_value=None,
        )
        resp = authenticated_client.get(f"/api/v2/solve/insights/{exe.id}")
        assert resp.status_code == 200
        messages = [i["message"] for i in resp.json()["insights"]]
        assert any("infeasible" in m.lower() for m in messages)

    def test_insights_with_sensitivity(self, authenticated_client, db_session, test_organization):
        result = _optimal_result()
        result["sensitivity"] = {
            "constraints": [
                {"name": "c1", "shadow_price": -1.5, "is_binding": True},
                {"name": "c2", "shadow_price": 0.0, "is_binding": False},
            ]
        }
        exe = _create_execution(db_session, test_organization.id, result_data=result)
        resp = authenticated_client.get(f"/api/v2/solve/insights/{exe.id}")
        assert resp.status_code == 200
        messages = [i["message"] for i in resp.json()["insights"]]
        assert any("binding" in m.lower() for m in messages)

    def test_insights_empty_input_data(self, authenticated_client, db_session, test_organization):
        """Execution with no input_data returns empty insights (not error)."""
        exe = ModelExecution(
            id=generate_id("exe_"),
            organization_id=test_organization.id,
            input_data={},
            result_data=_optimal_result(),
            status=ExecutionStatus.COMPLETED.value,
            credits_consumed=1,
        )
        db_session.add(exe)
        db_session.commit()

        resp = authenticated_client.get(f"/api/v2/solve/insights/{exe.id}")
        assert resp.status_code == 200
        assert resp.json()["insights"] == []
