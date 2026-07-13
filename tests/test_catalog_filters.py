"""
Tests for the catalog rating filter parameter (MKT-09; price filters died with ADR-008).

Tests the min_rating query parameter added to GET /api/v2/models/catalog, served from
the unified ``ModelProjectListing`` facet (P1.5 fusion).
"""

from app.models import ModelCategory, ModelProject, ModelProjectListing


def _make_listing(db, org, *, pid, avg_rating) -> None:
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Model " + pid,
            description="Test",
            category=ModelCategory.GENERAL.value,
            generator_type="generic",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_public=True,
            avg_rating=avg_rating,
        )
    )
    db.commit()


class TestCatalogRatingFilter:
    """Tests for minimum rating filter on catalog endpoint."""

    def test_min_rating_filter(self, authenticated_client, db_session, test_organization):
        """Catalog filters models by minimum rating."""
        for i, rating in enumerate([1.0, 2.5, 3.5, 4.8]):
            _make_listing(db_session, test_organization, pid=f"rating_test_{i}", avg_rating=rating)

        response = authenticated_client.get("/api/v2/models/catalog?min_rating=3")
        assert response.status_code == 200
        items = response.json()["items"]
        assert all(item["avg_rating"] >= 3 for item in items)

    def test_min_rating_with_no_rating_excluded(
        self, authenticated_client, db_session, test_organization
    ):
        """Models with no rating are excluded when min_rating is set."""
        _make_listing(db_session, test_organization, pid="rated_model", avg_rating=4.0)
        _make_listing(db_session, test_organization, pid="unrated_model", avg_rating=None)

        response = authenticated_client.get("/api/v2/models/catalog?min_rating=3")
        assert response.status_code == 200
        items = response.json()["items"]
        ids = [item["id"] for item in items]
        assert "rated_model" in ids
        assert "unrated_model" not in ids
