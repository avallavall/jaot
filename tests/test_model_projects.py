"""Tests for the ModelProject API (/api/v2/projects) — P1a.

Covers create/get/list (org-scoped + anti-oracle 404), draft optimistic
concurrency, commit-grade versioning (required message, immutability, dedup),
and the project solve riding the single async pipeline with model_project
provenance.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ModelExecution, Organization, User
from app.models.model_project import ModelProject, ModelProjectVersion
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from tests._helpers.anti_oracle import (
    assert_cross_tenant_404_anti_oracle,
    assert_cross_tenant_404_anti_oracle_write,
)

_VALID_PROBLEM = {
    "name": "tiny_lp",
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
    "objective": {"sense": "maximize", "expression": "x"},
    "constraints": [{"name": "c1", "expression": "x <= 5"}],
}


def _create_project(client: TestClient, name: str = "Test Project") -> dict:
    resp = client.post("/api/v2/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _insert_project(
    db: Session, org: Organization, user: User, name: str = "Other"
) -> ModelProject:
    project = ModelProject(organization_id=org.id, created_by=user.id, name=name, status="active")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


class TestCreateListGet:
    def test_create_returns_201_and_mp_prefix(self, authenticated_client: TestClient):
        data = _create_project(authenticated_client)
        assert data["id"].startswith("mp_")
        assert data["name"] == "Test Project"
        assert data["status"] == "active"
        assert data["committed_count"] == 0
        assert data["current_version_id"] is None

    def test_list_is_org_scoped(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        _create_project(authenticated_client, name="Mine")
        _insert_project(db_session, test_organization_2, test_user_2, name="Theirs")
        rows = authenticated_client.get("/api/v2/projects").json()
        names = {r["name"] for r in rows}
        assert "Mine" in names
        assert "Theirs" not in names

    def test_list_is_org_wide_with_creator_and_mine_filter(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        # A project created by the current user (via the API).
        _create_project(authenticated_client, name="MineModel")
        # A same-org project NOT created by the current user.
        orphan = ModelProject(
            organization_id=test_organization.id,
            created_by=None,
            name="OrgModel",
            status="active",
        )
        db_session.add(orphan)
        db_session.commit()

        # Org-wide list (default) includes both — the list is collaborative.
        all_rows = authenticated_client.get("/api/v2/projects").json()
        names = {r["name"] for r in all_rows}
        assert {"MineModel", "OrgModel"} <= names

        # Attribution is surfaced for the row the current user created.
        mine_row = next(r for r in all_rows if r["name"] == "MineModel")
        assert mine_row["created_by"] is not None
        assert mine_row["created_by_name"]

        # mine=true narrows to the current user's own models.
        mine_names = {
            r["name"] for r in authenticated_client.get("/api/v2/projects?mine=true").json()
        }
        assert "MineModel" in mine_names
        assert "OrgModel" not in mine_names

    def test_get_happy_path(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.get(f"/api/v2/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == pid

    # CONTRACT-TEST: ModelProject endpoints filter organization_id (cross-org -> 404)
    def test_get_cross_tenant_404_anti_oracle(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        other = _insert_project(db_session, test_organization_2, test_user_2)
        assert_cross_tenant_404_anti_oracle(
            authenticated_client,
            endpoint_template="/api/v2/projects/{id}",
            cross_tenant_resource_id=other.id,
        )


class TestDraft:
    def test_update_draft_bumps_lock(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["draft_lock_version"] == 1
        assert data["draft_model_json"]["name"] == "tiny_lp"
        assert data["draft_content_hash"]

    def test_stale_if_match_conflicts_409(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        # First write lands at lock 1.
        authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM}
        )
        # A second write with the stale lock 0 must 409.
        resp = authenticated_client.put(
            f"/api/v2/projects/{pid}/draft",
            json={"model_json": _VALID_PROBLEM},
            headers={"If-Match": "0"},
        )
        assert resp.status_code == 409


class TestCommit:
    def test_commit_happy_path(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM}
        )
        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "Add x and c1", "body": "first cut"}
        )
        assert resp.status_code == 201, resp.text
        v = resp.json()
        assert v["sequence"] == 1
        assert v["commit_summary"] == "Add x and c1"
        # The project HEAD now points at the committed version.
        proj = authenticated_client.get(f"/api/v2/projects/{pid}").json()
        assert proj["current_version_id"] == v["id"]
        assert proj["committed_count"] == 1

    # CONTRACT-TEST: commit rejects empty/whitespace summary
    def test_commit_rejects_blank_summary(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM}
        )
        for blank in ("", "   ", "\t\n"):
            resp = authenticated_client.post(
                f"/api/v2/projects/{pid}/commit", json={"summary": blank}
            )
            assert resp.status_code == 422, f"blank summary {blank!r} must 422"

    def test_commit_dedup_noop(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM}
        )
        v1 = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "v1"}
        ).json()
        # Committing again with no draft change returns the SAME version (no-op).
        v2 = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "no change"}
        ).json()
        assert v2["id"] == v1["id"]
        assert authenticated_client.get(f"/api/v2/projects/{pid}").json()["committed_count"] == 1

    # CONTRACT-TEST: a committed ModelProjectVersion is immutable (no API mutates/deletes it)
    def test_committed_version_is_immutable(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM}
        )
        vid = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "v1"}
        ).json()["id"]
        url = f"/api/v2/projects/{pid}/versions/{vid}"
        # The version is readable but exposes no mutate/delete verb.
        assert authenticated_client.get(url).status_code == 200
        assert (
            authenticated_client.patch(url, json={"commit_summary": "tampered"}).status_code == 405
        )
        assert authenticated_client.put(url, json={}).status_code == 405
        assert authenticated_client.delete(url).status_code == 405


class TestSolve:
    def _fund_and_arm(self, client: TestClient, db: Session, org: Organization) -> str:
        db.query(Organization).filter(Organization.id == org.id).update(
            {"credits_balance": 1_000_000}
        )
        db.commit()
        pid = _create_project(client)["id"]
        client.put(f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM})
        return pid

    # CONTRACT-TEST: a project solve persists a ModelExecution with source_kind="model_project"
    # and model_project_id set, riding the single async pipeline (_enqueue_async_solve, ADR-007 S4a).
    def test_solve_persists_model_project_provenance(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        pid = self._fund_and_arm(authenticated_client, db_session, test_organization)
        resp = authenticated_client.post(f"/api/v2/projects/{pid}/solve")
        assert resp.status_code == 200, resp.text
        execution = (
            db_session.query(ModelExecution).filter(ModelExecution.model_project_id == pid).first()
        )
        assert execution is not None
        assert execution.source_kind == "model_project"
        assert execution.source_id == pid
        assert execution.organization_id == test_organization.id
        # A draft solve carries no version id.
        assert execution.model_project_version_id is None

    # CONTRACT-TEST: solving a committed version persists the typed model_project_version_id
    # provenance (ADR-007 S4a additive fix) alongside model_project_id — the studio version
    # history + P1.5 rely on knowing which version a run came from.
    def test_solve_version_persists_version_provenance(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        pid = self._fund_and_arm(authenticated_client, db_session, test_organization)
        vid = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "v1"}
        ).json()["id"]
        resp = authenticated_client.post(f"/api/v2/projects/{pid}/solve?version_id={vid}")
        assert resp.status_code == 200, resp.text
        execution = (
            db_session.query(ModelExecution)
            .filter(ModelExecution.model_project_id == pid)
            .order_by(ModelExecution.created_at.desc())
            .first()
        )
        assert execution is not None
        assert execution.model_project_version_id == vid
        assert execution.source_kind == "model_project"

    def test_solve_requires_auth(self, client: TestClient, db_session: Session):
        # An unauthenticated solve against any id must 401 (no org on request state).
        resp = client.post("/api/v2/projects/mp_does_not_matter/solve")
        assert resp.status_code == 401

    def test_solve_unknown_project_404(self, authenticated_client: TestClient):
        resp = authenticated_client.post("/api/v2/projects/mp_nonexistent/solve")
        assert resp.status_code == 404


def _insert_execution(
    db: Session,
    org: Organization,
    *,
    status: str,
    is_async: bool = True,
    model_project_id: str | None = None,
    source_kind: str | None = None,
    source_id: str | None = None,
    celery_task_id: str | None = None,
    objective_value: float | None = None,
    created_at=None,
) -> ModelExecution:
    """Insert a ModelExecution directly so reconciliation can be tested without
    standing up Celery — the endpoint reads the persisted row, which the worker
    keeps in sync (pending -> running -> completed/failed)."""
    execution = ModelExecution(
        id=generate_id("exe_"),
        organization_id=org.id,
        input_data={"name": "tiny_lp"},
        status=status,
        is_async=is_async,
        model_project_id=model_project_id,
        source_kind=source_kind,
        source_id=source_id,
        celery_task_id=celery_task_id,
        objective_value=objective_value,
        created_at=created_at or utcnow(),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution


class TestExecutionsReconcile:
    """§14: the per-project executions endpoint is the server-side source of
    truth for reconciling a solve on workspace open."""

    def test_running_async_execution_is_returned_for_reattach(
        self, authenticated_client: TestClient, db_session: Session, test_organization: Organization
    ):
        pid = _create_project(authenticated_client)["id"]
        _insert_execution(
            db_session,
            test_organization,
            status="running",
            is_async=True,
            model_project_id=pid,
            source_kind="model_project",
            source_id=pid,
            celery_task_id="celery-task-123",
        )
        rows = authenticated_client.get(f"/api/v2/projects/{pid}/executions?limit=1").json()
        assert len(rows) == 1
        assert rows[0]["status"] == "running"
        assert rows[0]["is_async"] is True
        assert rows[0]["celery_task_id"] == "celery-task-123"

    # CONTRACT-TEST: reconcile matches the generic source_kind="model_project" provenance,
    # not only the typed model_project_id column — the studio's universal /solve/async path
    # tags executions via source_kind/source_id WITHOUT the typed column, and they MUST be found.
    def test_matches_generic_provenance_without_typed_column(
        self, authenticated_client: TestClient, db_session: Session, test_organization: Organization
    ):
        pid = _create_project(authenticated_client)["id"]
        _insert_execution(
            db_session,
            test_organization,
            status="running",
            is_async=True,
            model_project_id=None,  # /solve/async does NOT set the typed column
            source_kind="model_project",
            source_id=pid,
            celery_task_id="celery-async-xyz",
        )
        rows = authenticated_client.get(f"/api/v2/projects/{pid}/executions").json()
        assert len(rows) == 1
        assert rows[0]["celery_task_id"] == "celery-async-xyz"

    def test_terminal_execution_surfaces_objective(
        self, authenticated_client: TestClient, db_session: Session, test_organization: Organization
    ):
        pid = _create_project(authenticated_client)["id"]
        _insert_execution(
            db_session,
            test_organization,
            status="completed",
            model_project_id=pid,
            objective_value=90.0,
        )
        rows = authenticated_client.get(f"/api/v2/projects/{pid}/executions?limit=1").json()
        assert rows[0]["status"] == "completed"
        assert rows[0]["objective_value"] == 90.0

    def test_newest_first_and_limit(
        self, authenticated_client: TestClient, db_session: Session, test_organization: Organization
    ):
        pid = _create_project(authenticated_client)["id"]
        now = utcnow()
        _insert_execution(
            db_session,
            test_organization,
            status="completed",
            model_project_id=pid,
            celery_task_id="older",
            created_at=now - timedelta(minutes=5),
        )
        _insert_execution(
            db_session,
            test_organization,
            status="running",
            model_project_id=pid,
            celery_task_id="newer",
            created_at=now,
        )
        rows = authenticated_client.get(f"/api/v2/projects/{pid}/executions?limit=1").json()
        assert len(rows) == 1
        assert rows[0]["celery_task_id"] == "newer"

    def test_status_filter(
        self, authenticated_client: TestClient, db_session: Session, test_organization: Organization
    ):
        pid = _create_project(authenticated_client)["id"]
        _insert_execution(db_session, test_organization, status="completed", model_project_id=pid)
        _insert_execution(db_session, test_organization, status="running", model_project_id=pid)
        rows = authenticated_client.get(f"/api/v2/projects/{pid}/executions?status=running").json()
        assert len(rows) == 1
        assert rows[0]["status"] == "running"

    def test_empty_when_no_executions(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        assert authenticated_client.get(f"/api/v2/projects/{pid}/executions").json() == []

    # CONTRACT-TEST: per-project executions are org-scoped (cross-org -> 404, anti-oracle)
    def test_executions_cross_tenant_404_anti_oracle(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        other = _insert_project(db_session, test_organization_2, test_user_2)
        assert_cross_tenant_404_anti_oracle(
            authenticated_client,
            endpoint_template="/api/v2/projects/{id}/executions",
            cross_tenant_resource_id=other.id,
        )

    def test_does_not_leak_other_orgs_executions(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_organization_2: Organization,
    ):
        # An execution in org2 tagged with OUR project id must never surface for us:
        # the org filter precedes the provenance match.
        pid = _create_project(authenticated_client)["id"]
        _insert_execution(
            db_session,
            test_organization_2,
            status="running",
            source_kind="model_project",
            source_id=pid,
            celery_task_id="foreign",
        )
        assert authenticated_client.get(f"/api/v2/projects/{pid}/executions").json() == []


class TestArchiveAndPermanentDelete:
    """Archive (reversible) vs permanent hard-delete (irreversible, archived-only)."""

    def test_archive_then_permanent_delete_removes_project_and_versions(
        self, authenticated_client: TestClient, db_session: Session
    ):
        pid = _create_project(authenticated_client)["id"]
        authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM}
        )
        vid = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "v1"}
        ).json()["id"]

        # Archive first (reversible).
        assert authenticated_client.delete(f"/api/v2/projects/{pid}").status_code == 204
        # Then permanent delete (irreversible).
        assert (
            authenticated_client.delete(f"/api/v2/projects/{pid}?permanent=true").status_code == 204
        )
        # Project gone...
        assert authenticated_client.get(f"/api/v2/projects/{pid}").status_code == 404
        # ...and its committed versions cascade-deleted.
        assert (
            db_session.query(ModelProjectVersion).filter(ModelProjectVersion.id == vid).first()
            is None
        )

    # CONTRACT-TEST: permanent delete is refused (409) unless the project is archived first
    def test_permanent_delete_requires_archived_first(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.delete(f"/api/v2/projects/{pid}?permanent=true")
        assert resp.status_code == 409
        # The active project is untouched.
        assert authenticated_client.get(f"/api/v2/projects/{pid}").status_code == 200

    def test_archived_project_can_be_restored(self, authenticated_client: TestClient):
        pid = _create_project(authenticated_client)["id"]
        authenticated_client.delete(f"/api/v2/projects/{pid}")  # archive
        assert pid not in {p["id"] for p in authenticated_client.get("/api/v2/projects").json()}
        archived = authenticated_client.get("/api/v2/projects?status=archived").json()
        assert pid in {p["id"] for p in archived}
        # Restore via PATCH status -> active.
        authenticated_client.patch(f"/api/v2/projects/{pid}", json={"status": "active"})
        assert pid in {p["id"] for p in authenticated_client.get("/api/v2/projects").json()}

    # CONTRACT-TEST: permanent delete is org-scoped (cross-org -> 404 before the status check)
    def test_permanent_delete_cross_tenant_404(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        other = _insert_project(db_session, test_organization_2, test_user_2)
        resp = authenticated_client.delete(f"/api/v2/projects/{other.id}?permanent=true")
        assert resp.status_code == 404


class TestMultiTenancyWrite:
    def test_commit_cross_tenant_404(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        other = _insert_project(db_session, test_organization_2, test_user_2)
        assert_cross_tenant_404_anti_oracle_write(
            authenticated_client,
            method="post",
            endpoint_template="/api/v2/projects/{id}/commit",
            cross_tenant_resource_id=other.id,
            body={"summary": "x"},
        )


class TestMigrationWiring:
    def test_tables_exist_via_migration(self, db_session: Session):
        # The conftest builds the schema by running alembic to head; a successful
        # query proves the 20260629_model_projects migration created the tables.
        assert db_session.query(ModelProject).count() >= 0
        assert db_session.query(ModelProjectVersion).count() >= 0
