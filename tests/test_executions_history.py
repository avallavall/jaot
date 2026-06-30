"""Fix-wave (2026-06-30): the global executions history resolves a studio model's name.

A studio solve goes through the universal async path and records its provenance as
``source_kind="model_project"`` + ``source_id=<mp_id>`` (and the typed
``model_project_id``). The history list endpoint must batch-resolve that into a human
model name so the table shows a name instead of an opaque id / generic "open source".
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ModelExecution
from app.models.model_project import ModelProject


def _project(db: Session, org_id: str, name: str = "Fleet Dispatch") -> ModelProject:
    project = ModelProject(organization_id=org_id, name=name, status="active")
    db.add(project)
    db.flush()
    return project


def test_all_executions_resolves_model_project_name(
    authenticated_client: TestClient, db_session: Session, test_organization
):
    project = _project(db_session, test_organization.id)
    db_session.add(
        ModelExecution(
            id="exe_hist_name_test",
            organization_id=test_organization.id,
            status="completed",
            input_data={},
            origin="visual_builder",
            source_kind="model_project",
            source_id=project.id,
        )
    )
    db_session.commit()

    resp = authenticated_client.get("/api/v2/models/executions/all")
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["items"] if r["id"] == "exe_hist_name_test")
    assert row["model_name"] == "Fleet Dispatch"
    assert row["source_kind"] == "model_project"


def test_all_executions_resolves_via_typed_model_project_id(
    authenticated_client: TestClient, db_session: Session, test_organization
):
    # A run that carries only the typed column (no source_kind) must still resolve.
    project = _project(db_session, test_organization.id, name="Typed Project")
    db_session.add(
        ModelExecution(
            id="exe_hist_typed_test",
            organization_id=test_organization.id,
            status="completed",
            input_data={},
            origin="visual_builder",
            model_project_id=project.id,
        )
    )
    db_session.commit()

    rows = authenticated_client.get("/api/v2/models/executions/all").json()["items"]
    row = next(r for r in rows if r["id"] == "exe_hist_typed_test")
    assert row["model_name"] == "Typed Project"


def test_all_executions_without_model_has_no_name(
    authenticated_client: TestClient, db_session: Session, test_organization
):
    # A bare /solve run (no model behind it) leaves model_name null — no crash.
    db_session.add(
        ModelExecution(
            id="exe_hist_bare_test",
            organization_id=test_organization.id,
            status="completed",
            input_data={},
            origin="api",
        )
    )
    db_session.commit()

    rows = authenticated_client.get("/api/v2/models/executions/all").json()["items"]
    row = next(r for r in rows if r["id"] == "exe_hist_bare_test")
    assert row["model_name"] is None
