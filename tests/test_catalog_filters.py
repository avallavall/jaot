"""
Tests for catalog price and rating filter parameters (MKT-09).

Tests the min_price, max_price, min_rating query parameters
added to GET /api/v2/models/catalog.
"""

from app.models import ModelCatalog, ModelCategory


class TestCatalogPriceFilters:
    """Tests for price range filtering on catalog endpoint."""

    def test_min_price_filter(self, authenticated_client, db_session):
        """Catalog filters models by minimum price."""
        for i, price in enumerate([0.0, 5.0, 10.0, 20.0]):
            model = ModelCatalog(
                id=f"price_test_{i}",
                name=f"price_model_{i}",
                display_name=f"Price Model {i}",
                description="Test",
                category=ModelCategory.GENERAL,
                generator_type="generic",
                input_schema={"type": "object"},
                input_fields=[],
                example_input={},
                status="published",
                is_public=True,
                price_eur=price,
                credits_per_execution=int(price),
            )
            db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog?min_price=10")
        assert response.status_code == 200
        items = response.json()["items"]
        assert all(item["price_eur"] >= 10 for item in items)

    def test_max_price_filter(self, authenticated_client, db_session):
        """Catalog filters models by maximum price."""
        for i, price in enumerate([0.0, 5.0, 10.0, 20.0]):
            model = ModelCatalog(
                id=f"maxprice_test_{i}",
                name=f"maxprice_model_{i}",
                display_name=f"MaxPrice Model {i}",
                description="Test",
                category=ModelCategory.GENERAL,
                generator_type="generic",
                input_schema={"type": "object"},
                input_fields=[],
                example_input={},
                status="published",
                is_public=True,
                price_eur=price,
                credits_per_execution=int(price),
            )
            db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog?max_price=5")
        assert response.status_code == 200
        items = response.json()["items"]
        assert all(item["price_eur"] <= 5 for item in items)

    def test_price_range_combined(self, authenticated_client, db_session):
        """Catalog filters by both min and max price."""
        for i, price in enumerate([0.0, 5.0, 10.0, 20.0]):
            model = ModelCatalog(
                id=f"range_test_{i}",
                name=f"range_model_{i}",
                display_name=f"Range Model {i}",
                description="Test",
                category=ModelCategory.GENERAL,
                generator_type="generic",
                input_schema={"type": "object"},
                input_fields=[],
                example_input={},
                status="published",
                is_public=True,
                price_eur=price,
                credits_per_execution=int(price),
            )
            db_session.add(model)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/catalog?min_price=5&max_price=10")
        assert response.status_code == 200
        items = response.json()["items"]
        assert all(5 <= item["price_eur"] <= 10 for item in items)


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
                price_eur=0,
                credits_per_execution=0,
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
            price_eur=0,
            credits_per_execution=0,
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
            price_eur=0,
            credits_per_execution=0,
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
