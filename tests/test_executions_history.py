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


# CONTRACT-TEST: `source_id` is client-supplied on the solve request, so name/author
# resolution MUST be org-scoped — a run whose source_id points at another org's project
# must never leak that project's name or author into this org's history.
def test_all_executions_does_not_leak_cross_org_model_name(
    authenticated_client: TestClient, db_session: Session, test_organization, test_organization_2
):
    foreign = _project(db_session, test_organization_2.id, name="Secret Foreign Model")
    db_session.add(
        ModelExecution(
            id="exe_hist_crossorg_test",
            organization_id=test_organization.id,  # the run is MINE...
            status="completed",
            input_data={},
            origin="visual_builder",
            source_kind="model_project",
            source_id=foreign.id,  # ...but it names ANOTHER org's project
        )
    )
    db_session.commit()

    rows = authenticated_client.get("/api/v2/models/executions/all").json()["items"]
    row = next(r for r in rows if r["id"] == "exe_hist_crossorg_test")
    assert row["model_name"] is None
    assert row["model_author"] is None


# ---------------------------------------------------------------------------
# The DETAIL endpoint owes the same answer as the list. It did not: it served
# model_name=null and had no solver_name field at all, so the execution page —
# and the printable report generated from it — showed "—" for a model and a
# solver the list names correctly.
# ---------------------------------------------------------------------------


def test_execution_detail_resolves_model_name_like_the_list(
    authenticated_client: TestClient, db_session: Session, test_organization
):
    project = _project(db_session, test_organization.id, name="Detail Named Model")
    db_session.add(
        ModelExecution(
            id="exe_detail_name_test",
            organization_id=test_organization.id,
            status="completed",
            input_data={},
            origin="visual_builder",
            source_kind="model_project",
            source_id=project.id,
        )
    )
    db_session.commit()

    resp = authenticated_client.get("/api/v2/models/executions/exe_detail_name_test")
    assert resp.status_code == 200, resp.text
    assert resp.json()["model_name"] == "Detail Named Model"


def test_execution_detail_serves_the_solver_it_ran_with(
    authenticated_client: TestClient, db_session: Session, test_organization
):
    db_session.add(
        ModelExecution(
            id="exe_detail_solver_test",
            organization_id=test_organization.id,
            status="completed",
            input_data={},
            origin="api",
            solver_name="highs",
        )
    )
    db_session.commit()

    resp = authenticated_client.get("/api/v2/models/executions/exe_detail_solver_test")
    assert resp.status_code == 200, resp.text
    assert resp.json()["solver_name"] == "highs"


# CONTRACT-TEST: the detail endpoint resolves names org-scoped, same as the list.
def test_execution_detail_does_not_leak_cross_org_model_name(
    authenticated_client: TestClient, db_session: Session, test_organization, test_organization_2
):
    foreign = _project(db_session, test_organization_2.id, name="Secret Detail Model")
    db_session.add(
        ModelExecution(
            id="exe_detail_crossorg_test",
            organization_id=test_organization.id,
            status="completed",
            input_data={},
            origin="visual_builder",
            source_kind="model_project",
            source_id=foreign.id,
        )
    )
    db_session.commit()

    body = authenticated_client.get("/api/v2/models/executions/exe_detail_crossorg_test").json()
    assert body["model_name"] is None
    assert body["model_author"] is None
