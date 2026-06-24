"""
Tests for My Models API (Organization Models).

These tests verify the organization's models functionality:
- Listing organization's models
- Creating private models
- Updating models
- Deactivating models
"""

from app.models import OrganizationModel


class TestListMyModels:
    """Tests for GET /api/v2/models"""

    def test_list_my_models_with_models(self, authenticated_client, db_session, test_organization):
        """Test listing models when organization has some."""
        org_model = OrganizationModel(
            id="test_org_model_1",
            organization_id=test_organization.id,
            custom_name="My Test Model",
            is_active=True,
            total_executions=0,
            total_credits_used=0,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        model_ids = [s["id"] for s in data["items"]]
        assert "test_org_model_1" in model_ids

    def test_list_my_models_only_own_org(
        self, authenticated_client, db_session, test_organization, test_organization_2
    ):
        """Test that only models from own organization are listed."""
        # Create model for test_organization
        own_model = OrganizationModel(
            id="test_own_org_model",
            organization_id=test_organization.id,
            custom_name="Own Model",
            is_active=True,
        )
        # Create model for different organization
        other_model = OrganizationModel(
            id="test_other_org_model",
            organization_id=test_organization_2.id,
            custom_name="Other Model",
            is_active=True,
        )
        db_session.add_all([own_model, other_model])
        db_session.commit()

        response = authenticated_client.get("/api/v2/models")
        assert response.status_code == 200
        data = response.json()

        model_ids = [s["id"] for s in data["items"]]
        assert "test_own_org_model" in model_ids
        assert "test_other_org_model" not in model_ids

    def test_list_my_models_filter_active(
        self, authenticated_client, db_session, test_organization
    ):
        """Test filtering models by active status."""
        active_model = OrganizationModel(
            id="test_active_model",
            organization_id=test_organization.id,
            custom_name="Active Model",
            is_active=True,
        )
        inactive_model = OrganizationModel(
            id="test_inactive_model",
            organization_id=test_organization.id,
            custom_name="Inactive Model",
            is_active=False,
        )
        db_session.add_all([active_model, inactive_model])
        db_session.commit()

        response = authenticated_client.get("/api/v2/models?is_active=true")
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["is_active"]


class TestGetMyModel:
    """Tests for GET /api/v2/models/{model_id}"""

    def test_get_my_model(self, authenticated_client, db_session, test_organization):
        """Test getting details of own model."""
        org_model = OrganizationModel(
            id="test_get_model",
            organization_id=test_organization.id,
            custom_name="Get Test Model",
            is_active=True,
            total_executions=5,
            total_credits_used=10,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/test_get_model")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "test_get_model"
        assert data["custom_name"] == "Get Test Model"
        assert data["total_executions"] == 5

    def test_get_my_model_not_found(self, authenticated_client):
        """Test getting non-existent model returns 404."""
        response = authenticated_client.get("/api/v2/models/nonexistent_model")
        assert response.status_code == 404

    def test_get_my_model_other_org(self, authenticated_client, db_session, test_organization_2):
        """Test cannot get model from another organization."""
        other_model = OrganizationModel(
            id="test_other_org_get_model",
            organization_id=test_organization_2.id,
            custom_name="Other Org Model",
            is_active=True,
        )
        db_session.add(other_model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/test_other_org_get_model")
        assert response.status_code == 404


class TestUpdateModel:
    """Tests for PATCH /api/v2/models/{model_id}"""

    def test_update_model_custom_name(self, authenticated_client, db_session, test_organization):
        """Test updating model's custom name."""
        org_model = OrganizationModel(
            id="test_update_model",
            organization_id=test_organization.id,
            custom_name="Original Name",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.patch(
            "/api/v2/models/test_update_model", json={"custom_name": "Updated Name"}
        )
        assert response.status_code == 200

        # Verify update
        db_session.refresh(org_model)
        assert org_model.custom_name == "Updated Name"

    def test_update_model_favorite(self, authenticated_client, db_session, test_organization):
        """Test updating model's favorite status."""
        org_model = OrganizationModel(
            id="test_favorite_model",
            organization_id=test_organization.id,
            custom_name="Favorite Test",
            is_active=True,
            is_favorite=False,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.patch(
            "/api/v2/models/test_favorite_model", json={"is_favorite": True}
        )
        assert response.status_code == 200

        db_session.refresh(org_model)
        assert org_model.is_favorite

    def test_update_model_not_found(self, authenticated_client):
        """Test updating non-existent model returns 404."""
        response = authenticated_client.patch(
            "/api/v2/models/nonexistent_model", json={"custom_name": "New Name"}
        )
        assert response.status_code == 404

    def test_update_model_other_org(self, authenticated_client, db_session, test_organization_2):
        """Test cannot update model from another organization."""
        other_model = OrganizationModel(
            id="test_other_org_update",
            organization_id=test_organization_2.id,
            custom_name="Other Org Model",
            is_active=True,
        )
        db_session.add(other_model)
        db_session.commit()

        response = authenticated_client.patch(
            "/api/v2/models/test_other_org_update", json={"custom_name": "Hacked Name"}
        )
        assert response.status_code == 404


class TestDeactivateModel:
    """Tests for DELETE /api/v2/models/{model_id}"""

    def test_deactivate_model(self, authenticated_client, db_session, test_organization):
        """Test deactivating (soft delete) a model."""
        org_model = OrganizationModel(
            id="test_deactivate_model",
            organization_id=test_organization.id,
            custom_name="To Deactivate",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.delete("/api/v2/models/test_deactivate_model")
        assert response.status_code == 200

        db_session.refresh(org_model)
        assert not org_model.is_active

    def test_deactivate_model_not_found(self, authenticated_client):
        """Test deactivating non-existent model returns 404."""
        response = authenticated_client.delete("/api/v2/models/nonexistent_model")
        assert response.status_code == 404

    def test_deactivate_model_other_org(
        self, authenticated_client, db_session, test_organization_2
    ):
        """Test cannot deactivate model from another organization."""
        other_model = OrganizationModel(
            id="test_other_org_deactivate",
            organization_id=test_organization_2.id,
            custom_name="Other Org Model",
            is_active=True,
        )
        db_session.add(other_model)
        db_session.commit()

        response = authenticated_client.delete("/api/v2/models/test_other_org_deactivate")
        assert response.status_code == 404

        # Verify not deactivated
        db_session.refresh(other_model)
        assert other_model.is_active
