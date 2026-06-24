"""
Tests for Model Preview API.

Tests the preview endpoint that renders a model template
into an OptimizationProblem without solving it.
"""

from app.models import (
    ModelCatalog,
    ModelCategory,
    Organization,
    OrganizationModel,
)
from app.shared.utils.datetime_helpers import utcnow


class TestPreviewModel:
    """Tests for POST /api/v2/models/{model_id}/preview"""

    def test_preview_model_not_found(self, authenticated_client):
        """Test previewing non-existent model returns 404."""
        response = authenticated_client.post(
            "/api/v2/models/nonexistent_model/preview",
            json={"input_data": {}},
        )
        assert response.status_code == 404

    def test_preview_model_inactive(self, authenticated_client, db_session, test_organization):
        """Test previewing inactive model returns 404."""
        catalog = ModelCatalog(
            id="test_preview_inactive_catalog",
            name="preview_inactive",
            display_name="Preview Inactive",
            description="For preview testing",
            category=ModelCategory.GENERAL,
            generator_type="budget_allocation",
            input_schema={},
            input_fields=[
                {"name": "total_budget", "type": "number", "label": "Budget"},
                {"name": "departments", "type": "array", "label": "Departments"},
            ],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(catalog)

        org_model = OrganizationModel(
            id="test_preview_inactive_model",
            organization_id=test_organization.id,
            catalog_id="test_preview_inactive_catalog",
            is_active=False,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_preview_inactive_model/preview",
            json={"input_data": {}},
        )
        assert response.status_code == 404

    def test_preview_other_org_returns_404(
        self, authenticated_client, db_session, test_organization
    ):
        """Test previewing a model from another org returns 404."""
        other_org = Organization(
            id="some_other_org_id",
            name="Other Org",
            plan="free",
            credits_balance=0,
            created_at=utcnow(),
        )
        db_session.add(other_org)

        catalog = ModelCatalog(
            id="test_preview_other_org_catalog",
            name="preview_other_org",
            display_name="Preview Other Org",
            description="For org isolation testing",
            category=ModelCategory.GENERAL,
            generator_type="budget_allocation",
            input_schema={},
            input_fields=[
                {"name": "total_budget", "type": "number", "label": "Budget"},
            ],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(catalog)

        org_model = OrganizationModel(
            id="test_preview_other_org_model",
            organization_id="some_other_org_id",
            catalog_id="test_preview_other_org_catalog",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_preview_other_org_model/preview",
            json={"input_data": {}},
        )
        assert response.status_code == 404

    def test_preview_returns_optimization_problem(
        self, authenticated_client, db_session, test_organization
    ):
        """Test successful preview returns OptimizationProblem structure."""
        catalog = ModelCatalog(
            id="test_preview_success_catalog",
            name="preview_success",
            display_name="Preview Success",
            description="For success testing",
            category=ModelCategory.FINANCE,
            generator_type="budget_allocation",
            input_schema={},
            input_fields=[
                {"name": "total_budget", "type": "number", "label": "Budget"},
                {"name": "departments", "type": "array", "label": "Departments"},
            ],
            example_input={
                "total_budget": 100000,
                "departments": [
                    {"name": "Engineering", "min_pct": 0.2, "max_pct": 0.5},
                    {"name": "Marketing", "min_pct": 0.1, "max_pct": 0.3},
                ],
            },
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=1,
        )
        db_session.add(catalog)

        org_model = OrganizationModel(
            id="test_preview_success_model",
            organization_id=test_organization.id,
            catalog_id="test_preview_success_catalog",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_preview_success_model/preview",
            json={
                "input_data": {
                    "total_budget": 100000,
                    "departments": [
                        {"name": "Engineering", "min_pct": 0.2, "max_pct": 0.5},
                        {"name": "Marketing", "min_pct": 0.1, "max_pct": 0.3},
                    ],
                }
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Should return OptimizationProblem structure
        assert "variables" in data
        assert "objective" in data
        assert "constraints" in data
        assert isinstance(data["variables"], list)
        assert len(data["variables"]) > 0

        # Each variable should have name and type
        for var in data["variables"]:
            assert "name" in var
            assert "type" in var

    def test_preview_does_not_deduct_credits(
        self, authenticated_client, db_session, test_organization
    ):
        """Test that preview does NOT deduct credits (read-only operation)."""
        initial_credits = test_organization.credits_balance

        catalog = ModelCatalog(
            id="test_preview_no_credits_catalog",
            name="preview_no_credits",
            display_name="Preview No Credits",
            description="For credit testing",
            category=ModelCategory.FINANCE,
            generator_type="budget_allocation",
            input_schema={},
            input_fields=[
                {"name": "total_budget", "type": "number", "label": "Budget"},
                {"name": "departments", "type": "array", "label": "Departments"},
            ],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=5,
        )
        db_session.add(catalog)

        org_model = OrganizationModel(
            id="test_preview_no_credits_model",
            organization_id=test_organization.id,
            catalog_id="test_preview_no_credits_catalog",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_preview_no_credits_model/preview",
            json={
                "input_data": {
                    "total_budget": 50000,
                    "departments": [
                        {"name": "Sales", "min_pct": 0.3, "max_pct": 0.7},
                    ],
                }
            },
        )

        assert response.status_code == 200

        # Credits should be unchanged
        db_session.refresh(test_organization)
        assert test_organization.credits_balance == initial_credits
