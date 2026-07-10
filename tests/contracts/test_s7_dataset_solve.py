"""ADR-007 S7 — server-side scenario solve (compile ``dsl_source`` + dataset on the server).

``POST /projects/{id}/datasets/{dataset_id}/solve`` replaces the browser-side
compile-and-upload launch (~31MB payloads for the large TFM scenarios): the
server compiles the persisted JModel source against the named dataset and rides
the ONE async enqueue path with the exact provenance the old launch produced.
"""

import pytest

from app.models import ModelExecution
from app.services.platform_settings_service import PlatformSettingsService as PSS

PARAMETRIC_SOURCE = """
set I;
param w{I};
var x{I} binary;
maximize total: sum{i in I} w[i] * x[i];
subject to cap: sum{i in I} x[i] <= 1;
"""

DATASET_JSON = {"sets": {"I": ["a", "b"]}, "params": {"w": {"a": 2, "b": 3}}}
# Declares I but never fills w -> structured compile error, never a charge.
INCOMPLETE_DATASET_JSON = {"sets": {"I": ["a", "b"]}, "params": {}}


@pytest.fixture
def enable_dsl(db_session):
    """Turn JAOT_DSL ON for a single test, then restore OFF."""
    PSS.set(db_session, "JAOT_DSL", "true")
    db_session.commit()
    yield
    PSS.set(db_session, "JAOT_DSL", "false")
    db_session.commit()


def _seed_project(client, db_session, *, source: str | None = PARAMETRIC_SOURCE) -> str:
    """Create a project and persist its JModel draft source. Returns the id."""
    pid = client.post("/api/v2/projects", json={"name": "S7 scenario host"}).json()["id"]
    if source is not None:
        from app.models.model_project import ModelProject

        project = db_session.query(ModelProject).filter(ModelProject.id == pid).first()
        project.draft_dsl_source = source
        db_session.commit()
    return pid


def _seed_dataset(client, project_id: str, data=None, name: str = "scenario 1") -> str:
    resp = client.post(
        f"/api/v2/projects/{project_id}/datasets",
        json={"name": name, "data_json": data or DATASET_JSON},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.integration
class TestS7DatasetSolve:
    def test_solves_server_side_with_full_provenance(
        self, authenticated_client, db_session, test_organization, enable_dsl
    ):
        """# CONTRACT-TEST: ADR-007 S7 — server compiles source+dataset and the run
        carries the same provenance the browser-side launch produced (origin
        visual_builder, model_project source, S1 dataset snapshot, typed column)."""
        pid = _seed_project(authenticated_client, db_session)
        dsid = _seed_dataset(authenticated_client, pid)

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/datasets/{dsid}/solve")

        assert resp.status_code == 200, resp.text
        envelope = resp.json()
        assert envelope["task_id"], envelope
        execution_id = envelope["execution_id"]
        assert execution_id.startswith("exe_"), envelope

        # Row provenance is stamped at enqueue (insert_pending) — the eager
        # worker ran BEFORE the row existed (the insert-before-enqueue reorder
        # is deferred to P1.5), so terminal status is read via the poll
        # endpoint below, exactly like the client and the §14 reconcile do.
        db_session.expire_all()
        row = db_session.query(ModelExecution).filter(ModelExecution.id == execution_id).first()
        assert row is not None
        assert row.celery_task_id == envelope["task_id"]
        assert row.origin == "visual_builder"
        assert row.source_kind == "model_project"
        assert row.source_id == pid
        assert row.model_project_id == pid  # typed column (in-org project)
        assert row.dataset_id == dsid
        assert row.dataset_name == "scenario 1"  # S1 snapshot

        status_resp = authenticated_client.get(f"/api/v2/solve/async/{envelope['task_id']}")
        assert status_resp.status_code == 200, status_resp.text
        body = status_resp.json()
        assert body["status"] == "completed", body
        solver_result = body["result"]["result"]
        assert solver_result["objective_value"] == 3.0  # pick "b" (w=3) under the <=1 cap

    def test_compile_error_is_422_and_never_charges(
        self, authenticated_client, db_session, test_organization, enable_dsl
    ):
        """# CONTRACT-TEST: a dataset that does not fill the model is a structured
        422 {message, position} resolved BEFORE any credit charge or row insert."""
        pid = _seed_project(authenticated_client, db_session)
        dsid = _seed_dataset(authenticated_client, pid, data=INCOMPLETE_DATASET_JSON)
        initial_credits = test_organization.credits_balance
        before_rows = db_session.query(ModelExecution).count()

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/datasets/{dsid}/solve")

        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "message" in detail and detail["message"], detail

        db_session.expire_all()
        assert db_session.query(ModelExecution).count() == before_rows
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == initial_credits

    def test_project_without_source_is_422(
        self, authenticated_client, db_session, test_organization, enable_dsl
    ):
        pid = _seed_project(authenticated_client, db_session, source=None)
        dsid = _seed_dataset(authenticated_client, pid)

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/datasets/{dsid}/solve")

        assert resp.status_code == 422, resp.text
        assert "JModel source" in resp.json()["detail"]

    def test_foreign_or_unknown_dataset_is_404(
        self, authenticated_client, db_session, test_organization, enable_dsl
    ):
        """# CONTRACT-TEST: the dataset is project-pinned — another project's
        dataset (or a nonexistent id) 404s without touching credits."""
        pid = _seed_project(authenticated_client, db_session)
        other_pid = _seed_project(authenticated_client, db_session)
        foreign_dsid = _seed_dataset(authenticated_client, other_pid, name="foreign")

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/datasets/{foreign_dsid}/solve")
        assert resp.status_code == 404, resp.text

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/datasets/mpd_nope/solve")
        assert resp.status_code == 404, resp.text

    def test_gate_off_is_404(self, authenticated_client, db_session, test_organization):
        """# CONTRACT-TEST: ships dark — invisible (404) while JAOT_DSL is off."""
        pid = _seed_project(authenticated_client, db_session)
        dsid = _seed_dataset(authenticated_client, pid)

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/datasets/{dsid}/solve")
        assert resp.status_code == 404, resp.text
