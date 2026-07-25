"""POST /llm/executions/{id}/explain-scenarios — plain-language reading of the L2 batch.

The explanation is the one part of the analysis a user cannot verify at a glance,
so the contract is about grounding and cost: it narrates only measured scenarios,
it is cached so a reload never re-bills, and it refuses when there is nothing
measured to narrate.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.api.v2.llm as llm_routes
from app.domains.solver import scenario_job
from app.models import ModelExecution, Organization
from app.services.llm.explanation_service import ScenarioExplanationOutcome
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

pytestmark = pytest.mark.contract

_ANALYSIS: dict[str, Any] = {
    "computed": True,
    "sense": "minimize",
    "base_objective": 900.0,
    "rhs_scenarios": [
        {
            "constraint": "demand",
            "operator": ">=",
            "direction": "relax",
            "is_equality": False,
            "rhs": 100.0,
            "rhs_new": 99.0,
            "delta": 1.0,
            "status": "computed",
            "objective_value": 894.0,
            "objective_delta": -6.0,
            "objective_delta_per_unit": -6.0,
            "improves": True,
        }
    ],
    "decision_scenarios": [
        {
            "variable": "open_a",
            "original_value": 1.0,
            "forced_value": 0.0,
            "status": "infeasible",
            "objective_value": None,
            "regret": None,
        }
    ],
    "resolves_used": 2,
    "resolves_planned": 2,
    "seconds_used": 0.4,
    "budget_seconds": 300.0,
    "partial": False,
}


def _seed(db: Session, org_id: str, *, job: dict[str, Any] | None = None) -> ModelExecution:
    execution = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org_id,
        input_data={
            "variables": [{"name": "x", "type": "continuous"}],
            "objective": {"sense": "minimize", "expression": "x"},
            "constraints": [{"name": "demand", "expression": "x >= 100"}],
        },
        result_data={"model": {"x": 100.0}, "objective_value": 900.0},
        status="completed",
        solver_status="optimal",
        objective_value=900.0,
        scenario_analysis=job,
    )
    db.add(execution)
    db.commit()
    return execution


def _completed_job(**overrides: Any) -> dict[str, Any]:
    job = {
        "status": scenario_job.STATUS_COMPLETED,
        "requested_at": utcnow().isoformat(),
        "completed_at": utcnow().isoformat(),
        "error": None,
        "result": _ANALYSIS,
    }
    job.update(overrides)
    return job


@pytest.fixture
def fake_llm(monkeypatch):
    """Stand in for Anthropic: records the grounding it was given."""
    calls: list[dict[str, Any]] = []

    async def _explain(**kwargs):
        calls.append(kwargs)
        return ScenarioExplanationOutcome(
            text="Demand is what limits you: one unit less saves **6**.",
            input_tokens=1200,
            output_tokens=80,
        )

    monkeypatch.setattr(llm_routes, "explain_scenarios", _explain)
    monkeypatch.setattr(llm_routes, "get_anthropic_client", lambda db=None: object())
    return calls


# CONTRACT-TEST: the explanation is grounded in the MEASURED scenarios — the model
# is handed the analysis itself, never asked to imagine one.
def test_it_explains_the_measured_scenarios(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    fake_llm: list[dict[str, Any]],
):
    execution = _seed(db_session, test_organization.id, job=_completed_job())

    res = authenticated_client.post(f"/api/v2/llm/executions/{execution.id}/explain-scenarios")

    assert res.status_code == 200
    assert res.json()["cached"] is False
    assert "6" in res.json()["explanation"]
    assert len(fake_llm) == 1
    passed = fake_llm[0]["analysis"]
    assert passed["rhs_scenarios"][0]["objective_delta_per_unit"] == -6.0
    assert passed["decision_scenarios"][0]["status"] == "infeasible"


# CONTRACT-TEST: a second read must NOT re-bill a model call.
def test_the_explanation_is_cached_on_the_execution(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    fake_llm: list[dict[str, Any]],
):
    execution = _seed(db_session, test_organization.id, job=_completed_job())
    url = f"/api/v2/llm/executions/{execution.id}/explain-scenarios"

    first = authenticated_client.post(url)
    second = authenticated_client.post(url)

    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["explanation"] == first.json()["explanation"]
    assert len(fake_llm) == 1  # the second call never reached the model

    db_session.expire_all()
    stored = db_session.query(ModelExecution).filter(ModelExecution.id == execution.id).first()
    assert stored.scenario_analysis["explanation"]
    assert stored.scenario_analysis["explained_at"]
    # …and caching the text did not clobber the analysis it describes.
    assert stored.scenario_analysis["result"]["base_objective"] == 900.0


def test_it_refuses_when_no_batch_has_been_run(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    fake_llm: list[dict[str, Any]],
):
    execution = _seed(db_session, test_organization.id, job=None)

    res = authenticated_client.post(f"/api/v2/llm/executions/{execution.id}/explain-scenarios")

    assert res.status_code == 422
    assert fake_llm == []


def test_it_refuses_while_the_batch_is_still_running(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    fake_llm: list[dict[str, Any]],
):
    execution = _seed(
        db_session,
        test_organization.id,
        job={
            "status": scenario_job.STATUS_RUNNING,
            "requested_at": utcnow().isoformat(),
            "budget_seconds": 300.0,
            "result": None,
        },
    )

    res = authenticated_client.post(f"/api/v2/llm/executions/{execution.id}/explain-scenarios")

    assert res.status_code == 422
    assert fake_llm == []


def test_another_orgs_execution_cannot_be_explained(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    fake_llm: list[dict[str, Any]],
):
    other = Organization(id=generate_id("org_"), name="Other", slug=f"o-{generate_id('')}")
    db_session.add(other)
    db_session.commit()
    execution = _seed(db_session, other.id, job=_completed_job())

    res = authenticated_client.post(f"/api/v2/llm/executions/{execution.id}/explain-scenarios")

    assert res.status_code == 404
    assert fake_llm == []


def test_the_explanation_needs_authentication(client: TestClient):
    res = client.post("/api/v2/llm/executions/exe_x/explain-scenarios")
    assert res.status_code == 401
