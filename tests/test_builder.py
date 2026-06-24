"""
Tests for the builder CRUD API (/api/v2/builder).

Covers:
- Create document — happy path (bld_ prefix, default name)
- Create document with custom name
- List documents — returns only org's active docs
- Get document by ID — happy path
- Get document — 404 for wrong org
- Get document — 404 for deleted document
- Update document name
- Update document canvas_json
- Update document model_json
- Partial update (unset fields unchanged)
- Delete document (soft delete — is_active=False)
- Delete document — subsequent GET returns 404
- Multi-tenancy boundary: org2 cannot access org1's documents
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.models.builder_document import ModelBuilderDocument
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from tests._helpers.anti_oracle import (
    assert_cross_tenant_404_anti_oracle,
    assert_cross_tenant_404_anti_oracle_write,
)


def _create_doc(
    db: Session,
    org: Organization,
    user: User,
    name: str = "Test Document",
    canvas_json: dict | None = None,
    model_json: dict | None = None,
    is_active: bool = True,
) -> ModelBuilderDocument:
    """Insert a builder document directly into the DB for test setup."""
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=org.id,
        created_by=user.id,
        name=name,
        canvas_json=canvas_json or {},
        model_json=model_json,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


class TestCreateDocument:
    def test_create_returns_201(self, authenticated_client: TestClient):
        """POST /builder creates a document and returns 201."""
        response = authenticated_client.post("/api/v2/builder/", json={})
        assert response.status_code == 201

    def test_create_default_name(self, authenticated_client: TestClient):
        """Default name should be 'Untitled Model' when not supplied."""
        response = authenticated_client.post("/api/v2/builder/", json={})
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Untitled Model"

    def test_create_bld_prefix(self, authenticated_client: TestClient):
        """Created document ID should start with 'bld_'."""
        response = authenticated_client.post("/api/v2/builder/", json={})
        assert response.status_code == 201
        assert response.json()["id"].startswith("bld_")

    def test_create_custom_name(self, authenticated_client: TestClient):
        """Custom name should be stored and returned."""
        response = authenticated_client.post("/api/v2/builder/", json={"name": "My Routing Model"})
        assert response.status_code == 201
        assert response.json()["name"] == "My Routing Model"

    def test_create_canvas_json_defaults_to_empty(self, authenticated_client: TestClient):
        """canvas_json should default to an empty dict."""
        response = authenticated_client.post("/api/v2/builder/", json={})
        assert response.status_code == 201
        assert response.json()["canvas_json"] == {}

    def test_create_model_json_defaults_to_null(self, authenticated_client: TestClient):
        """model_json should default to None."""
        response = authenticated_client.post("/api/v2/builder/", json={})
        assert response.status_code == 201
        assert response.json()["model_json"] is None

    def test_create_sets_is_active(self, authenticated_client: TestClient):
        """Newly created document should be active."""
        response = authenticated_client.post("/api/v2/builder/", json={})
        assert response.status_code == 201
        assert response.json()["is_active"] is True

    def test_create_returns_timestamps(self, authenticated_client: TestClient):
        """Response should include created_at and updated_at fields."""
        response = authenticated_client.post("/api/v2/builder/", json={})
        assert response.status_code == 201
        data = response.json()
        assert "created_at" in data
        assert "updated_at" in data

    def test_create_returns_org_and_user_ids(
        self,
        authenticated_client: TestClient,
        test_organization: Organization,
        test_user: User,
    ):
        """Response should include organization_id and created_by."""
        response = authenticated_client.post("/api/v2/builder/", json={})
        assert response.status_code == 201
        data = response.json()
        assert data["organization_id"] == test_organization.id
        assert data["created_by"] == test_user.id


class TestListDocuments:
    def test_list_returns_200(self, authenticated_client: TestClient):
        """GET /builder should return 200."""
        response = authenticated_client.get("/api/v2/builder/")
        assert response.status_code == 200

    def test_list_returns_only_org_docs(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """List should return documents belonging to the authenticated org."""
        doc = _create_doc(db_session, test_organization, test_user, name="Org1 Doc")
        response = authenticated_client.get("/api/v2/builder/")
        assert response.status_code == 200
        ids = [d["id"] for d in response.json()]
        assert doc.id in ids

    def test_list_excludes_deleted_docs(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Soft-deleted documents should not appear in list."""
        deleted_doc = _create_doc(
            db_session, test_organization, test_user, name="Gone", is_active=False
        )
        response = authenticated_client.get("/api/v2/builder/")
        assert response.status_code == 200
        ids = [d["id"] for d in response.json()]
        assert deleted_doc.id not in ids

    def test_list_returns_list_schema(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Each list item should have id, name, created_at, updated_at fields."""
        _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.get("/api/v2/builder/")
        assert response.status_code == 200
        items = response.json()
        assert len(items) >= 1
        item = items[0]
        assert "id" in item
        assert "name" in item
        assert "created_at" in item
        assert "updated_at" in item
        # List schema should NOT include heavy canvas_json / model_json
        assert "canvas_json" not in item
        assert "model_json" not in item


class TestGetDocument:
    def test_get_returns_200(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /builder/{id} should return 200 for a valid owned doc."""
        doc = _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 200

    def test_get_returns_full_schema(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET should return the full document including canvas_json and model_json."""
        doc = _create_doc(
            db_session,
            test_organization,
            test_user,
            canvas_json={"nodes": [], "edges": []},
        )
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == doc.id
        assert data["canvas_json"] == {"nodes": [], "edges": []}

    def test_get_returns_404_for_unknown_id(self, authenticated_client: TestClient):
        """Should return 404 when document does not exist."""
        response = authenticated_client.get("/api/v2/builder/bld_nonexistent0000")
        assert response.status_code == 404

    def test_get_returns_404_for_deleted_doc(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Soft-deleted documents should return 404."""
        doc = _create_doc(db_session, test_organization, test_user, is_active=False)
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 404

    def test_get_returns_404_anti_oracle_for_wrong_org(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """TA-08 + TH-01: cross-tenant GET 404 must be byte-identical to genuine 404.

        Strengthens the prior status-only test to a Tier-5 anti-oracle
        invariant: the response body's ``detail`` field for a cross-tenant
        GET must equal the ``detail`` for a no-such-id GET on the same
        endpoint. Any divergence (e.g. "Builder document not found in this
        org" vs. "Builder document not found") leaks tenant existence and
        violates OWASP A01 (IDOR).

        Resolves TH-01 honesty naming: the test now matches what it
        actually verifies (anti-oracle, not status-only). Plan 03 STRENGTHEN
        path per CONTEXT D-04 / 12.2-04-th-list.md.
        """
        # Setup: org_b creates a builder doc under their own tenancy.
        # authenticated_client is authenticated as test_user (org_a) — so
        # the doc id from org_b is the cross-tenant target.
        other_doc = _create_doc(db_session, test_organization_2, test_user_2)

        assert_cross_tenant_404_anti_oracle(
            authenticated_client,
            endpoint_template="/api/v2/builder/{id}",
            cross_tenant_resource_id=other_doc.id,
        )


class TestUpdateDocument:
    def test_update_name(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PUT should update the name field."""
        doc = _create_doc(db_session, test_organization, test_user, name="Old Name")
        response = authenticated_client.put(f"/api/v2/builder/{doc.id}", json={"name": "New Name"})
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_update_canvas_json(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PUT should update canvas_json independently of other fields."""
        doc = _create_doc(db_session, test_organization, test_user)
        new_canvas = {"nodes": [{"id": "n1"}], "edges": [], "viewport": {"x": 0, "y": 0}}
        response = authenticated_client.put(
            f"/api/v2/builder/{doc.id}", json={"canvas_json": new_canvas}
        )
        assert response.status_code == 200
        assert response.json()["canvas_json"] == new_canvas

    def test_update_model_json(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PUT should update model_json independently of other fields."""
        doc = _create_doc(db_session, test_organization, test_user)
        model = {"name": "knapsack", "variables": [], "constraints": []}
        response = authenticated_client.put(f"/api/v2/builder/{doc.id}", json={"model_json": model})
        assert response.status_code == 200
        assert response.json()["model_json"] == model

    def test_update_does_not_overwrite_unset_fields(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Updating only name should not reset canvas_json."""
        canvas = {"nodes": [{"id": "preserved"}], "edges": []}
        doc = _create_doc(db_session, test_organization, test_user, canvas_json=canvas)
        response = authenticated_client.put(f"/api/v2/builder/{doc.id}", json={"name": "Renamed"})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Renamed"
        assert data["canvas_json"] == canvas  # unchanged

    def test_update_returns_404_anti_oracle_for_wrong_org(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """SC4: cross-tenant PUT /api/v2/builder/{id} returns 404 with anti-oracle detail.

        Promotes the prior status-only test to a Tier-5 anti-oracle
        invariant via the helper (D-09 Path B). Closes WEAK cell from
        12.4-01-cross-tenant-scaffold.md row 3 (builder_document PUT).
        """
        other_doc = _create_doc(db_session, test_organization_2, test_user_2)
        assert_cross_tenant_404_anti_oracle_write(
            authenticated_client,
            method="put",
            endpoint_template="/api/v2/builder/{id}",
            cross_tenant_resource_id=other_doc.id,
            body={"name": "Hacked"},
        )


class TestDeleteDocument:
    def test_delete_returns_204(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """DELETE should return 204 No Content on success."""
        doc = _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.delete(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 204

    def test_delete_sets_is_active_false(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Document should remain in DB with is_active=False after delete."""
        doc = _create_doc(db_session, test_organization, test_user)
        authenticated_client.delete(f"/api/v2/builder/{doc.id}")

        db_session.expire(doc)
        db_session.refresh(doc)
        assert doc.is_active is False

    def test_delete_subsequent_get_returns_404(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """After soft-delete, GET on the same document should return 404."""
        doc = _create_doc(db_session, test_organization, test_user)
        authenticated_client.delete(f"/api/v2/builder/{doc.id}")
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 404

    def test_delete_returns_404_anti_oracle_for_wrong_org(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """SC4: cross-tenant DELETE /api/v2/builder/{id} returns 404 with anti-oracle detail.

        Promotes the prior status-only check to a Tier-5 anti-oracle
        invariant via the helper (D-09 Path B). Closes WEAK cell from
        12.4-01-cross-tenant-scaffold.md row 3 (builder_document DELETE).
        """
        other_doc = _create_doc(db_session, test_organization_2, test_user_2)
        assert_cross_tenant_404_anti_oracle_write(
            authenticated_client,
            method="delete",
            endpoint_template="/api/v2/builder/{id}",
            cross_tenant_resource_id=other_doc.id,
        )
