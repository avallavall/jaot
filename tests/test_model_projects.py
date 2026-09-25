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

    # CONTRACT-TEST: an unknown body key is a 422, never a silent no-op.
    def test_unknown_body_key_is_422_not_silent_noop(self, authenticated_client: TestClient):
        """Measured against production (2026-08-02): ``problem=`` instead of
        ``model_json`` returned the project as if it had worked, saved NOTHING,
        and the follow-up commit sealed an empty model. A wrong argument name is
        the typical LLM mistake, and the MCP draft tool is agent-facing.
        """
        pid = _create_project(authenticated_client)["id"]
        resp = authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"problem": _VALID_PROBLEM}
        )
        assert resp.status_code == 422, resp.text
        # Nothing was saved — and nothing pretended to be.
        proj = authenticated_client.get(f"/api/v2/projects/{pid}").json()
        assert proj["draft_model_json"] is None

        # The declared key still works after the rejection.
        ok = authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM}
        )
        assert ok.status_code == 200, ok.text

        # The commit body rejects a typo the same way.
        bad_commit = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "v1", "mesage_body": "typo"}
        )
        assert bad_commit.status_code == 422, bad_commit.text

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
        pid = _create_project(client)["id"]
        client.put(f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM})
        return pid

    # CONTRACT-TEST: a project solve persists a ModelExecution with source_kind="model_project"
    # and model_project_id set, riding the single async pipeline (enqueue_async_solve, ADR-007 S4a).
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

    def test_a_solver_matrix_cell_is_not_a_run_of_the_model(
        self, authenticated_client: TestClient, db_session: Session, test_organization: Organization
    ):
        """The model's own runs only: the "Last run" line and the runs list agree.

        A matrix cell carries the project's id. The Solve tab's "Last run:
        solved · objective 18,390" showed a cell of a matrix run a minute
        earlier, while "Runs of this model" left matrix runs out (found driving
        the studio, 2026-09-24). Both read this endpoint.
        """
        from app.models import SolverComparison

        pid = _create_project(authenticated_client)["id"]
        now = utcnow()
        own = _insert_execution(
            db_session,
            test_organization,
            status="completed",
            model_project_id=pid,
            objective_value=90.0,
            created_at=now - timedelta(minutes=5),
        )
        comparison = SolverComparison(
            id=generate_id("cmp_"),
            organization_id=test_organization.id,
            model_project_id=pid,
            problem_name="QA JAOS Facility",
            time_limit_seconds=20.0,
            gap_tolerance=0.0001,
            threads=1,
            solver_names=["scip", "jaos"],
            status="completed",
        )
        db_session.add(comparison)
        db_session.flush()
        cell = ModelExecution(
            id=generate_id("exe_"),
            organization_id=test_organization.id,
            input_data={"name": "tiny_lp"},
            status="completed",
            is_async=True,
            origin="comparison",
            model_project_id=pid,
            source_kind="model_project",
            source_id=pid,
            comparison_id=comparison.id,
            solver_name="jaos",
            objective_value=18390.0,
            created_at=now,
        )
        db_session.add(cell)
        db_session.commit()

        latest = authenticated_client.get(f"/api/v2/projects/{pid}/executions?limit=1").json()
        every = authenticated_client.get(f"/api/v2/projects/{pid}/executions").json()

        assert [r["id"] for r in latest] == [own.id]
        assert cell.id not in {r["id"] for r in every}

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


