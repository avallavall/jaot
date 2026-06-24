"""Tests for solve analytics service and API endpoints.

Unit tests for compute_summary(), compute_trends(), compare_executions().
Integration tests for GET /api/v2/solve/analytics/*.
"""

from datetime import timedelta

from app.domains.solver.services.analytics import (
    compare_executions,
    compute_summary,
    compute_trends,
)
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
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _simple_problem() -> OptimizationProblem:
    return OptimizationProblem(
        name="analytics_test",
        variables=[
            Variable(name="x1", type=VariableType.CONTINUOUS, lower_bound=0, upper_bound=10),
            Variable(name="x2", type=VariableType.INTEGER, lower_bound=0, upper_bound=5),
        ],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression="x1 + 2*x2"),
        constraints=[
            Constraint(name="c1", expression="x1 + x2 <= 15"),
        ],
    )


def _create_execution(db_session, org_id, **kwargs) -> ModelExecution:
    exe = ModelExecution(
        id=kwargs.get("id", generate_id("exe_")),
        organization_id=org_id,
        input_data=kwargs.get("input_data", _simple_problem().model_dump()),
        result_data=kwargs.get(
            "result_data",
            {
                "model": {"x1": 3.0, "x2": 1.0},
                "objective_value": 5.0,
                "solver_status": "optimal",
                "solve_time_seconds": 0.05,
                "gap": 0.0,
            },
        ),
        status=kwargs.get("status", ExecutionStatus.COMPLETED.value),
        solver_status=kwargs.get("solver_status", "optimal"),
        objective_value=kwargs.get("objective_value", 5.0),
        execution_time_ms=kwargs.get("execution_time_ms", 50),
        credits_consumed=kwargs.get("credits_consumed", 1),
        origin=kwargs.get("origin", "manual"),
        created_at=kwargs.get("created_at", utcnow()),
    )
    db_session.add(exe)
    db_session.flush()
    return exe


# UNIT TESTS — compute_summary()


class TestComputeSummaryEmpty:
    """Summary with no executions."""

    def test_empty_org(self, db_session, test_organization):
        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.total_executions == 0
        assert summary.success_rate == 0.0
        assert summary.avg_solve_time_ms is None
        assert summary.total_credits == 0

    def test_empty_distributions(self, db_session, test_organization):
        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.executions_by_status == {}
        assert summary.executions_by_origin == {}


class TestComputeSummaryWithData:
    """Summary with various executions."""

    def test_basic_counts(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id, status="completed")
        _create_execution(db_session, test_organization.id, status="completed")
        _create_execution(db_session, test_organization.id, status="failed", solver_status="error")
        db_session.commit()

        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.total_executions == 3
        assert summary.completed == 2
        assert summary.failed == 1
        assert summary.success_rate == 2 / 3

    def test_credits_aggregation(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id, credits_consumed=5)
        _create_execution(db_session, test_organization.id, credits_consumed=3)
        db_session.commit()

        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.total_credits == 8
        assert summary.avg_credits == 4.0

    def test_solve_time_stats(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id, execution_time_ms=100)
        _create_execution(db_session, test_organization.id, execution_time_ms=200)
        _create_execution(db_session, test_organization.id, execution_time_ms=300)
        db_session.commit()

        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.avg_solve_time_ms == 200.0
        assert summary.median_solve_time_ms == 200.0

    def test_median_even_count(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id, execution_time_ms=100)
        _create_execution(db_session, test_organization.id, execution_time_ms=300)
        db_session.commit()

        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.median_solve_time_ms == 200.0

    def test_days_filter(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id)
        _create_execution(
            db_session,
            test_organization.id,
            created_at=utcnow() - timedelta(days=60),
        )
        db_session.commit()

        summary_30 = compute_summary(db_session, test_organization.id, days=30)
        assert summary_30.total_executions == 1

        summary_all = compute_summary(db_session, test_organization.id, days=0)
        assert summary_all.total_executions == 2

    def test_status_distribution(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id, status="completed")
        _create_execution(db_session, test_organization.id, status="failed", solver_status="error")
        _create_execution(db_session, test_organization.id, status="timeout", solver_status=None)
        db_session.commit()

        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.executions_by_status["completed"] == 1
        assert summary.executions_by_status["failed"] == 1
        assert summary.timed_out == 1

    def test_origin_distribution(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id, origin="manual")
        _create_execution(db_session, test_organization.id, origin="manual")
        _create_execution(db_session, test_organization.id, origin="triggered")
        db_session.commit()

        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.executions_by_origin["manual"] == 2
        assert summary.executions_by_origin["triggered"] == 1

    def test_org_isolation(self, db_session, test_organization, test_organization_2):
        """Executions from other orgs are not included."""
        _create_execution(db_session, test_organization.id)
        _create_execution(db_session, test_organization_2.id)
        db_session.commit()

        summary = compute_summary(db_session, test_organization.id, days=30)
        assert summary.total_executions == 1


# UNIT TESTS — compute_trends()


