"""Tests for profiles API endpoints.

Tests the public profiles and reviews system including:
- Organization public profiles
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import ModelCategory, ModelProject, ModelProjectListing, ModelReview, User
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def app():
    """Create test app."""
    return create_app()


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestOrganizationProfiles:
    """Tests for organization profile endpoints."""

    def test_get_org_profile_not_found(self, client):
        """Test getting non-existent organization profile.

        Asserts 404 + JSON error payload + detail string. Verifies the
        response is a real JSON error (not an HTML 404 routing artifact).
        """
        response = client.get("/api/v2/organizations/nonexistent-org/public")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["detail"]


def _publish(db, org, pid: str) -> ModelProjectListing:
    """A published, public listing of ``org`` — what the profile counts."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    listing = ModelProjectListing(
        model_project_id=pid,
        name=pid,
        display_name="Model " + pid,
        description="A listing for " + pid,
        short_description="short",
        category=ModelCategory.GENERAL.value,
        generator_type="generic",
        input_schema={"type": "object"},
        input_fields=[],
        example_input={},
        version="1.0.0",
        status="published",
        is_official=False,
        is_public=True,
        author_organization_id=org.id,
    )
    db.add(listing)
    db.commit()
    return listing


def _review(db, org, pid: str, rating: int, *, visible: bool = True) -> ModelReview:
    """One review of ``pid``, by a reviewer of its own. ``visible=False`` is what
    moderation leaves behind: the row stays, the review stops being shown."""
    reviewer = User(
        id=generate_id("usr_"),
        email=f"{generate_id('rev')}@example.com",
        name="Reviewer",
        organization_id=org.id,
        is_active=True,
    )
    db.add(reviewer)
    db.flush()
    review = ModelReview(
        id=generate_id("rev_"),
        model_project_id=pid,
        user_id=reviewer.id,
        organization_id=org.id,
        rating=rating,
        is_visible=visible,
    )
    db.add(review)
    db.flush()
    # Production keeps a rolled-up average on the listing (``_recompute_avg_rating``
    # in profiles/reviews.py). Seed it the same way, so the fixture is the data the
    # old code read: without it the old path finds no average at all and the test
    # would pass for the wrong reason instead of on the arithmetic.
    visible_ratings = [
        r[0]
        for r in db.query(ModelReview.rating)
        .filter(
            ModelReview.model_project_id == pid,
            ModelReview.is_visible == True,  # noqa: E712
        )
        .all()
    ]
    listing = (
        db.query(ModelProjectListing).filter(ModelProjectListing.model_project_id == pid).one()
    )
    listing.avg_rating = (sum(visible_ratings) / len(visible_ratings)) if visible_ratings else None
    db.commit()
    return review


class TestOrganizationRating:
    """The headline rating of an author, and the count printed beside it."""

    # CONTRACT-TEST: an author's average rating weighs every review equally
    def test_average_weighs_reviews_not_listings(
        self, authenticated_client, db_session, test_organization
    ):
        """One listing with many reviews must not weigh the same as one with a single review.

        Listing A: four reviews of 1. Listing B: one review of 5. Each listing
        carries its own rolled-up average, 1.0 and 5.0, exactly as production
        stores it.

        Averaging the two listing averages gives (1 + 5) / 2 = 3.0 — the old
        figure. Averaging the five reviews gives (1+1+1+1+5) / 5 = 1.8, which is
        the rating of this author's work. The test fails on 3.0.
        """
        _publish(db_session, test_organization, "mp_rating_a")
        _publish(db_session, test_organization, "mp_rating_b")
        for _ in range(4):
            _review(db_session, test_organization, "mp_rating_a", 1)
        _review(db_session, test_organization, "mp_rating_b", 5)

        body = authenticated_client.get(
            f"/api/v2/organizations/{test_organization.id}/public"
        ).json()

        assert body["total_reviews"] == 5
        assert body["avg_rating"] == pytest.approx(1.8)

    # CONTRACT-TEST: the review count and the average describe the same rows
    def test_hidden_review_leaves_both_numbers(
        self, authenticated_client, db_session, test_organization
    ):
        """A review hidden by moderation counts in neither the average nor the total.

        The card prints "from N reviews" under the average. If the count keeps a
        hidden review the average does not use, the sentence names a denominator
        that produced no part of the figure above it.
        """
        _publish(db_session, test_organization, "mp_rating_hidden")
        _review(db_session, test_organization, "mp_rating_hidden", 5)
        _review(db_session, test_organization, "mp_rating_hidden", 1, visible=False)

        body = authenticated_client.get(
            f"/api/v2/organizations/{test_organization.id}/public"
        ).json()

        assert body["total_reviews"] == 1
        assert body["avg_rating"] == pytest.approx(5.0)

    def test_no_reviews_leaves_no_rating(self, authenticated_client, db_session, test_organization):
        """An author nobody has rated has no average, not a zero."""
        _publish(db_session, test_organization, "mp_rating_none")

        body = authenticated_client.get(
            f"/api/v2/organizations/{test_organization.id}/public"
        ).json()

        assert body["total_reviews"] == 0
        assert body["avg_rating"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