class TestArchivedProjectIsReadOnly:
    """# CONTRACT-TEST: an archived project accepts no writes until it is restored.

    Archiving is this platform's soft delete, and it used to be enforced by
    nothing but the model list rendering an archived row without a link. The URL
    underneath still worked, and so did every write behind it: driving the local
    API against an archived project, a rename, a draft edit, a commit, a version
    restore, a solve and a **publish to the public marketplace** all succeeded.

    Reads stay open on purpose — the trash view has to show what is in it.
    """

    @staticmethod
    def _archived(client: TestClient) -> str:
        pid = _create_project(client)["id"]
        client.put(f"/api/v2/projects/{pid}/draft", json={"model_json": _VALID_PROBLEM})
        client.post(f"/api/v2/projects/{pid}/commit", json={"summary": "v1"})
        assert client.delete(f"/api/v2/projects/{pid}").status_code == 204
        return pid

    def test_rename_is_refused(self, authenticated_client: TestClient):
        pid = self._archived(authenticated_client)
        before = authenticated_client.get(f"/api/v2/projects/{pid}").json()["name"]

        resp = authenticated_client.patch(f"/api/v2/projects/{pid}", json={"name": "RENAMED"})

        assert resp.status_code == 409
        assert "archived" in resp.json()["detail"].lower()
        # The refusal has to leave the row alone, or a 409 would be cosmetic.
        assert authenticated_client.get(f"/api/v2/projects/{pid}").json()["name"] == before

    def test_draft_edit_is_refused_and_the_draft_is_unchanged(
        self, authenticated_client: TestClient
    ):
        pid = self._archived(authenticated_client)
        before = authenticated_client.get(f"/api/v2/projects/{pid}").json()["draft_model_json"]

        resp = authenticated_client.put(
            f"/api/v2/projects/{pid}/draft",
            json={"model_json": {**_VALID_PROBLEM, "name": "edited-while-archived"}},
        )

        assert resp.status_code == 409
        assert (
            authenticated_client.get(f"/api/v2/projects/{pid}").json()["draft_model_json"] == before
        )

    def test_commit_is_refused_and_no_version_is_written(self, authenticated_client: TestClient):
        pid = self._archived(authenticated_client)
        before = len(authenticated_client.get(f"/api/v2/projects/{pid}/versions").json())

        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "while archived"}
        )

        assert resp.status_code == 409
        assert len(authenticated_client.get(f"/api/v2/projects/{pid}/versions").json()) == before

    def test_version_restore_is_refused(self, authenticated_client: TestClient):
        pid = self._archived(authenticated_client)
        vid = authenticated_client.get(f"/api/v2/projects/{pid}/versions").json()[0]["id"]

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/versions/{vid}/restore")

        assert resp.status_code == 409

    def test_dataset_create_is_refused(self, authenticated_client: TestClient):
        pid = self._archived(authenticated_client)

        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/datasets",
            json={"name": "while-archived", "data_json": {"sets": {}, "params": {}}},
        )

        assert resp.status_code == 409

    def test_publish_to_the_marketplace_is_refused(self, authenticated_client: TestClient):
        """The worst of them: a soft-deleted model must not reach the public catalogue."""
        pid = self._archived(authenticated_client)

        resp = authenticated_client.post(
            f"/api/v2/projects/{pid}/publish",
            json={"display_name": "PUBLISHED-WHILE-ARCHIVED", "description": "a" * 60},
        )

        assert resp.status_code == 409

    def test_solve_is_refused(self, authenticated_client: TestClient):
        """A solve writes an execution row and spends the org's quota."""
        pid = self._archived(authenticated_client)

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/solve")

        assert resp.status_code == 409

    def test_reads_still_work(self, authenticated_client: TestClient):
        """The trash view lists archived projects, so reading one must not 409."""
        pid = self._archived(authenticated_client)

        assert authenticated_client.get(f"/api/v2/projects/{pid}").status_code == 200
        assert authenticated_client.get(f"/api/v2/projects/{pid}/versions").status_code == 200
        assert authenticated_client.get(f"/api/v2/projects/{pid}/datasets").status_code == 200

    def test_restore_is_the_one_patch_that_passes(self, authenticated_client: TestClient):
        """PATCH is both the rename and the restore. Only the restore may pass.

        Without this the guard would lock the door from both sides: an archived
        project could never be brought back.
        """
        pid = self._archived(authenticated_client)

        restore = authenticated_client.patch(f"/api/v2/projects/{pid}", json={"status": "active"})

        assert restore.status_code == 200
        assert restore.json()["status"] == "active"
        # And the writes are open again afterwards.
        assert (
            authenticated_client.patch(
                f"/api/v2/projects/{pid}", json={"name": "RENAMED-AFTER-RESTORE"}
            ).status_code
            == 200
        )

    def test_archive_and_permanent_delete_still_work(self, authenticated_client: TestClient):
        """The guard must not block the two steps that dispose of the project."""
        pid = self._archived(authenticated_client)

        # Archiving an already-archived project goes through DELETE, not PATCH.
        assert authenticated_client.delete(f"/api/v2/projects/{pid}").status_code == 204
        assert (
            authenticated_client.delete(f"/api/v2/projects/{pid}?permanent=true").status_code == 204
        )
        assert authenticated_client.get(f"/api/v2/projects/{pid}").status_code == 404


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


