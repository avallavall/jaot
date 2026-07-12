"""
Tests for the catalog rating filter parameter (MKT-09; price filters died with ADR-008).

Tests the min_rating query parameter
added to GET /api/v2/models/catalog.
"""

from app.models import ModelCatalog, ModelCategory


class TestCatalogRatingFilter:
    """Tests for minimum rating filter on catalog endpoint."""

    def test_min_rating_filter(self, authenticated_client, db_session):
        """Catalog filters models by minimum rating."""
        for i, rating in enumerate([1.0, 2.5, 3.5, 4.8]):
            model = ModelCatalog(
                id=f"rating_test_{i}",
                name=f"rating_model_{i}",
                display_name=f"Rating Model {i}",
                description="Test",
                category=ModelCategory.GENERAL,
                generator_type="generic",
                input_schema={"type": "object"},
                input_fields=[],
                example_input={},
                status="published",
                is_public=True,
                avg_rating=rating,
            )
            db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog?min_rating=3")
        assert response.status_code == 200
        items = response.json()["items"]
        assert all(item["avg_rating"] >= 3 for item in items)

    def test_min_rating_with_no_rating_excluded(self, authenticated_client, db_session):
        """Models with no rating are excluded when min_rating is set."""
        model_rated = ModelCatalog(
            id="rated_model",
            name="rated",
            display_name="Rated Model",
            description="Test",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            status="published",
            is_public=True,
            avg_rating=4.0,
        )
        model_unrated = ModelCatalog(
            id="unrated_model",
            name="unrated",
            display_name="Unrated Model",
            description="Test",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            status="published",
            is_public=True,
            avg_rating=None,
        )
        db_session.add_all([model_rated, model_unrated])
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog?min_rating=3")
        assert response.status_code == 200
        items = response.json()["items"]
        ids = [item["id"] for item in items]
        assert "rated_model" in ids
        assert "unrated_model" not in ids
