"""
Tests for Models Catalog API (Marketplace).

P1.5 fusion: the marketplace serves from the unified ``ModelProjectListing`` facet
(browse / detail / schema). Activation still creates an ``OrganizationModel`` from a
``ModelCatalog`` row during the transition (bridge), so those tests keep using it.
"""

from app.models import ModelCatalog, ModelCategory, ModelProject, ModelProjectListing


def _make_listing(db, org, *, pid, **overrides) -> ModelProjectListing:
    """Create a published ModelProject + its marketplace listing facet."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    fields = {
        "model_project_id": pid,
        "name": pid,
        "display_name": "Model " + pid,
        "description": "A test listing for " + pid,
        "short_description": "short",
        "category": ModelCategory.GENERAL.value,
        "generator_type": "generic",
        "input_schema": {"type": "object"},
        "input_fields": [],
        "example_input": {},
        "version": "1.0.0",
        "status": "published",
        "is_official": False,
        "is_public": True,
    }
    fields.update(overrides)
    listing = ModelProjectListing(**fields)
    db.add(listing)
    db.commit()
    return listing


class TestCatalogList:
    """Tests for GET /api/v2/models/catalog"""

    def test_list_catalog_with_models(self, authenticated_client, db_session, test_organization):
        """Test listing catalog with published models."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_catalog_model_1",
            name="uniquelistingname",
            display_name="Unique Listing Name",
        )

        # Search-isolate from the seeded official listings (which crowd page 1).
        response = authenticated_client.get("/api/v2/models/catalog?search=uniquelistingname")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

        model_ids = [s["id"] for s in data["items"]]
        assert "test_catalog_model_1" in model_ids

    def test_list_catalog_filters_unpublished(
        self, authenticated_client, db_session, test_organization
    ):
        """Test that unpublished listings are not listed."""
        _make_listing(db_session, test_organization, pid="test_unpublished_model", status="draft")

        response = authenticated_client.get("/api/v2/models/catalog")
        assert response.status_code == 200
        data = response.json()

        model_ids = [s["id"] for s in data["items"]]
        assert "test_unpublished_model" not in model_ids

    def test_list_catalog_filter_by_category(
        self, authenticated_client, db_session, test_organization
    ):
        """Test filtering catalog by category."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_finance_model",
            category=ModelCategory.FINANCE.value,
        )
        _make_listing(
            db_session,
            test_organization,
            pid="test_logistics_model",
            category=ModelCategory.LOGISTICS.value,
        )

        response = authenticated_client.get("/api/v2/models/catalog?category=finance")
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["category"] == "finance"

    def test_list_catalog_filter_by_official(
        self, authenticated_client, db_session, test_organization
    ):
        """Test filtering catalog by official status."""
        _make_listing(db_session, test_organization, pid="test_official_model", is_official=True)

        response = authenticated_client.get("/api/v2/models/catalog?is_official=true")
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["is_official"]

    def test_list_catalog_search(self, authenticated_client, db_session, test_organization):
        """Test searching catalog by name/description."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_searchable_model",
            name="unique_searchable_name",
            display_name="Unique Searchable Model",
        )

        response = authenticated_client.get("/api/v2/models/catalog?search=unique_searchable")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        model_ids = [s["id"] for s in data["items"]]
        assert "test_searchable_model" in model_ids

    def test_list_catalog_pagination(self, authenticated_client, db_session, test_organization):
        """Test catalog pagination."""
        for i in range(5):
            _make_listing(db_session, test_organization, pid=f"test_pagination_model_{i}")

        response = authenticated_client.get("/api/v2/models/catalog?page=1&page_size=2")
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) <= 2


class TestCatalogDetail:
    """Tests for GET /api/v2/models/catalog/{model_id}"""

    def test_get_catalog_model_detail(self, authenticated_client, db_session, test_organization):
        """Test getting details of a catalog model."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_detail_model",
            display_name="Detail Model",
            category=ModelCategory.FINANCE.value,
            tags=["test", "detail"],
            is_official=True,
            is_featured=True,
        )

        response = authenticated_client.get("/api/v2/models/catalog/test_detail_model")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "test_detail_model"
        assert data["display_name"] == "Detail Model"
        assert data["is_official"]

    def test_get_catalog_model_not_found(self, authenticated_client):
        """Test getting non-existent model returns 404."""
        response = authenticated_client.get("/api/v2/models/catalog/nonexistent_model")
        assert response.status_code == 404


class TestCatalogSchema:
    """Tests for GET /api/v2/models/catalog/{model_id}/schema"""

    def test_get_catalog_model_schema(self, authenticated_client, db_session, test_organization):
        """Test getting schema of a catalog model."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_schema_model",
            generator_type="budget_allocation",
            input_schema={"type": "object", "properties": {"budget": {"type": "number"}}},
            input_fields=[
                {"name": "budget", "type": "number", "label": "Total Budget", "required": True}
            ],
            example_input={"budget": 10000},
        )

        response = authenticated_client.get("/api/v2/models/catalog/test_schema_model/schema")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "test_schema_model"
        assert "input_fields" in data
        assert "example_input" in data
        assert data["generator_type"] == "budget_allocation"


class TestActivateModel:
    """Tests for POST /api/v2/models/catalog/{model_id}/activate.

    Activation still resolves the legacy ``ModelCatalog`` row during the fusion
    transition (bridge) — collapsed to a seeded fork ModelProject in a later slice.
    """

    def _make_catalog(self, db, *, cid) -> ModelCatalog:
        model = ModelCatalog(
            id=cid,
            name=cid,
            display_name="Model " + cid,
            description="A free model for activation testing",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
        )
        db.add(model)
        db.commit()
        return model

    def test_activate_free_model(self, authenticated_client, db_session, test_organization):
        """Test activating a free model."""
        self._make_catalog(db_session, cid="test_free_activate_model")

        response = authenticated_client.post(
            "/api/v2/models/catalog/test_free_activate_model/activate", json={}
        )
        assert response.status_code == 200
        data = response.json()

        assert data["catalog_id"] == "test_free_activate_model"
        assert data["is_active"]

    def test_activate_model_already_activated(
        self, authenticated_client, db_session, test_organization
    ):
        """Test activating an already activated model returns error."""
        self._make_catalog(db_session, cid="test_already_activated_model")

        response1 = authenticated_client.post(
            "/api/v2/models/catalog/test_already_activated_model/activate", json={}
        )
        assert response1.status_code == 200

        response2 = authenticated_client.post(
            "/api/v2/models/catalog/test_already_activated_model/activate", json={}
        )
        assert response2.status_code == 400
        assert "already activated" in response2.json()["detail"].lower()

    def test_activate_nonexistent_model(self, authenticated_client):
        """Test activating non-existent model returns 404."""
        response = authenticated_client.post(
            "/api/v2/models/catalog/nonexistent_model/activate", json={}
        )
        assert response.status_code == 404
