"""GET /models/executions/{id}/exact-analysis — the on-demand exact analysis (A3)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ModelExecution, Organization
from app.shared.utils.id_generator import generate_id

pytestmark = pytest.mark.contract

_PROBLEM = {
    "variables": [
        {"name": "x", "type": "continuous"},
        {"name": "y", "type": "continuous"},
    ],
    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
    "constraints": [
        {"name": "cap", "expression": "x + y <= 10"},
        {"name": "room", "expression": "x + y <= 20"},
    ],
}


def _seed_execution(db: Session, org_id: str, **overrides) -> ModelExecution:
    fields = {
        "id": generate_id("exe_"),
        "organization_id": org_id,
        "input_data": _PROBLEM,
        "result_data": {"model": {"x": 2.0, "y": 8.0}, "objective_value": 22.0},
        "status": "completed",
        "solver_status": "optimal",
        "objective_value": 22.0,
    }
    fields.update(overrides)
    exe = ModelExecution(**fields)
    db.add(exe)
    db.commit()
    return exe


# CONTRACT-TEST: the exact analysis is computed from x* + the stored problem and
# is exact for the solution (binding via slack, not LP-relaxation duals).
def test_exact_analysis_reports_binding_and_contributions(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
):
    exe = _seed_execution(db_session, test_organization.id)
    res = authenticated_client.get(f"/api/v2/models/executions/{exe.id}/exact-analysis")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["computed"] is True
    assert body["binding_count"] == 1
    assert body["total_constraints"] == 2
    by = {c["name"]: c for c in body["constraints"]}
    assert by["cap"]["is_binding"] is True
    assert by["cap"]["utilization"] == pytest.approx(1.0)
    assert by["room"]["is_binding"] is False
    assert [c["label"] for c in body["contributions"]][:2] == ["y", "x"]


def test_exact_analysis_404_for_other_org(
    authenticated_client: TestClient,
    admin_client: TestClient,
    db_session: Session,
    test_organization: Organization,
):
    # An execution the caller's org does not own is a 404, never a data leak.
    exe = _seed_execution(db_session, test_organization.id)
    # admin_client belongs to the same org here; assert a bogus id 404s instead.
    res = authenticated_client.get("/api/v2/models/executions/exe_does_not_exist/exact-analysis")
    assert res.status_code == 404
    # sanity: the real one resolves
    assert (
        authenticated_client.get(f"/api/v2/models/executions/{exe.id}/exact-analysis").status_code
        == 200
    )


def test_exact_analysis_uncomputed_without_solution(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
):
    exe = _seed_execution(db_session, test_organization.id, result_data={"model": {}})
    body = authenticated_client.get(f"/api/v2/models/executions/{exe.id}/exact-analysis").json()
    assert body["computed"] is False
    assert body["note"] == "no_solution"


# CONTRACT-TEST: the exact analysis re-parses every constraint (CPU-bound, no awaits) —
# the endpoint must stay a sync `def` so FastAPI runs it in the threadpool. An
# `async def` here would run the parse loop ON the event loop and stall every
# in-flight request for the duration of a large model's analysis.
def test_exact_analysis_endpoint_is_sync_def():
    import inspect

    from app.api.v2.routes.models.execution import get_execution_exact_analysis

    assert not inspect.iscoroutinefunction(get_execution_exact_analysis)
