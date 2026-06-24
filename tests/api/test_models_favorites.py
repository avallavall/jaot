"""
Tests for Favorites and Recents API.

These tests verify the favorites/recents functionality:
- Adding/removing favorites
- Listing favorites
- Getting favorite status
- Listing recent models
"""

from app.models import ModelCatalog, ModelCategory, UserFavorite


class TestFavoritesList:
    """Tests for GET /api/v2/models/favorites"""

    def test_list_favorites_with_favorites(self, authenticated_client, db_session):
        """Test listing favorites by adding one first."""
        model = ModelCatalog(
            id="test_fav_catalog_model",
            name="fav_catalog_model",
            display_name="Favorite Catalog Model",
            description="A model to favorite",
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

        # Add to favorites via API (this uses the authenticated user)
        add_response = authenticated_client.post("/api/v2/models/favorites/test_fav_catalog_model")
        assert add_response.status_code == 200

        # Now list favorites
        response = authenticated_client.get("/api/v2/models/favorites")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        model_ids = [s["id"] for s in data["items"]]
        assert "test_fav_catalog_model" in model_ids


class TestAddFavorite:
    """Tests for POST /api/v2/models/favorites/{model_id}"""

    def test_add_favorite(self, authenticated_client, db_session, test_user):
        """Test adding a model to favorites."""
        model = ModelCatalog(
            id="test_add_fav_model",
            name="add_fav_model",
            display_name="Add Favorite Model",
            description="A model to add to favorites",
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

        response = authenticated_client.post("/api/v2/models/favorites/test_add_fav_model")
        assert response.status_code == 200
        data = response.json()

        assert data["model_id"] == "test_add_fav_model"
        assert data["is_favorite"]

        # Verify in database
        favorite = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id, UserFavorite.model_id == "test_add_fav_model"
            )
            .first()
        )
        assert favorite is not None

    def test_add_favorite_already_favorited(self, authenticated_client, db_session, test_user):
        """Test adding already favorited model is idempotent (no duplicate row)."""
        # Create model and favorite
        model = ModelCatalog(
            id="test_already_fav_model",
            name="already_fav_model",
            display_name="Already Favorite Model",
            description="Already favorited",
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

        favorite = UserFavorite(
            user_id=test_user.id,
            model_id="test_already_fav_model",
        )
        db_session.add(favorite)
        db_session.commit()

        # Try to add again
        response = authenticated_client.post("/api/v2/models/favorites/test_already_fav_model")
        assert response.status_code == 200
        data = response.json()
        assert data["is_favorite"]

        # Idempotency: still exactly one favorite row, not two
        count = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_id == "test_already_fav_model",
            )
            .count()
        )
        assert count == 1

    def test_add_favorite_nonexistent_model(self, authenticated_client):
        """Test adding non-existent model to favorites returns 404."""
        response = authenticated_client.post("/api/v2/models/favorites/nonexistent_model")
        assert response.status_code == 404


class TestRemoveFavorite:
    """Tests for DELETE /api/v2/models/favorites/{model_id}"""

    def test_remove_favorite(self, authenticated_client, db_session, test_user):
        """Test removing a model from favorites."""
        # Create model and favorite
        model = ModelCatalog(
            id="test_remove_fav_model",
            name="remove_fav_model",
            display_name="Remove Favorite Model",
            description="To be removed from favorites",
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

        favorite = UserFavorite(
            user_id=test_user.id,
            model_id="test_remove_fav_model",
        )
        db_session.add(favorite)
        db_session.commit()

        response = authenticated_client.delete("/api/v2/models/favorites/test_remove_fav_model")
        assert response.status_code == 200
        data = response.json()

        assert data["model_id"] == "test_remove_fav_model"
        assert not data["is_favorite"]

        # Verify removed from database
        favorite = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_id == "test_remove_fav_model",
            )
            .first()
        )
        assert favorite is None

    def test_remove_favorite_not_favorited(self, authenticated_client, db_session, test_user):
        """Test removing non-favorited model is idempotent (no row left behind)."""
        response = authenticated_client.delete("/api/v2/models/favorites/some_model")
        assert response.status_code == 200
        data = response.json()
        assert data["model_id"] == "some_model"
        assert data["is_favorite"] is False
        # Idempotent removal must not have created a row as a side-effect
        assert (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_id == "some_model",
            )
            .count()
            == 0
        )


class TestFavoriteStatus:
    """Tests for GET /api/v2/models/favorites/{model_id}/status"""

    def test_get_favorite_status_true(self, authenticated_client, db_session, test_user):
        """Test getting favorite status when favorited."""
        model = ModelCatalog(
            id="test_status_fav_model",
            name="status_fav_model",
            display_name="Status Favorite Model",
            description="Check status",
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

        favorite = UserFavorite(
            user_id=test_user.id,
            model_id="test_status_fav_model",
        )
        db_session.add(favorite)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/favorites/test_status_fav_model/status")
        assert response.status_code == 200
        data = response.json()

        assert data["model_id"] == "test_status_fav_model"
        assert data["is_favorite"]

    def test_get_favorite_status_false(self, authenticated_client, db_session):
        """Test getting favorite status when not favorited."""
        response = authenticated_client.get("/api/v2/models/favorites/some_model/status")
        assert response.status_code == 200
        data = response.json()
        assert not data["is_favorite"]
