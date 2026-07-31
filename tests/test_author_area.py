"""Tests for the author area: withdrawing listings, my listings, reviews received.

The author area is what an author sees about what they published: the listings
with their state, the reviews people left, and the ability to take a model off
the marketplace without losing its history.

Withdrawal is REVERSIBLE by owner decision (2026-07-31): the listing row and all
its rollups survive, and every catalog surface filters ``status == "published"``,
so a withdrawn listing is simply absent from the marketplace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models import (
    ModelProject,
    ModelProjectListing,
    ModelReview,
    Organization,
    User,
)
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

_REPO_ROOT = Path(__file__).resolve().parent.parent
_APP_ROUTES = _REPO_ROOT / "frontend" / "src" / "app" / "[locale]"


def _publish(db, *, org_id: str, pid: str | None = None, status: str = "published"):
    """Create a project owned by ``org_id`` plus its marketplace listing facet."""
    pid = pid or generate_id("mp_")
    db.add(
        ModelProject(
            id=pid,
            organization_id=org_id,
            name=f"Project {pid}",
            status="active",
            committed_count=2,
        )
    )
    db.flush()
    listing = ModelProjectListing(
        model_project_id=pid,
        name=pid,
        display_name=f"Model {pid}",
        description="A published model",
        category="linear",
        version="1.0.0",
        status=status,
        is_public=True,
        author_organization_id=org_id,
        total_activations=7,
        total_executions=11,
        published_at=utcnow(),
    )
    db.add(listing)
    db.flush()
    return listing


class TestWithdrawListing:
    """POST /projects/{id}/unpublish and /republish."""

    def test_unpublish_removes_the_listing_from_every_catalog_surface(
        self, authenticated_client, client, db_session, test_organization
    ):
        """Withdrawing hides the model from list, detail and input schema."""
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.commit()
        pid = listing.model_project_id

        assert client.get(f"/api/v2/models/catalog/{pid}").status_code == 200

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/unpublish")
        assert resp.status_code == 200, resp.text

        assert client.get(f"/api/v2/models/catalog/{pid}").status_code == 404
        assert client.get(f"/api/v2/models/catalog/{pid}/schema").status_code == 404
        listed = client.get("/api/v2/models/catalog").json()
        assert all(m["id"] != pid for m in listed["items"])

    def test_republish_puts_it_back_with_its_rollups_intact(
        self, authenticated_client, client, db_session, test_organization
    ):
        """The whole point of a reversible withdrawal: nothing is lost."""
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.commit()
        pid = listing.model_project_id

        authenticated_client.post(f"/api/v2/projects/{pid}/unpublish")
        resp = authenticated_client.post(f"/api/v2/projects/{pid}/republish")
        assert resp.status_code == 200, resp.text

        assert client.get(f"/api/v2/models/catalog/{pid}").status_code == 200
        db_session.expire_all()
        restored = (
            db_session.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id == pid)
            .one()
        )
        assert restored.status == "published"
        assert restored.total_activations == 7
        assert restored.total_executions == 11
        assert restored.published_at is not None

    def test_unpublish_is_idempotent(
        self, authenticated_client, db_session, test_organization
    ):
        """Withdrawing twice is a no-op, not an error — the UI can retry safely."""
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.commit()
        pid = listing.model_project_id

        assert authenticated_client.post(f"/api/v2/projects/{pid}/unpublish").status_code == 200
        assert authenticated_client.post(f"/api/v2/projects/{pid}/unpublish").status_code == 200

    def test_unpublish_a_never_published_project_returns_404(
        self, authenticated_client, db_session, test_organization
    ):
        """No listing facet means there is nothing to withdraw."""
        pid = generate_id("mp_")
        db_session.add(
            ModelProject(
                id=pid, organization_id=test_organization.id, name="Unpublished", status="active"
            )
        )
        db_session.commit()

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/unpublish")
        assert resp.status_code == 404

    def test_cannot_withdraw_another_orgs_listing(
        self, authenticated_client, db_session, test_organization_2
    ):
        """Multi-tenancy: the project lookup is org-scoped, so this is a 404."""
        listing = _publish(db_session, org_id=test_organization_2.id)
        db_session.commit()

        resp = authenticated_client.post(
            f"/api/v2/projects/{listing.model_project_id}/unpublish"
        )
        assert resp.status_code == 404

        db_session.expire_all()
        untouched = (
            db_session.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id == listing.model_project_id)
            .one()
        )
        assert untouched.status == "published"

    def test_unpublish_requires_authentication(self, client, db_session, test_organization):
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.commit()

        resp = client.post(f"/api/v2/projects/{listing.model_project_id}/unpublish")
        assert resp.status_code == 401

    def test_forks_already_made_keep_working_after_withdrawal(
        self, authenticated_client, db_session, test_organization, test_organization_2
    ):
        """# CONTRACT-TEST: adoption COPIES the model, so withdrawing never breaks a fork.

        This is the invariant the whole reversible-withdrawal decision rests on:
        an adopter's project carries its own content and only a provenance string,
        so the author retiring the listing cannot take it away from them.
        """
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.flush()
        fork = ModelProject(
            id=generate_id("mp_"),
            organization_id=test_organization_2.id,
            name="Adopted model",
            status="active",
            source_type="marketplace",
            source_ref=listing.model_project_id,
            draft_model_json={"variables": [], "constraints": []},
        )
        db_session.add(fork)
        db_session.commit()

        authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/unpublish")

        db_session.expire_all()
        survivor = db_session.query(ModelProject).filter(ModelProject.id == fork.id).one()
        assert survivor.status == "active"
        assert survivor.draft_model_json == {"variables": [], "constraints": []}


class TestMyListings:
    """GET /author/listings."""

    def test_lists_my_listings_including_withdrawn_ones(
        self, authenticated_client, db_session, test_organization
    ):
        """The author's own view shows withdrawn models — that is how they come back."""
        live = _publish(db_session, org_id=test_organization.id)
        gone = _publish(db_session, org_id=test_organization.id, status="unpublished")
        db_session.commit()

        resp = authenticated_client.get("/api/v2/author/listings")
        assert resp.status_code == 200
        by_id = {row["model_project_id"]: row for row in resp.json()}
        assert by_id[live.model_project_id]["status"] == "published"
        assert by_id[gone.model_project_id]["status"] == "unpublished"
        assert by_id[live.model_project_id]["total_activations"] == 7

    def test_does_not_leak_other_orgs_listings(
        self, authenticated_client, db_session, test_organization_2
    ):
        theirs = _publish(db_session, org_id=test_organization_2.id)
        db_session.commit()

        resp = authenticated_client.get("/api/v2/author/listings")
        assert resp.status_code == 200
        assert all(row["model_project_id"] != theirs.model_project_id for row in resp.json())

    def test_requires_authentication(self, client):
        assert client.get("/api/v2/author/listings").status_code == 401