class TestComputeTrendsEmpty:
    """Trends with no data."""

    def test_empty_returns_empty(self, db_session, test_organization):
        trends = compute_trends(db_session, test_organization.id, days=30)
        assert trends == []


class TestComputeTrendsWithData:
    """Trends with execution data."""

    def test_daily_buckets(self, db_session, test_organization):
        today = utcnow()
        yesterday = today - timedelta(days=1)
        _create_execution(db_session, test_organization.id, created_at=today)
        _create_execution(db_session, test_organization.id, created_at=today)
        _create_execution(db_session, test_organization.id, created_at=yesterday)
        db_session.commit()

        trends = compute_trends(db_session, test_organization.id, days=7, bucket="day")
        assert len(trends) == 2
        latest = trends[-1]
        assert latest.executions == 2

    def test_weekly_buckets(self, db_session, test_organization):
        today = utcnow()
        _create_execution(db_session, test_organization.id, created_at=today)
        _create_execution(
            db_session,
            test_organization.id,
            created_at=today - timedelta(days=8),
        )
        db_session.commit()

        trends = compute_trends(db_session, test_organization.id, days=30, bucket="week")
        assert len(trends) == 2

    def test_credits_per_bucket(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id, credits_consumed=5)
        _create_execution(db_session, test_organization.id, credits_consumed=3)
        db_session.commit()

        trends = compute_trends(db_session, test_organization.id, days=7)
        assert trends[0].credits == 8

    def test_status_counts_per_bucket(self, db_session, test_organization):
        _create_execution(db_session, test_organization.id, status="completed")
        _create_execution(db_session, test_organization.id, status="failed", solver_status="error")
        db_session.commit()

        trends = compute_trends(db_session, test_organization.id, days=7)
        assert trends[0].completed == 1
        assert trends[0].failed == 1

    def test_org_isolation(self, db_session, test_organization, test_organization_2):
        _create_execution(db_session, test_organization.id)
        _create_execution(db_session, test_organization_2.id)
        db_session.commit()

        trends = compute_trends(db_session, test_organization.id, days=30)
        total = sum(t.executions for t in trends)
        assert total == 1


# UNIT TESTS — compare_executions()


class TestCompareExecutionsEmpty:
    """Comparison with no matching IDs."""

    def test_no_matches(self, db_session, test_organization):
        result = compare_executions(db_session, test_organization.id, ["exe_nonexistent"])
        assert result == []


class TestCompareExecutionsWithData:
    """Side-by-side execution comparison."""

    def test_basic_comparison(self, db_session, test_organization):
        exe1 = _create_execution(
            db_session,
            test_organization.id,
            objective_value=10.0,
            execution_time_ms=100,
        )
        exe2 = _create_execution(
            db_session,
            test_organization.id,
            objective_value=5.0,
            execution_time_ms=200,
        )
        db_session.commit()

        result = compare_executions(db_session, test_organization.id, [exe1.id, exe2.id])
        assert len(result) == 2
        assert result[0].id == exe1.id
        assert result[1].id == exe2.id
        assert result[0].objective_value == 10.0
        assert result[1].objective_value == 5.0

    def test_extracts_problem_size(self, db_session, test_organization):
        exe = _create_execution(db_session, test_organization.id)
        db_session.commit()

        result = compare_executions(db_session, test_organization.id, [exe.id])
        assert result[0].num_variables == 2
        assert result[0].num_constraints == 1

    def test_extracts_gap(self, db_session, test_organization):
        exe = _create_execution(
            db_session,
            test_organization.id,
            result_data={
                "model": {"x1": 3.0},
                "objective_value": 5.0,
                "solver_status": "feasible",
                "gap": 0.05,
            },
        )
        db_session.commit()

        result = compare_executions(db_session, test_organization.id, [exe.id])
        assert result[0].gap == 0.05

    def test_org_isolation(self, db_session, test_organization, test_organization_2):
        exe_other = _create_execution(db_session, test_organization_2.id)
        db_session.commit()

        result = compare_executions(db_session, test_organization.id, [exe_other.id])
        assert result == []

    def test_returns_all_when_no_cap(self, db_session, test_organization):
        """Service processes all IDs; route enforces max 10 via 422."""
        ids = []
        for _ in range(12):
            exe = _create_execution(db_session, test_organization.id)
            ids.append(exe.id)
        db_session.commit()

        result = compare_executions(db_session, test_organization.id, ids)
        assert len(result) == 12

    def test_preserves_order(self, db_session, test_organization):
        exe1 = _create_execution(db_session, test_organization.id)
        exe2 = _create_execution(db_session, test_organization.id)
        db_session.commit()

        result = compare_executions(db_session, test_organization.id, [exe2.id, exe1.id])
        assert result[0].id == exe2.id
        assert result[1].id == exe1.id


