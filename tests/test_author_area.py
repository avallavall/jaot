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
    RecentModel,
    User,
    UserFavorite,
)
from app.models.audit_log import AuditAction, AuditLog
from app.models.model_view_event import ModelViewEvent
from app.services.author_analytics_service import adoption_count
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

_REPO_ROOT = Path(__file__).resolve().parent.parent
_APP_ROUTES = _REPO_ROOT / "frontend" / "src" / "app" / "[locale]"


def _adopt(db, listing, *, org_id: str):
    """Somebody seeds a fork from a listing. That row IS the adoption.

    There is no counter to bump any more: every screen counts these rows, so a
    test that wants a non-zero adoption number has to create one.
    """
    project = ModelProject(
        id=generate_id("mp_"),
        organization_id=org_id,
        name="Adopted copy",
        status="active",
        source_type="marketplace",
        source_ref=listing.model_project_id,
    )
    db.add(project)
    db.flush()
    return project


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
        total_executions=11,
        published_at=utcnow(),
    )
    db.add(listing)
    db.flush()
    return listing


@pytest.fixture
def published(db_session, test_organization):
    """A published listing owned by the authenticated client's org, committed."""
    listing = _publish(db_session, org_id=test_organization.id)
    db_session.commit()
    return listing


class TestWithdrawListing:
    """POST /projects/{id}/unpublish and /republish."""

    def test_unpublish_removes_the_listing_from_every_catalog_surface(
        self, authenticated_client, client, published
    ):
        """Withdrawing hides the model from list, detail and input schema."""
        pid = published.model_project_id

        assert client.get(f"/api/v2/models/catalog/{pid}").status_code == 200

        resp = authenticated_client.post(f"/api/v2/projects/{pid}/unpublish")
        assert resp.status_code == 200, resp.text

        assert client.get(f"/api/v2/models/catalog/{pid}").status_code == 404
        assert client.get(f"/api/v2/models/catalog/{pid}/schema").status_code == 404
        listed = client.get("/api/v2/models/catalog").json()
        assert all(m["id"] != pid for m in listed["items"])

    def test_republish_puts_it_back_with_its_rollups_intact(
        self, authenticated_client, client, db_session, published, test_organization_2
    ):
        """The whole point of a reversible withdrawal: nothing is lost."""
        pid = published.model_project_id
        _adopt(db_session, published, org_id=test_organization_2.id)
        _adopt(db_session, published, org_id=test_organization_2.id)
        db_session.commit()

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
        assert restored.total_executions == 11
        # Adoptions come back too. They are counted off the fork rows, which a
        # withdrawal never touched, so the card reads the same as before.
        assert adoption_count(db_session, pid) == 2
        assert restored.published_at is not None

    def test_unpublish_is_idempotent(self, authenticated_client, published):
        """Withdrawing twice is a no-op, not an error — the UI can retry safely."""
        pid = published.model_project_id

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

        resp = authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/unpublish")
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


