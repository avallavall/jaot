"""Tests for POST /solve/{execution_id}/infeasibility-analysis (P2).

The on-demand IIS endpoint runs the real SCIP adapter (registered by the autouse
conftest fixture) against a persisted INFEASIBLE execution, persists the analysis
into ``result_data``, and enforces org ownership. Auth, conversations, settings,
and executions run against the real PostgreSQL database.
"""

from app.models.optimization_model import ExecutionStatus, ModelExecution
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)
from app.shared.utils.id_generator import generate_id

INFEASIBLE_PROBLEM = OptimizationProblem(
    name="infeasible_model",
    objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x"),
    variables=[Variable(name="x", type=VariableType.CONTINUOUS, lower_bound=0)],
    constraints=[
        Constraint(name="floor", expression="x >= 10"),
        Constraint(name="ceiling", expression="x <= 5"),
    ],
).model_dump(mode="json")


def _create_infeasible_execution(
    db_session, org_id, *, solver_status="infeasible"
) -> ModelExecution:
    exe = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org_id,
        input_data=INFEASIBLE_PROBLEM,
        result_data={"solver_status": solver_status, "model": None, "objective_value": None},
        status=ExecutionStatus.COMPLETED.value,
        credits_consumed=1,
        solver_status=solver_status,
        solver_name="scip",
    )
    db_session.add(exe)
    db_session.commit()
    return exe


def _url(execution_id: str) -> str:
    return f"/api/v2/solve/{execution_id}/infeasibility-analysis"


class TestInfeasibilityAnalysisEndpoint:
    def test_happy_path_returns_iis_and_persists_it(
        self, authenticated_client, db_session, test_organization
    ):
        exe = _create_infeasible_execution(db_session, test_organization.id)

        response = authenticated_client.post(_url(exe.id))

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["method"] == "iis"
        assert sorted(body["iis_constraints"]) == ["ceiling", "floor"]
        assert body["conflict_type"] == "constraint"

        # Persisted back into result_data so the LLM endpoint can ground on it.
        db_session.expire_all()
        refreshed = db_session.query(ModelExecution).filter(ModelExecution.id == exe.id).first()
        persisted = refreshed.result_data["infeasibility_analysis"]
        assert sorted(persisted["iis_constraints"]) == ["ceiling", "floor"]

    def test_second_call_returns_cached_analysis(
        self, authenticated_client, db_session, test_organization
    ):
        exe = _create_infeasible_execution(db_session, test_organization.id)

        first = authenticated_client.post(_url(exe.id))
        second = authenticated_client.post(_url(exe.id))

        assert first.status_code == second.status_code == 200
        assert first.json()["iis_constraints"] == second.json()["iis_constraints"]

    def test_requires_auth(self, client, db_session, test_organization):
        exe = _create_infeasible_execution(db_session, test_organization.id)
        response = client.post(_url(exe.id))
        assert response.status_code == 401

    def test_cross_org_execution_is_not_found(
        self, authenticated_client, db_session, test_organization_2
    ):
        foreign = _create_infeasible_execution(db_session, test_organization_2.id)
        response = authenticated_client.post(_url(foreign.id))
        assert response.status_code == 404

    def test_missing_execution_is_not_found(self, authenticated_client):
        response = authenticated_client.post(_url("exe_does_not_exist"))
        assert response.status_code == 404

    def test_non_infeasible_execution_returns_422(
        self, authenticated_client, db_session, test_organization
    ):
        exe = _create_infeasible_execution(
            db_session, test_organization.id, solver_status="optimal"
        )
        response = authenticated_client.post(_url(exe.id))
        assert response.status_code == 422
