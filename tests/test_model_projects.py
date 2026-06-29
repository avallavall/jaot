"""Tests for the ModelProject API (/api/v2/projects) — P1a.

Covers create/get/list (org-scoped + anti-oracle 404), draft optimistic
concurrency, commit-grade versioning (required message, immutability, dedup),
and the project solve routing through SolveOrchestrator with model_project
provenance.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ModelExecution, Organization, User
from app.models.model_project import ModelProject, ModelProjectVersion
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
    # and model_project_id set, going through the single SolveOrchestrator path.
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

    def test_solve_requires_auth(self, client: TestClient, db_session: Session):
        # An unauthenticated solve against any id must 401 (no org on request state).
        resp = client.post("/api/v2/projects/mp_does_not_matter/solve")
        assert resp.status_code == 401

    def test_solve_unknown_project_404(self, authenticated_client: TestClient):
        resp = authenticated_client.post("/api/v2/projects/mp_nonexistent/solve")
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