class TestAJModelEditIsWorkEvenWhenTheModelDoesNotChange:
    """# CONTRACT-TEST: restore and commit see a JModel-only edit.

    Autosave stores a JModel text edit even when it does not change the compiled
    model (broken text, a comment). Restore and commit compared the model alone,
    so restore overwrote the text without asking and commit returned the old
    HEAD as if the text were in it.
    """

    def _project_with_v1(self, client: TestClient) -> tuple[str, str]:
        pid = _create_project(client)["id"]
        client.put(
            f"/api/v2/projects/{pid}/draft",
            json={"model_json": _VALID_PROBLEM, "dsl_source": "var x;"},
        )
        v1 = client.post(f"/api/v2/projects/{pid}/commit", json={"summary": "v1"}).json()
        return pid, v1["id"]

    def test_restore_asks_before_overwriting_a_text_edit(self, authenticated_client):
        pid, v1 = self._project_with_v1(authenticated_client)
        edited = authenticated_client.put(
            f"/api/v2/projects/{pid}/draft",
            json={"dsl_source": "var x;\n# forty lines that do not compile yet"},
        )
        assert edited.status_code == 200

        refused = authenticated_client.post(f"/api/v2/projects/{pid}/versions/{v1}/restore")
        assert refused.status_code == 409
        kept = authenticated_client.get(f"/api/v2/projects/{pid}").json()
        assert "forty lines" in kept["draft_dsl_source"]

    def test_commit_records_a_text_edit(self, authenticated_client):
        pid, v1 = self._project_with_v1(authenticated_client)
        authenticated_client.put(
            f"/api/v2/projects/{pid}/draft", json={"dsl_source": "var x; # annotated"}
        )
        v2 = authenticated_client.post(
            f"/api/v2/projects/{pid}/commit", json={"summary": "annotate"}
        ).json()
        assert v2["id"] != v1
        assert v2["dsl_source"] == "var x; # annotated"


class TestAForkKeepsItsLinkAndItsSource:
    """# CONTRACT-TEST: a marketplace fork points at its listing and carries its JModel source."""

    def test_a_fork_by_the_bare_template_id_points_at_the_listing(
        self, authenticated_client, db_session, test_organization
    ):
        from app.models.model_project import ModelProjectListing

        db_session.add(
            ModelProject(id="official_knapsack", organization_id=test_organization.id, name="k")
        )
        db_session.flush()
        db_session.add(
            ModelProjectListing(
                model_project_id="official_knapsack",
                name="knapsack",
                display_name="Knapsack",
                description="The official card",
                generator_type="knapsack",
                status="published",
                is_public=True,
            )
        )
        db_session.commit()

        fork = authenticated_client.post("/api/v2/projects/from-marketplace/knapsack")
        assert fork.status_code == 201, fork.text
        stored = db_session.get(ModelProject, fork.json()["id"])
        assert stored.source_type == "marketplace"
        assert stored.source_ref == "official_knapsack"

    def test_a_fork_of_a_jmodel_model_keeps_the_source(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        from app.models.model_project import ModelProjectListing
        from app.services import model_project_service as svc

        source = svc.create_seeded(
            db_session,
            org_id=test_organization.id,
            user_id=test_user.id,
            name="Written in JModel",
            problem_json=_VALID_PROBLEM,
            dsl_source="var x in [0, 10];\nmaximize x;\nsubject to c1: x <= 5;",
            source_type="blank",
            auto_commit_summary="v1",
        )
        db_session.add(
            ModelProjectListing(
                model_project_id=source.id,
                name="jmodel-card",
                display_name="JModel card",
                description="A static listing written in JModel",
                status="published",
                is_public=True,
                pinned_version_id=source.current_version_id,
            )
        )
        db_session.commit()

        fork = authenticated_client.post(f"/api/v2/projects/from-marketplace/{source.id}")
        assert fork.status_code == 201, fork.text
        assert fork.json()["draft_dsl_source"].startswith("var x in [0, 10];")


def test_a_commit_that_loaded_the_project_before_another_commit_sees_the_new_head(
    db_engine, db_session, test_organization, test_user
):
    """# CONTRACT-TEST: commit_version reads the locked row, not the copy it loaded earlier.

    The lock query returned the identity-mapped object unchanged, so a second
    commit deduped against the HEAD it had seen before waiting, created a copy
    of the version that already held its content, and miscounted.
    """
    from sqlalchemy.orm import sessionmaker

    from app.services import model_project_service as svc

    project = svc.create_seeded(
        db_session,
        org_id=test_organization.id,
        user_id=test_user.id,
        name="Two tabs",
        problem_json=_VALID_PROBLEM,
        source_type="blank",
        auto_commit_summary="v1",
    )
    db_session.commit()

    make = sessionmaker(bind=db_engine, autoflush=False)
    tab_a, tab_b = make(), make()
    try:
        stale = tab_a.get(ModelProject, project.id)  # tab A loads before B commits
        edited = {**_VALID_PROBLEM, "constraints": [{"name": "c1", "expression": "x <= 4"}]}
        fresh = tab_b.get(ModelProject, project.id)
        svc.update_draft(tab_b, fresh, model_json=edited, expected_lock=None)
        v2 = svc.commit_version(tab_b, fresh, user_id=test_user.id, summary="v2")
        tab_b.commit()

        again = svc.commit_version(tab_a, stale, user_id=test_user.id, summary="same content")
        tab_a.commit()
        assert again.id == v2.id, "a commit of unchanged content made a new version"
        assert tab_a.get(ModelProject, project.id).committed_count == 2
    finally:
        tab_a.close()
        tab_b.close()