class TestWithdrawalIsHonouredEverywhere:
    """# CONTRACT-TEST: a withdrawn listing must not be linked from anywhere.

    The reversible withdrawal rests on "every marketplace surface filters
    status == published". Catalog list/detail/schema did; favourites and
    recently-viewed did not, because they were written when withdrawing deleted
    the row — so they kept serving cards whose target answers 404.
    """

    def test_a_withdrawn_listing_leaves_favourites(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.add(
            UserFavorite(
                id=generate_id("fav_"),
                user_id=test_user.id,
                model_project_id=listing.model_project_id,
            )
        )
        db_session.commit()

        assert authenticated_client.get("/api/v2/models/favorites").json()["total"] == 1

        authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/unpublish")

        assert authenticated_client.get("/api/v2/models/favorites").json()["total"] == 0

    def test_it_comes_back_when_republished(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        """The favourite row survives — only the card is withheld while it is off."""
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.add(
            UserFavorite(
                id=generate_id("fav_"),
                user_id=test_user.id,
                model_project_id=listing.model_project_id,
            )
        )
        db_session.commit()

        authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/unpublish")
        authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/republish")

        assert authenticated_client.get("/api/v2/models/favorites").json()["total"] == 1

    def test_a_withdrawn_listing_leaves_recently_viewed(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.add(
            RecentModel(
                id=generate_id("rec_"),
                user_id=test_user.id,
                model_project_id=listing.model_project_id,
                last_accessed=utcnow(),
                access_count=1,
            )
        )
        db_session.commit()

        assert authenticated_client.get("/api/v2/models/recents").json()["total"] == 1

        authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/unpublish")

        assert authenticated_client.get("/api/v2/models/recents").json()["total"] == 0

    def test_a_withdrawn_listing_leaves_the_public_user_profile(
        self, authenticated_client, client, db_session, test_organization, test_user
    ):
        """The reviews on a user's public profile each link to the marketplace."""
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.add(
            ModelReview(
                id=generate_id("rev_"),
                model_project_id=listing.model_project_id,
                user_id=test_user.id,
                organization_id=test_organization.id,
                rating=5,
                comment="Solid",
            )
        )
        db_session.commit()

        assert len(client.get(f"/api/v2/users/{test_user.id}/reviews").json()) == 1

        authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/unpublish")

        # Dropped, not relabelled "Unknown Model": the row is a link either way.
        assert client.get(f"/api/v2/users/{test_user.id}/reviews").json() == []

    def test_an_unlisted_model_is_not_offered_either(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        """`is_public=False` 404s on the detail page exactly like a withdrawal does."""
        listing = _publish(db_session, org_id=test_organization.id)
        listing.is_public = False
        db_session.add(
            UserFavorite(
                id=generate_id("fav_"),
                user_id=test_user.id,
                model_project_id=listing.model_project_id,
            )
        )
        db_session.commit()

        assert authenticated_client.get("/api/v2/models/favorites").json()["total"] == 0


class TestPublicationTransitions:
    """Republishing restores a withdrawal; it is not a back door into published."""

    @pytest.mark.parametrize("state", ["draft", "deprecated"])
    def test_republish_refuses_states_that_never_passed_publish(
        self, authenticated_client, db_session, test_organization, state
    ):
        """A draft has no pinned version and a deprecated template was retired on
        purpose — promoting either would put a broken card on the marketplace."""
        listing = _publish(db_session, org_id=test_organization.id, status=state)
        db_session.commit()

        resp = authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/republish")
        assert resp.status_code == 409, resp.text

        db_session.expire_all()
        unchanged = (
            db_session.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id == listing.model_project_id)
            .one()
        )
        assert unchanged.status == state

    def test_withdraw_refuses_them_too(self, authenticated_client, db_session, test_organization):
        listing = _publish(db_session, org_id=test_organization.id, status="deprecated")
        db_session.commit()

        resp = authenticated_client.post(f"/api/v2/projects/{listing.model_project_id}/unpublish")
        assert resp.status_code == 409

    def test_the_audit_log_says_which_way_it_went(
        self, authenticated_client, db_session, published
    ):
        """'When did this leave the marketplace, and who took it off?' — model_edit
        cannot answer that, and all three publication routes used to log it."""
        pid = published.model_project_id

        authenticated_client.post(f"/api/v2/projects/{pid}/unpublish")
        authenticated_client.post(f"/api/v2/projects/{pid}/republish")

        actions = [
            row.action
            for row in db_session.query(AuditLog)
            .filter(AuditLog.target_id == pid)
            .order_by(AuditLog.created_at)
            .all()
        ]
        assert AuditAction.MODEL_UNPUBLISH.value in actions
        assert AuditAction.MODEL_PUBLISH.value in actions


class TestGeoCountsVisits:
    """The geo card is titled "where your visitors are" and must count visitors."""

    def test_impressions_are_not_counted_as_visits(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        listing = _publish(db_session, org_id=test_organization.id)
        now = utcnow()
        db_session.add_all(
            [
                ModelViewEvent(
                    id=generate_id("mve_"),
                    model_project_id=listing.model_project_id,
                    event_type="view",
                    viewer_country="ES",
                    created_at=now,
                ),
                *[
                    ModelViewEvent(
                        id=generate_id("mve_"),
                        model_project_id=listing.model_project_id,
                        event_type="impression",
                        viewer_country="ES",
                        created_at=now,
                    )
                    for _ in range(30)
                ],
            ]
        )
        db_session.commit()

        geo = authenticated_client.get("/api/v2/author/analytics/geo?period=30d").json()
        summary = authenticated_client.get("/api/v2/author/analytics/summary?period=30d").json()

        # The breakdown must not exceed the total it breaks down.
        assert sum(entry["count"] for entry in geo["data"]) == summary["total_views"] == 1


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

    def test_the_panel_counts_adoptions_instead_of_reading_a_counter(
        self, authenticated_client, db_session, test_organization, test_organization_2
    ):
        """The author sees the number the marketplace shows, counted the same way.

        The column this row used to read was bumped on a fork and nothing ever
        recomputed it: 66 stored against 6 counted on the development database.
        Two forks by another organization read as two, and the author forking
        their own listing does not count at all — or the word would not mean
        what it says.
        """
        mine = _publish(db_session, org_id=test_organization.id)
        _adopt(db_session, mine, org_id=test_organization_2.id)
        _adopt(db_session, mine, org_id=test_organization_2.id)
        _adopt(db_session, mine, org_id=test_organization.id)
        db_session.commit()

        resp = authenticated_client.get("/api/v2/author/listings")
        assert resp.status_code == 200
        row = next(r for r in resp.json() if r["model_project_id"] == mine.model_project_id)
        assert row["total_activations"] == 2

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

    def test_does_not_read_the_columns_the_panel_never_shows(self, db_session, test_organization):
        """The rich text and the generator blobs are kilobytes per row, on a
        query with no upper bound on rows, for a panel that shows neither."""
        from sqlalchemy import inspect

        from app.services import author_listing_service

        _publish(db_session, org_id=test_organization.id)
        db_session.commit()
        db_session.expire_all()

        rows = author_listing_service.load_my_listing_rows(db_session, org_id=test_organization.id)
        unloaded = inspect(rows[0]).unloaded
        assert {
            "description",
            "scenario_description",
            "section_overview",
            "input_schema",
            "input_fields",
            "example_input",
        } <= unloaded
        # And every field the response promises IS there, without a second query.
        assert "display_name" not in unloaded
        assert "total_executions" not in unloaded


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
        # Five reviewers, not one reviewer five times: one review per user per
        # model is enforced by the database (D-26), and five reviews of a model
        # is five people — which is also what the page is paginating.
        for i in range(5):
            reviewer = User(
                id=generate_id("usr_"),
                email=f"reviewer{i}@paginate.test",
                name=f"Reviewer {i}",
                organization_id=test_organization_2.id,
            )
            db_session.add(reviewer)
            db_session.flush()
            self._review(
                db_session,
                pid=listing.model_project_id,
                org_id=test_organization_2.id,
                user_id=reviewer.id,
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
        """Resolve a concrete link to its Next.js route directory.

        Links may carry ids (``/studio/mp_abc/publish``); the route that serves
        them is a dynamic segment (``[modelId]``), so a literal id has to be
        matched against the one bracketed child directory at that level.
        """
        directory = _APP_ROUTES
        for segment in [s for s in link.strip("/").split("/") if s]:
            if (directory / segment).is_dir():
                directory = directory / segment
                continue
            dynamic = [d for d in directory.iterdir() if d.is_dir() and d.name.startswith("[")]
            if len(dynamic) != 1:
                return directory / segment  # let the caller report the miss
            directory = dynamic[0]
        return directory

    def test_every_step_links_to_an_existing_page(
        self, authenticated_client, db_session, test_organization
    ):
        if not _APP_ROUTES.exists():
            pytest.skip("frontend sources not mounted")

        # With a published listing that has no image, the rich-media step links to
        # that listing's publish panel — the dynamic-route case this must cover.
        _publish(db_session, org_id=test_organization.id)
        db_session.commit()

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

    def test_rich_media_step_points_at_the_listing_that_needs_an_image(
        self, authenticated_client, db_session, test_organization
    ):
        """One click to the upload panel — not back to the page the checklist is on."""
        listing = _publish(db_session, org_id=test_organization.id)
        db_session.commit()

        steps = authenticated_client.get("/api/v2/author/onboarding/status").json()["steps"]
        media_step = next(s for s in steps if s["key"] == "add_rich_media")
        assert media_step["link"] == f"/studio/{listing.model_project_id}/publish"

    def test_rich_media_step_falls_back_when_there_is_nothing_to_illustrate(
        self, authenticated_client
    ):
        """With no published listing, the step has no particular one to point at."""
        steps = authenticated_client.get("/api/v2/author/onboarding/status").json()["steps"]
        media_step = next(s for s in steps if s["key"] == "add_rich_media")
        assert media_step["link"] == "/workspace/models"

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


class TestAuthorHearsAboutReviews:
    """# CONTRACT-TEST: a review must ring the author's bell.

    The notification type and the preference plumbing existed
    (``NotificationType.NEW_REVIEW``, ``_AUTHOR_EVENT_MAP["review"]``) and nobody
    ever raised the event: adopting a model notified the author, reviewing it
    did not. Verified by driving the real app across two organizations.
    """

    def test_reviewing_a_model_notifies_its_author(
        self, authenticated_client, db_session, test_organization, test_organization_2, test_user_2
    ):
        from app.api.v2.routes.profiles.reviews import _notify_author_of_review
        from app.models.notification import Notification, NotificationType

        listing = _publish(db_session, org_id=test_organization.id)
        review = ModelReview(
            id=generate_id("rev_"),
            model_project_id=listing.model_project_id,
            user_id=test_user_2.id,
            organization_id=test_organization_2.id,
            rating=5,
            comment="Excellent",
        )
        db_session.add(review)
        db_session.flush()

        _notify_author_of_review(db_session, listing, review, reviewer=test_user_2)
        db_session.flush()

        rows = (
            db_session.query(Notification)
            .filter(Notification.type == NotificationType.NEW_REVIEW.value)
            .all()
        )
        assert rows, "the author was never told about the review"
        assert listing.display_name in rows[0].message

    def test_reviewing_your_own_model_notifies_nobody(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        """Same rule the adoption counter already follows: your own activity is not news."""
        from app.api.v2.routes.profiles.reviews import _notify_author_of_review
        from app.models.notification import Notification

        listing = _publish(db_session, org_id=test_organization.id)
        review = ModelReview(
            id=generate_id("rev_"),
            model_project_id=listing.model_project_id,
            user_id=test_user.id,
            organization_id=test_organization.id,
            rating=4,
        )
        db_session.add(review)
        db_session.flush()

        _notify_author_of_review(db_session, listing, review, reviewer=test_user)

        assert db_session.query(Notification).count() == 0


class TestCatalogOffersEveryCategory:
    """# CONTRACT-TEST: the category filter must cover the catalogue, not the page.

    The sidebar derived its options from the models already loaded, so page 1 and
    page 2 offered different lists and most of the catalogue could not be
    filtered by category at all.
    """

    def test_the_facet_is_not_limited_to_the_current_page(
        self, client, db_session, test_organization
    ):
        for i, category in enumerate(["logistics", "finance", "energy"]):
            listing = _publish(db_session, org_id=test_organization.id, pid=f"mp_cat_{i}")
            listing.category = category
        db_session.commit()

        page = client.get("/api/v2/models/catalog?page_size=1").json()

        assert len(page["items"]) == 1, "page size not honoured; the test proves nothing"
        for category in ("logistics", "finance", "energy"):
            assert category in page["categories"], (
                f"{category} is in the catalogue but the filter would not offer it"
            )
