"""
Tests for Models Catalog API (Marketplace).

These tests verify the catalog/marketplace functionality:
- Listing published models
- Filtering by category, search, official status
- Getting model details and schemas
- Activating models for an organization
"""

from app.models import ModelCatalog, ModelCategory


class TestCatalogList:
    """Tests for GET /api/v2/models/catalog"""

    def test_list_catalog_with_models(self, authenticated_client, db_session):
        """Test listing catalog with published models."""
        model = ModelCatalog(
            id="test_catalog_model_1",
            name="test_model",
            display_name="Test Model",
            description="A test model for testing",
            short_description="Test model",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

        # Find our model in the list
        model_ids = [s["id"] for s in data["items"]]
        assert "test_catalog_model_1" in model_ids

    def test_list_catalog_filters_unpublished(self, authenticated_client, db_session):
        """Test that unpublished models are not listed."""
        model = ModelCatalog(
            id="test_unpublished_model",
            name="unpublished_model",
            display_name="Unpublished Model",
            description="Should not appear in catalog",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="draft",  # Not published
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog")
        assert response.status_code == 200
        data = response.json()

        model_ids = [s["id"] for s in data["items"]]
        assert "test_unpublished_model" not in model_ids

    def test_list_catalog_filter_by_category(self, authenticated_client, db_session):
        """Test filtering catalog by category."""
        # Create models in different categories
        finance_model = ModelCatalog(
            id="test_finance_model",
            name="finance_model",
            display_name="Finance Model",
            description="A finance model",
            category=ModelCategory.FINANCE,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        logistics_model = ModelCatalog(
            id="test_logistics_model",
            name="logistics_model",
            display_name="Logistics Model",
            description="A logistics model",
            category=ModelCategory.LOGISTICS,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add_all([finance_model, logistics_model])
        db_session.commit()

        # Filter by finance
        response = authenticated_client.get("/api/v2/models/catalog?category=finance")
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["category"] == "finance"

    def test_list_catalog_filter_by_official(self, authenticated_client, db_session):
        """Test filtering catalog by official status."""
        # Create official and non-official models
        official = ModelCatalog(
            id="test_official_model",
            name="official_model",
            display_name="Official Model",
            description="An official model",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=True,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(official)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog?is_official=true")
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["is_official"]

    def test_list_catalog_search(self, authenticated_client, db_session):
        """Test searching catalog by name/description."""
        model = ModelCatalog(
            id="test_searchable_model",
            name="unique_searchable_name",
            display_name="Unique Searchable Model",
            description="This model has a unique description for testing search",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog?search=unique_searchable")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        model_ids = [s["id"] for s in data["items"]]
        assert "test_searchable_model" in model_ids

    def test_list_catalog_pagination(self, authenticated_client, db_session):
        """Test catalog pagination."""
        # Create multiple models
        for i in range(5):
            model = ModelCatalog(
                id=f"test_pagination_model_{i}",
                name=f"pagination_model_{i}",
                display_name=f"Pagination Model {i}",
                description=f"Model {i} for pagination test",
                category=ModelCategory.GENERAL,
                generator_type="generic",
                input_schema={},
                input_fields=[],
                example_input={},
                version="1.0.0",
                status="published",
                is_official=False,
                is_public=True,
                price_eur=0.0,
                credits_per_execution=1,
            )
            db_session.add(model)
        db_session.commit()

        # Get first page with small page size
        response = authenticated_client.get("/api/v2/models/catalog?page=1&page_size=2")
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) <= 2


class TestCatalogDetail:
    """Tests for GET /api/v2/models/catalog/{model_id}"""

    def test_get_catalog_model_detail(self, authenticated_client, db_session):
        """Test getting details of a catalog model."""
        model = ModelCatalog(
            id="test_detail_model",
            name="detail_model",
            display_name="Detail Model",
            description="A model for detail testing",
            short_description="Detail test",
            category=ModelCategory.FINANCE,
            tags=["test", "detail"],
            generator_type="generic",
            input_schema={"type": "object"},
            input_fields=[{"name": "amount", "type": "number", "label": "Amount"}],
            example_input={"amount": 100},
            version="1.0.0",
            status="published",
            is_official=True,
            is_featured=True,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=2,
        )
        db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog/test_detail_model")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "test_detail_model"
        assert data["display_name"] == "Detail Model"
        assert data["is_official"]
        assert data["credits_per_execution"] == 2

    def test_get_catalog_model_not_found(self, authenticated_client):
        """Test getting non-existent model returns 404."""
        response = authenticated_client.get("/api/v2/models/catalog/nonexistent_model")
        assert response.status_code == 404


class TestCatalogSchema:
    """Tests for GET /api/v2/models/catalog/{model_id}/schema"""

    def test_get_catalog_model_schema(self, authenticated_client, db_session):
        """Test getting schema of a catalog model."""
        model = ModelCatalog(
            id="test_schema_model",
            name="schema_model",
            display_name="Schema Model",
            description="A model for schema testing",
            category=ModelCategory.GENERAL,
            generator_type="budget_allocation",
            input_schema={"type": "object", "properties": {"budget": {"type": "number"}}},
            input_fields=[
                {"name": "budget", "type": "number", "label": "Total Budget", "required": True}
            ],
            example_input={"budget": 10000},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog/test_schema_model/schema")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "test_schema_model"
        assert "input_fields" in data
        assert "example_input" in data
        assert data["generator_type"] == "budget_allocation"


class TestActivateModel:
    """Tests for POST /api/v2/models/catalog/{model_id}/activate"""

    def test_activate_free_model(self, authenticated_client, db_session, test_organization):
        """Test activating a free model."""
        model = ModelCatalog(
            id="test_free_activate_model",
            name="free_activate_model",
            display_name="Free Activate Model",
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
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(model)
        db_session.commit()

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
        model = ModelCatalog(
            id="test_already_activated_model",
            name="already_activated_model",
            display_name="Already Activated Model",
            description="A model that will be activated twice",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(model)
        db_session.commit()

        # First activation
        response1 = authenticated_client.post(
            "/api/v2/models/catalog/test_already_activated_model/activate", json={}
        )
        assert response1.status_code == 200

        # Second activation should fail
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