class TestReviewsReceived:
    """GET /author/reviews."""

    def _review(self, db, *, pid, org_id, user_id, rating=5, visible=True, comment="Great"):
        review = ModelReview(
            id=generate_id("rev_"),
            model_project_id=pid,
            user_id=user_id,
            organization_id=org_id,
            rating=rating,
            title="Nice",
            comment=comment,
            is_visible=visible,
        )
        db.add(review)
        return review

    def test_returns_reviews_left_on_my_models(
        self, authenticated_client, db_session, test_organization, test_user_2, test_organization_2
    ):
        listing = _publish(db_session, org_id=test_organization.id)
        self._review(
            db_session,
            pid=listing.model_project_id,
            org_id=test_organization_2.id,
            user_id=test_user_2.id,
        )
        db_session.commit()

        resp = authenticated_client.get("/api/v2/author/reviews")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        row = data["reviews"][0]
        assert row["model_project_id"] == listing.model_project_id
        assert row["model_display_name"] == listing.display_name
        assert row["rating"] == 5
        assert row["reviewer_name"] == test_user_2.name

    def test_hidden_reviews_stay_hidden_from_the_author(
        self, authenticated_client, db_session, test_organization, test_user_2, test_organization_2
    ):
        """Moderation is not bypassed by the author panel."""
        listing = _publish(db_session, org_id=test_organization.id)
        self._review(
            db_session,
            pid=listing.model_project_id,
            org_id=test_organization_2.id,
            user_id=test_user_2.id,
            visible=False,
            comment="Hidden by an admin",
        )
        db_session.commit()

        data = authenticated_client.get("/api/v2/author/reviews").json()
        assert data["total"] == 0
        assert data["reviews"] == []

    def test_does_not_leak_reviews_of_other_authors_models(
        self, authenticated_client, db_session, test_organization_2, test_user_2
    ):
        theirs = _publish(db_session, org_id=test_organization_2.id)
        self._review(
            db_session,
            pid=theirs.model_project_id,
            org_id=test_organization_2.id,
            user_id=test_user_2.id,
        )
        db_session.commit()

        data = authenticated_client.get("/api/v2/author/reviews").json()
        assert data["total"] == 0

    def test_paginates_newest_first(
        self, authenticated_client, db_session, test_organization, test_user_2, test_organization_2
    ):
        listing = _publish(db_session, org_id=test_organization.id)
        for i in range(5):
            self._review(
                db_session,
                pid=listing.model_project_id,
                org_id=test_organization_2.id,
                user_id=test_user_2.id,
                rating=(i % 5) + 1,
                comment=f"Review {i}",
            )
        db_session.commit()

        page1 = authenticated_client.get(
            "/api/v2/author/reviews", params={"page": 1, "page_size": 2}
        ).json()
        page2 = authenticated_client.get(
            "/api/v2/author/reviews", params={"page": 2, "page_size": 2}
        ).json()

        assert page1["total"] == 5
        assert len(page1["reviews"]) == 2
        assert len(page2["reviews"]) == 2
        assert {r["id"] for r in page1["reviews"]}.isdisjoint({r["id"] for r in page2["reviews"]})

    def test_author_with_nothing_published_gets_an_empty_list(self, authenticated_client):
        resp = authenticated_client.get("/api/v2/author/reviews")
        assert resp.status_code == 200
        assert resp.json() == {"reviews": [], "total": 0}

    def test_requires_authentication(self, client):
        assert client.get("/api/v2/author/reviews").status_code == 401


