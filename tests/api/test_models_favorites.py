"""
Tests for Favorites and Recents API (P1.5 fusion: keyed on model_project_id).

These tests verify the favorites/recents functionality:
- Adding/removing favorites
- Listing favorites
- Getting favorite status
"""

from app.models import ModelCategory, ModelProject, ModelProjectListing, UserFavorite


def _listing(db, org, *, pid) -> None:
    """A published ModelProject + its marketplace listing facet."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Model " + pid,
            description="A model for favorites tests",
            category=ModelCategory.GENERAL.value,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_public=True,
        )
    )
    db.commit()


class TestFavoritesList:
    """Tests for GET /api/v2/models/favorites"""

    def test_list_favorites_with_favorites(
        self, authenticated_client, db_session, test_organization
    ):
        """Test listing favorites by adding one first."""
        _listing(db_session, test_organization, pid="test_fav_model")

        add_response = authenticated_client.post("/api/v2/models/favorites/test_fav_model")
        assert add_response.status_code == 200

        response = authenticated_client.get("/api/v2/models/favorites")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        model_ids = [s["id"] for s in data["items"]]
        assert "test_fav_model" in model_ids


class TestAddFavorite:
    """Tests for POST /api/v2/models/favorites/{model_id}"""

    def test_add_favorite(self, authenticated_client, db_session, test_user, test_organization):
        """Test adding a model to favorites."""
        _listing(db_session, test_organization, pid="test_add_fav_model")

        response = authenticated_client.post("/api/v2/models/favorites/test_add_fav_model")
        assert response.status_code == 200
        data = response.json()

        assert data["model_id"] == "test_add_fav_model"
        assert data["is_favorite"]

        favorite = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_project_id == "test_add_fav_model",
            )
            .first()
        )
        assert favorite is not None

    def test_add_favorite_already_favorited(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """Test adding already favorited model is idempotent (no duplicate row)."""
        _listing(db_session, test_organization, pid="test_already_fav_model")
        db_session.add(
            UserFavorite(user_id=test_user.id, model_project_id="test_already_fav_model")
        )
        db_session.commit()

        response = authenticated_client.post("/api/v2/models/favorites/test_already_fav_model")
        assert response.status_code == 200
        assert response.json()["is_favorite"]

        count = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_project_id == "test_already_fav_model",
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

    def test_remove_favorite(self, authenticated_client, db_session, test_user, test_organization):
        """Test removing a model from favorites."""
        _listing(db_session, test_organization, pid="test_remove_fav_model")
        db_session.add(UserFavorite(user_id=test_user.id, model_project_id="test_remove_fav_model"))
        db_session.commit()

        response = authenticated_client.delete("/api/v2/models/favorites/test_remove_fav_model")
        assert response.status_code == 200
        data = response.json()

        assert data["model_id"] == "test_remove_fav_model"
        assert not data["is_favorite"]

        favorite = (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_project_id == "test_remove_fav_model",
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
        assert (
            db_session.query(UserFavorite)
            .filter(
                UserFavorite.user_id == test_user.id,
                UserFavorite.model_project_id == "some_model",
            )
            .count()
            == 0
        )


class TestFavoriteStatus:
    """Tests for GET /api/v2/models/favorites/{model_id}/status"""

    def test_get_favorite_status_true(
        self, authenticated_client, db_session, test_user, test_organization
    ):
        """Test getting favorite status when favorited."""
        _listing(db_session, test_organization, pid="test_status_fav_model")
        db_session.add(UserFavorite(user_id=test_user.id, model_project_id="test_status_fav_model"))
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
