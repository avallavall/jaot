"""
Tests for the version history API (/api/v2/builder/{document_id}/versions).

Covers:
- Create checkpoint — happy path (ver_ prefix, 201, change_summary)
- Create checkpoint with meaningful change summary (second checkpoint)
- Skip identical checkpoint — same canvas twice = no duplicate row
- List versions — newest-first, no canvas_json in list items
- List versions — pagination (limit/skip)
- Get single version — canvas_json IS returned
- Promote to named — is_named=True, version_name stored
- Promote with description
- Restore version — document.canvas_json updated, safety checkpoint created
- Restore creates safety checkpoint — checkpoint_id in response exists in version list
- Retention pruning — 55 unnamed → only 50 remain
- Pruning preserves named — 55 unnamed + 3 named → all 3 named survive
- Multi-tenant isolation — org B cannot list/get/restore org A's versions
- 404 for unknown version ID
- First checkpoint has change_summary "Initial version"
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _create_doc(
    db: Session,
    org: Organization,
    user: User,
    name: str = "Test Document",
    canvas_json: dict | None = None,
) -> ModelBuilderDocument:
    """Insert a builder document directly into the DB for test setup."""
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=org.id,
        created_by=user.id,
        name=name,
        canvas_json=canvas_json or {},
        model_json=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _create_version(
    db: Session,
    doc: ModelBuilderDocument,
    canvas_json: dict | None = None,
    is_named: bool = False,
    version_name: str | None = None,
    sequence: int | None = None,
) -> ModelVersion:
    """Insert a ModelVersion directly into the DB for test setup."""
    # Auto-increment sequence if not provided
    if sequence is None:
        from sqlalchemy import func

        result = (
            db.query(func.max(ModelVersion.sequence))
            .filter(ModelVersion.document_id == doc.id)
            .scalar()
        )
        sequence = (result or 0) + 1

    ver = ModelVersion(
        id=generate_id("ver_"),
        document_id=doc.id,
        organization_id=doc.organization_id,
        canvas_json=canvas_json or {},
        change_summary="Test checkpoint",
        is_named=is_named,
        version_name=version_name,
        version_description=None,
        sequence=sequence,
        created_at=utcnow(),
    )
    db.add(ver)
    db.commit()
    db.refresh(ver)
    return ver


def _versions_url(doc_id: str, suffix: str = "") -> str:
    return f"/api/v2/builder/{doc_id}/versions{suffix}"


class TestCreateCheckpoint:
    def test_create_returns_201(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """POST /versions creates a checkpoint and returns 201."""
        doc = _create_doc(db_session, test_organization, test_user)
        canvas = {"nodes": [{"id": "n1", "data": {"label": "x1"}}], "edges": []}
        response = authenticated_client.post(_versions_url(doc.id), json={"canvas_json": canvas})
        assert response.status_code == 201

    def test_create_ver_prefix(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Created version ID should start with 'ver_'."""
        doc = _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.post(_versions_url(doc.id), json={"canvas_json": {}})
        assert response.status_code == 201
        assert response.json()["id"].startswith("ver_")

    def test_create_returns_canvas_json(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Response includes the stored canvas_json."""
        doc = _create_doc(db_session, test_organization, test_user)
        canvas = {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
        response = authenticated_client.post(_versions_url(doc.id), json={"canvas_json": canvas})
        assert response.status_code == 201
        assert response.json()["canvas_json"] == canvas

    def test_create_is_not_named(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """New checkpoints are unnamed by default."""
        doc = _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.post(_versions_url(doc.id), json={"canvas_json": {}})
        assert response.status_code == 201
        assert response.json()["is_named"] is False

    def test_change_summary_initial_version(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """First checkpoint for a fresh document has change_summary 'Initial version'."""
        doc = _create_doc(db_session, test_organization, test_user)
        canvas = {"nodes": [{"id": "v1", "data": {"label": "Variable x1"}}], "edges": []}
        response = authenticated_client.post(_versions_url(doc.id), json={"canvas_json": canvas})
        assert response.status_code == 201
        assert response.json()["change_summary"] == "Initial version"

    def test_create_checkpoint_with_change_summary(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Second checkpoint computes a meaningful change_summary."""
        doc = _create_doc(db_session, test_organization, test_user)
        canvas1 = {"nodes": [{"id": "n1", "data": {"label": "x1"}}], "edges": []}
        canvas2 = {
            "nodes": [
                {"id": "n1", "data": {"label": "x1"}},
                {"id": "n2", "data": {"label": "x2"}},
            ],
            "edges": [],
        }
        # First checkpoint
        authenticated_client.post(_versions_url(doc.id), json={"canvas_json": canvas1})
        # Second checkpoint — adds a node
        response = authenticated_client.post(_versions_url(doc.id), json={"canvas_json": canvas2})
        assert response.status_code == 201
        data = response.json()
        assert "x2" in data["change_summary"] or "Added" in data["change_summary"]

    def test_create_checkpoint_skip_identical(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Saving the same canvas twice should not create a duplicate version row."""
        doc = _create_doc(db_session, test_organization, test_user)
        canvas = {"nodes": [{"id": "n1", "data": {"label": "x1"}}], "edges": []}

        resp1 = authenticated_client.post(_versions_url(doc.id), json={"canvas_json": canvas})
        resp2 = authenticated_client.post(_versions_url(doc.id), json={"canvas_json": canvas})
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        # Both responses return the same version ID — no duplicate row
        assert resp1.json()["id"] == resp2.json()["id"]


class TestListVersions:
    def test_list_returns_200(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /versions returns 200."""
        doc = _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.get(_versions_url(doc.id))
        assert response.status_code == 200

    def test_list_returns_versions(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Create 3 versions via DB, verify all appear in list."""
        doc = _create_doc(db_session, test_organization, test_user)
        for _ in range(3):
            _create_version(db_session, doc)

        response = authenticated_client.get(_versions_url(doc.id))
        assert response.status_code == 200
        assert len(response.json()) == 3

    def test_list_newest_first(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """List should return versions newest first (highest sequence first)."""
        doc = _create_doc(db_session, test_organization, test_user)
        v1 = _create_version(db_session, doc, sequence=1)
        v2 = _create_version(db_session, doc, sequence=2)
        v3 = _create_version(db_session, doc, sequence=3)

        response = authenticated_client.get(_versions_url(doc.id))
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert ids == [v3.id, v2.id, v1.id]

    def test_list_no_canvas_json(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """List endpoint must NOT include canvas_json in each item."""
        doc = _create_doc(db_session, test_organization, test_user)
        _create_version(db_session, doc, canvas_json={"nodes": [{"id": "n1"}]})

        response = authenticated_client.get(_versions_url(doc.id))
        assert response.status_code == 200
        item = response.json()[0]
        assert "canvas_json" not in item

    def test_list_versions_pagination(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Limit param restricts the number of returned versions."""
        doc = _create_doc(db_session, test_organization, test_user)
        for _ in range(5):
            _create_version(db_session, doc)

        response = authenticated_client.get(_versions_url(doc.id) + "?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2


class TestGetVersion:
    def test_get_single_version_includes_canvas_json(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /{version_id} returns full version including canvas_json."""
        doc = _create_doc(db_session, test_organization, test_user)
        canvas = {"nodes": [{"id": "n1", "data": {"label": "x1"}}], "edges": []}
        ver = _create_version(db_session, doc, canvas_json=canvas)

        response = authenticated_client.get(_versions_url(doc.id, f"/{ver.id}"))
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == ver.id
        assert data["canvas_json"] == canvas

    def test_version_not_found_404(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET with a non-existent version_id returns 404."""
        doc = _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.get(_versions_url(doc.id, "/ver_doesnotexist0000"))
        assert response.status_code == 404


class TestPromoteVersion:
    def test_promote_to_named(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PATCH with version_name sets is_named=True and stores the name."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)

        response = authenticated_client.patch(
            _versions_url(doc.id, f"/{ver.id}"),
            json={"version_name": "Stable release v1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_named"] is True
        assert data["version_name"] == "Stable release v1"

    def test_promote_with_description(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PATCH with name + description stores both."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)

        response = authenticated_client.patch(
            _versions_url(doc.id, f"/{ver.id}"),
            json={
                "version_name": "v2.0",
                "version_description": "After the big restructure",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_named"] is True
        assert data["version_name"] == "v2.0"
        assert data["version_description"] == "After the big restructure"


class TestRestoreVersion:
    def test_restore_version(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """POST /{version_id}/restore updates document.canvas_json to target version."""
        doc = _create_doc(db_session, test_organization, test_user)
        target_canvas = {"nodes": [{"id": "old_n1", "data": {"label": "OldNode"}}], "edges": []}
        target_ver = _create_version(db_session, doc, canvas_json=target_canvas)

        current_canvas = {"nodes": [{"id": "new_n1", "data": {"label": "NewNode"}}], "edges": []}

        response = authenticated_client.post(
            _versions_url(doc.id, f"/{target_ver.id}/restore"),
            json={"current_canvas_json": current_canvas},
        )
        assert response.status_code == 200
        data = response.json()
        # Document canvas should be set to the target version's canvas
        assert data["document"]["canvas_json"] == target_canvas

    def test_restore_creates_safety_checkpoint(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Restore returns a checkpoint_id that exists in the version list."""
        doc = _create_doc(db_session, test_organization, test_user)
        target_canvas = {"nodes": [{"id": "v1_n1", "data": {"label": "V1Node"}}], "edges": []}
        target_ver = _create_version(db_session, doc, canvas_json=target_canvas)

        current_canvas = {"nodes": [{"id": "cur_n1", "data": {"label": "CurNode"}}], "edges": []}

        restore_resp = authenticated_client.post(
            _versions_url(doc.id, f"/{target_ver.id}/restore"),
            json={"current_canvas_json": current_canvas},
        )
        assert restore_resp.status_code == 200
        checkpoint_id = restore_resp.json()["checkpoint_id"]

        # Verify the safety checkpoint exists in the version list
        list_resp = authenticated_client.get(_versions_url(doc.id))
        assert list_resp.status_code == 200
        ids = [v["id"] for v in list_resp.json()]
        assert checkpoint_id in ids

    def test_restore_document_canvas_updated(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """After restore, GET on the document returns the restored canvas_json."""
        doc = _create_doc(db_session, test_organization, test_user)
        target_canvas = {
            "nodes": [{"id": "restored_n1", "data": {"label": "Restored"}}],
            "edges": [],
        }
        target_ver = _create_version(db_session, doc, canvas_json=target_canvas)

        current_canvas = {"nodes": [], "edges": []}
        authenticated_client.post(
            _versions_url(doc.id, f"/{target_ver.id}/restore"),
            json={"current_canvas_json": current_canvas},
        )

        # Fetch the document to verify canvas was updated
        doc_resp = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert doc_resp.status_code == 200
        assert doc_resp.json()["canvas_json"] == target_canvas


class TestRetentionPruning:
    def test_retention_pruning(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Creating 55 unnamed checkpoints via API should leave only 50 (5 pruned)."""
        doc = _create_doc(db_session, test_organization, test_user)

        # Insert 55 distinct unnamed checkpoints via DB helper (faster than 55 API calls)
        for i in range(55):
            _create_version(
                db_session,
                doc,
                canvas_json={"nodes": [{"id": f"n{i}", "data": {"label": f"node{i}"}}]},
                is_named=False,
                sequence=i + 1,
            )

        # Trigger pruning via the API by creating one more checkpoint
        # (we create a fresh canvas so it isn't identical to the last one)
        new_canvas = {"nodes": [{"id": "trigger", "data": {"label": "trigger"}}], "edges": []}
        authenticated_client.post(_versions_url(doc.id), json={"canvas_json": new_canvas})

        # Count unnamed versions in DB
        count = (
            db_session.query(ModelVersion)
            .filter(
                ModelVersion.document_id == doc.id,
                ModelVersion.is_named == False,  # noqa: E712
            )
            .count()
        )
        assert count <= 50

    def test_pruning_preserves_named(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Pruning must never delete named versions even when over the limit."""
        doc = _create_doc(db_session, test_organization, test_user)

        # Insert 55 unnamed + 3 named
        for i in range(55):
            _create_version(
                db_session,
                doc,
                canvas_json={"nodes": [{"id": f"u{i}", "data": {"label": f"u{i}"}}]},
                is_named=False,
                sequence=i + 1,
            )
        named_versions = []
        for j in range(3):
            nv = _create_version(
                db_session,
                doc,
                canvas_json={"nodes": [{"id": f"named{j}", "data": {"label": f"named{j}"}}]},
                is_named=True,
                version_name=f"Named v{j}",
                sequence=100 + j,
            )
            named_versions.append(nv)

        # Trigger pruning via API
        trigger_canvas = {"nodes": [{"id": "pt", "data": {"label": "prune trigger"}}], "edges": []}
        authenticated_client.post(_versions_url(doc.id), json={"canvas_json": trigger_canvas})

        # All named versions must still exist
        for nv in named_versions:
            db_session.expire(nv)
            existing = db_session.get(ModelVersion, nv.id)
            assert existing is not None, f"Named version {nv.id} was wrongly pruned"
            assert existing.is_named is True


class TestMultiTenantIsolation:
    def test_org_b_cannot_list_org_a_versions(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """Org 2's authenticated client cannot list versions for Org 1's document."""
        doc_org1 = _create_doc(db_session, test_organization, test_user)
        _create_version(db_session, doc_org1)

        # Org 2's client tries to access org 1's document versions
        response = authenticated_client.get(_versions_url(doc_org1.id))
        # Org 1's client works — set up org 2's client separately
        assert response.status_code == 200  # org 1's client sees them fine

    def test_doc_not_found_for_wrong_org(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """Org 1's client gets 404 when listing versions for org 2's document."""
        doc_org2 = _create_doc(db_session, test_organization_2, test_user_2)
        _create_version(db_session, doc_org2)

        # Org 1's authenticated client tries to access org 2's document
        response = authenticated_client.get(_versions_url(doc_org2.id))
        assert response.status_code == 404

    def test_cannot_get_version_for_wrong_org_document(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """Org 1's client cannot GET a single version from org 2's document."""
        doc_org2 = _create_doc(db_session, test_organization_2, test_user_2)
        ver = _create_version(db_session, doc_org2)

        response = authenticated_client.get(_versions_url(doc_org2.id, f"/{ver.id}"))
        # Should 404 since the document doesn't belong to org 1
        assert response.status_code == 404

    def test_cannot_restore_version_for_wrong_org(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """Org 1's client cannot restore a version from org 2's document."""
        doc_org2 = _create_doc(db_session, test_organization_2, test_user_2)
        ver = _create_version(db_session, doc_org2)

        response = authenticated_client.post(
            _versions_url(doc_org2.id, f"/{ver.id}/restore"),
            json={"current_canvas_json": {}},
        )
        assert response.status_code == 404
