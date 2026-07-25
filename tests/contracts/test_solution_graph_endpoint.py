"""GET /models/executions/{id}/solution-graph — the solution drawn as a graph (v3.2)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ModelExecution, Organization
from app.shared.utils.id_generator import generate_id

pytestmark = pytest.mark.contract

# A two-vehicle routing slice: start -> load -> unload -> end, the shape the
# owner's TFM formulation produces. Index tuples arrive the way the JModel
# compiler stamps a 3-dimensional tuple set: ONE entry, three components.
_ROUTING_PROBLEM = {
    "variables": [
        {"name": "xsc_s1_c1_k1", "type": "binary", "family": "xsc", "index_tuple": ["s1_c1_k1"]},
        {"name": "xcd_c1_d1_k1", "type": "binary", "family": "xcd", "index_tuple": ["c1_d1_k1"]},
        {"name": "xde_d1_e1_k1", "type": "binary", "family": "xde", "index_tuple": ["d1_e1_k1"]},
        {"name": "xsc_s2_c2_k2", "type": "binary", "family": "xsc", "index_tuple": ["s2_c2_k2"]},
    ],
    "objective": {
        "sense": "minimize",
        "expression": "xsc_s1_c1_k1 + xcd_c1_d1_k1 + xde_d1_e1_k1 + xsc_s2_c2_k2",
    },
    "constraints": [{"name": "one", "expression": "xsc_s1_c1_k1 + xsc_s2_c2_k2 <= 2"}],
}

# No index structure at all — a perfectly healthy model that simply has no graph.
_PLAIN_PROBLEM = {
    "variables": [{"name": "total", "type": "continuous"}],
    "objective": {"sense": "minimize", "expression": "total"},
    "constraints": [{"name": "floor", "expression": "total >= 3"}],
}


def _seed(db: Session, org_id: str, problem: dict, model: dict) -> ModelExecution:
    exe = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org_id,
        input_data=problem,
        result_data={"model": model, "objective_value": sum(model.values())},
        status="completed",
        solver_status="optimal",
        objective_value=sum(model.values()),
    )
    db.add(exe)
    db.commit()
    return exe


# CONTRACT-TEST: active edges become a graph whose node LAYERS come from the flow.
# Nothing about position is invented — the model holds distances, not coordinates.
def test_active_arcs_become_a_layered_graph(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
):
    exe = _seed(
        db_session,
        test_organization.id,
        _ROUTING_PROBLEM,
        {
            "xsc_s1_c1_k1": 1.0,
            "xcd_c1_d1_k1": 1.0,
            "xde_d1_e1_k1": 1.0,
            "xsc_s2_c2_k2": 0.0,
        },
    )
    res = authenticated_client.get(f"/api/v2/models/executions/{exe.id}/solution-graph")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["computed"] is True
    assert body["active_count"] == 3
    assert body["candidate_count"] == 4  # the honest "3 of 4"
    assert body["groups"] == ["k1"]
    assert body["is_network"] is True
    assert body["layers"] == {"s1": 0, "c1": 1, "d1": 2, "e1": 3}
    edges = {(e["source"], e["target"]) for e in body["edges"]}
    assert edges == {("s1", "c1"), ("c1", "d1"), ("d1", "e1")}


# CONTRACT-TEST: "no graph here" is a 200 with computed=false, never a 404 or a
# 500. A model without an edge-shaped family is healthy, not broken, and the UI
# must be able to tell those apart to decide whether to render anything.
def test_model_without_a_graph_answers_computed_false(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
):
    exe = _seed(db_session, test_organization.id, _PLAIN_PROBLEM, {"total": 3.0})
    res = authenticated_client.get(f"/api/v2/models/executions/{exe.id}/solution-graph")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["computed"] is False
    assert body["note"]
    assert body["edges"] == []


def test_solution_activating_no_arc_answers_computed_false(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
):
    exe = _seed(
        db_session,
        test_organization.id,
        _ROUTING_PROBLEM,
        {n["name"]: 0.0 for n in _ROUTING_PROBLEM["variables"]},
    )
    res = authenticated_client.get(f"/api/v2/models/executions/{exe.id}/solution-graph")
    assert res.status_code == 200
    assert res.json()["computed"] is False


# CONTRACT-TEST: multi-tenancy. The graph exposes node labels and variable names
# straight out of someone's model, so a missing organization_id filter here would
# leak the shape of another tenant's business.
def test_404_for_another_orgs_execution(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization_2: Organization,
):
    """An execution owned by a DIFFERENT org is a 404, never a data leak."""
    exe = _seed(db_session, test_organization_2.id, _ROUTING_PROBLEM, {"xsc_s1_c1_k1": 1.0})
    res = authenticated_client.get(f"/api/v2/models/executions/{exe.id}/solution-graph")
    assert res.status_code == 404


def test_requires_auth(client: TestClient):
    res = client.get("/api/v2/models/executions/exe_whatever/solution-graph")
    assert res.status_code == 401