class TestAnalyticsSummaryEndpoint:
    """Integration tests for GET /api/v2/solve/analytics/summary."""

    def test_summary_empty(self, authenticated_client):
        resp = authenticated_client.get("/api/v2/solve/analytics/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_executions"] == 0
        assert data["success_rate"] == 0.0

    def test_summary_with_data(self, authenticated_client, db_session, test_organization):
        _create_execution(db_session, test_organization.id, status="completed")
        _create_execution(db_session, test_organization.id, status="failed", solver_status="error")
        db_session.commit()

        resp = authenticated_client.get("/api/v2/solve/analytics/summary?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_executions"] == 2
        assert data["completed"] == 1
        assert data["failed"] == 1

    def test_summary_response_shape(self, authenticated_client, db_session, test_organization):
        _create_execution(db_session, test_organization.id)
        db_session.commit()

        resp = authenticated_client.get("/api/v2/solve/analytics/summary")
        data = resp.json()
        required_keys = {
            "total_executions",
            "completed",
            "failed",
            "timed_out",
            "success_rate",
            "avg_solve_time_ms",
            "median_solve_time_ms",
            "total_credits",
            "avg_credits",
            "avg_objective_value",
            "executions_by_status",
            "executions_by_origin",
            "solver_status_distribution",
        }
        assert required_keys.issubset(data.keys())

    def test_summary_days_param(self, authenticated_client, db_session, test_organization):
        _create_execution(db_session, test_organization.id)
        _create_execution(
            db_session,
            test_organization.id,
            created_at=utcnow() - timedelta(days=60),
        )
        db_session.commit()

        resp_30 = authenticated_client.get("/api/v2/solve/analytics/summary?days=30")
        resp_all = authenticated_client.get("/api/v2/solve/analytics/summary?days=0")
        assert resp_30.json()["total_executions"] == 1
        assert resp_all.json()["total_executions"] == 2

    def test_summary_no_auth(self, client):
        resp = client.get("/api/v2/solve/analytics/summary")
        assert resp.status_code == 401


class TestAnalyticsTrendsEndpoint:
    """Integration tests for GET /api/v2/solve/analytics/trends."""

    def test_trends_empty(self, authenticated_client):
        resp = authenticated_client.get("/api/v2/solve/analytics/trends")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"] == []

    def test_trends_with_data(self, authenticated_client, db_session, test_organization):
        _create_execution(db_session, test_organization.id)
        _create_execution(db_session, test_organization.id)
        db_session.commit()

        resp = authenticated_client.get("/api/v2/solve/analytics/trends?days=7&bucket=day")
        assert resp.status_code == 200
        data = resp.json()
        assert data["days"] == 7
        assert data["bucket"] == "day"
        assert len(data["data"]) >= 1
        assert data["data"][0]["executions"] == 2

    def test_trends_bucket_shape(self, authenticated_client, db_session, test_organization):
        _create_execution(db_session, test_organization.id)
        db_session.commit()

        resp = authenticated_client.get("/api/v2/solve/analytics/trends")
        bucket = resp.json()["data"][0]
        required_keys = {
            "date",
            "executions",
            "completed",
            "failed",
            "credits",
            "avg_solve_time_ms",
        }
        assert required_keys.issubset(bucket.keys())

    def test_trends_no_auth(self, client):
        resp = client.get("/api/v2/solve/analytics/trends")
        assert resp.status_code == 401


class TestAnalyticsCompareEndpoint:
    """Integration tests for GET /api/v2/solve/analytics/compare."""

    def test_compare_two(self, authenticated_client, db_session, test_organization):
        exe1 = _create_execution(db_session, test_organization.id, objective_value=10.0)
        exe2 = _create_execution(db_session, test_organization.id, objective_value=5.0)
        db_session.commit()

        resp = authenticated_client.get(f"/api/v2/solve/analytics/compare?ids={exe1.id},{exe2.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["executions"]) == 2
        assert data["executions"][0]["objective_value"] == 10.0
        assert data["executions"][1]["objective_value"] == 5.0

    def test_compare_nonexistent(self, authenticated_client):
        resp = authenticated_client.get("/api/v2/solve/analytics/compare?ids=exe_nonexistent")
        assert resp.status_code == 200
        assert resp.json()["executions"] == []

    def test_compare_response_shape(self, authenticated_client, db_session, test_organization):
        exe = _create_execution(db_session, test_organization.id)
        db_session.commit()

        resp = authenticated_client.get(f"/api/v2/solve/analytics/compare?ids={exe.id}")
        item = resp.json()["executions"][0]
        required_keys = {
            "id",
            "status",
            "solver_status",
            "objective_value",
            "execution_time_ms",
            "credits_consumed",
            "created_at",
            "origin",
            "num_variables",
            "num_constraints",
            "gap",
        }
        assert required_keys.issubset(item.keys())

    def test_compare_no_auth(self, client):
        resp = client.get("/api/v2/solve/analytics/compare?ids=exe_1")
        assert resp.status_code == 401

    def test_compare_rejects_over_10_ids(self, authenticated_client):
        ids = ",".join(f"exe_{i:016d}" for i in range(11))
        resp = authenticated_client.get(f"/api/v2/solve/analytics/compare?ids={ids}")
        assert resp.status_code == 422
        assert "10" in resp.json()["detail"]

    def test_compare_missing_ids_param(self, authenticated_client):
        resp = authenticated_client.get("/api/v2/solve/analytics/compare")
        assert resp.status_code == 422
