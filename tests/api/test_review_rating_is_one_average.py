"""A listing's rating is the average of its visible reviews, whoever changed them.

# CONTRACT-TEST: every route that changes a review leaves avg_rating equal to the visible average.

Found in the 2026-09-24 review:

- The admin delete read the ratings before its DELETE was flushed. Production
  sessions do not autoflush (the test harness does), so the deleted rating
  stayed in the average and no test could see it.
- Hiding or showing a review never recomputed the average.
- The admin leaderboard averaged each listing's average, so one review weighed
  as much as fifty, and it counted withdrawn listings.
- The review routes ignored withdrawal: a withdrawn listing still served its
  reviews to anyone and still accepted new ones.
"""

from __future__ import annotations

import pytest

from app.models import ModelCategory, ModelProject, ModelProjectListing, ModelReview, User
from app.services.author_analytics_service import AuthorAnalyticsService


def _listing(db, org, pid: str, *, status: str = "published") -> None:
    db.add(ModelProject(id=pid, organization_id=org.id, name=pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name=pid,
            description="Rating tests",
            category=ModelCategory.GENERAL.value,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status=status,
            is_public=True,
            author_organization_id=org.id,
        )
    )
    db.flush()


def _review(db, org, _user, pid: str, rid: str, rating: int) -> None:
    """One review per person per model is a database rule, so each gets its own reviewer."""
    reviewer = User(
        id=f"usr_{rid}",
        email=f"{rid}@example.com",
        name=f"Reviewer {rid}",
        organization_id=org.id,
        is_active=True,
    )
    db.add(reviewer)
    db.flush()
    db.add(
        ModelReview(
            id=rid,
            model_project_id=pid,
            user_id=reviewer.id,
            organization_id=org.id,
            rating=rating,
            is_visible=True,
        )
    )
    db.flush()


@pytest.fixture
def production_flushing(db_session):
    """Production sessions are autoflush=False. The harness's are not."""
    db_session.autoflush = False
    yield
    db_session.autoflush = True


def _avg(db, pid: str) -> float | None:
    db.expire_all()
    return db.get(ModelProjectListing, pid).avg_rating


def test_an_admin_delete_takes_the_rating_out_of_the_average(
    admin_client, db_session, test_organization, test_admin_user, production_flushing
):
    _listing(db_session, test_organization, "rate_del")
    _review(db_session, test_organization, test_admin_user, "rate_del", "rev_del_5", 5)
    _review(db_session, test_organization, test_admin_user, "rate_del", "rev_del_1", 1)
    db_session.commit()

    assert admin_client.delete("/api/v2/admin/reviews/rev_del_1").status_code == 200
    assert _avg(db_session, "rate_del") == pytest.approx(5.0)


def test_hiding_and_showing_a_review_moves_the_average(
    admin_client, db_session, test_organization, test_admin_user
):
    _listing(db_session, test_organization, "rate_hide")
    _review(db_session, test_organization, test_admin_user, "rate_hide", "rev_hide_5", 5)
    _review(db_session, test_organization, test_admin_user, "rate_hide", "rev_hide_1", 1)
    db_session.get(ModelProjectListing, "rate_hide").avg_rating = 3.0
    db_session.commit()

    url = "/api/v2/admin/reviews/rev_hide_1/visibility"
    assert admin_client.patch(url, params={"visible": "false"}).status_code == 200
    assert _avg(db_session, "rate_hide") == pytest.approx(5.0)
    assert admin_client.patch(url, params={"visible": "true"}).status_code == 200
    assert _avg(db_session, "rate_hide") == pytest.approx(3.0)


def test_the_leaderboard_averages_reviews_not_listings(
    db_session, test_organization, test_admin_user
):
    _listing(db_session, test_organization, "rate_many")
    _listing(db_session, test_organization, "rate_one")
    _listing(db_session, test_organization, "rate_gone", status="withdrawn")
    for i in range(4):
        _review(db_session, test_organization, test_admin_user, "rate_many", f"rev_m{i}", 5)
    _review(db_session, test_organization, test_admin_user, "rate_one", "rev_o", 1)
    _review(db_session, test_organization, test_admin_user, "rate_gone", "rev_g", 1)
    db_session.commit()

    board = AuthorAnalyticsService(db_session).get_author_leaderboard("30d")
    mine = next(entry for entry in board if entry.org_id == test_organization.id)
    # (4 x 5 + 1) / 5; the withdrawn listing's review does not count.
    assert mine.avg_rating == pytest.approx(4.2)


def test_a_withdrawn_listing_serves_no_reviews(client, db_session, test_organization, test_user):
    _listing(db_session, test_organization, "rate_wd", status="withdrawn")
    _review(db_session, test_organization, test_user, "rate_wd", "rev_wd", 4)
    db_session.commit()

    assert client.get("/api/v2/models/catalog/rate_wd/reviews").status_code == 404