class TestProjectListPublicationState:
    """The studio list says which models are on the marketplace."""

    def test_rows_carry_their_listing_status(
        self, authenticated_client, db_session, test_organization
    ):
        published = _publish(db_session, org_id=test_organization.id)
        withdrawn = _publish(db_session, org_id=test_organization.id, status="unpublished")
        never = generate_id("mp_")
        db_session.add(
            ModelProject(
                id=never, organization_id=test_organization.id, name="Never", status="active"
            )
        )
        db_session.commit()

        rows = authenticated_client.get("/api/v2/projects").json()
        by_id = {row["id"]: row for row in rows}
        assert by_id[published.model_project_id]["listing_status"] == "published"
        assert by_id[withdrawn.model_project_id]["listing_status"] == "unpublished"
        assert by_id[never]["listing_status"] is None


class TestOnboardingLinks:
    """# CONTRACT-TEST: every onboarding step must link to a route that exists.

    Two of the three links pointed at /workspace/models/publish and
    /workspace/models, neither of which existed, and the third resolved to a page
    that does not hold what the step asks for. A checklist that sends authors to a
    404 is worse than no checklist, so the links are pinned here.
    """

    def _route_dir(self, link: str) -> Path:
        return _APP_ROUTES.joinpath(*[seg for seg in link.strip("/").split("/") if seg])

    def test_every_step_links_to_an_existing_page(
        self, authenticated_client, db_session, test_organization
    ):
        if not _APP_ROUTES.exists():
            pytest.skip("frontend sources not mounted")

        steps = authenticated_client.get("/api/v2/author/onboarding/status").json()["steps"]
        assert len(steps) == 3

        for step in steps:
            directory = self._route_dir(step["link"])
            assert (directory / "page.tsx").exists(), (
                f"onboarding step {step['key']} links to {step['link']}, "
                f"but {directory / 'page.tsx'} does not exist"
            )

    def test_profile_step_points_where_the_bio_is_edited(self, authenticated_client):
        """The step measures org name + bio, which live on /workspace/profile."""
        steps = authenticated_client.get("/api/v2/author/onboarding/status").json()["steps"]
        profile_step = next(s for s in steps if s["key"] == "complete_profile")
        assert profile_step["link"] == "/workspace/profile"

    def test_completion_tracks_the_real_state(
        self, authenticated_client, db_session, test_organization
    ):
        """publish_model flips once a published listing exists."""
        before = authenticated_client.get("/api/v2/author/onboarding/status").json()
        assert {s["key"]: s["completed"] for s in before["steps"]}["publish_model"] is False

        _publish(db_session, org_id=test_organization.id)
        db_session.commit()

        after = authenticated_client.get("/api/v2/author/onboarding/status").json()
        assert {s["key"]: s["completed"] for s in after["steps"]}["publish_model"] is True
