"""Tests for the project-native review-create gate (P1.5 G4).

``POST /api/v2/models/catalog/{id}/reviews`` — the ``{id}`` is the model-project id. A
user may review a model only after their org has *used* it: seeded a fork ModelProject
from the listing (``source_ref``) AND completed an execution. Creating a review rolls the
average rating up onto the listing.
"""

from sqlalchemy import text

from app.models import (
    ExecutionStatus,
    ModelCategory,
    ModelExecution,
    ModelProject,
    ModelProjectListing,
    ModelReview,
    Organization,
    User,
)


def _listing(db, org, *, pid) -> None:
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Model " + pid,
            description="A model for review tests",
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


def _fork(db, org, user, *, listing_id, fork_id) -> None:
    db.add(
        ModelProject(
            id=fork_id,
            organization_id=org.id,
            created_by=user.id,
            name="Fork of " + listing_id,
            status="active",
            source_type="marketplace",
            source_ref=listing_id,
        )
    )


def _completed_execution(db, org, user, *, fork_id, exe_id) -> None:
    db.add(
        ModelExecution(
            id=exe_id,
            model_project_id=fork_id,
            organization_id=org.id,
            executed_by_user_id=user.id,
            input_data={},
            status=ExecutionStatus.COMPLETED.value,
        )
    )


_REVIEW = {"rating": 5, "title": "Great", "comment": "Worked well"}


class TestCreateReviewGate:
    def test_review_without_using_model_403(
        self, authenticated_client, db_session, test_organization
    ):
        _listing(db_session, test_organization, pid="rev_no_fork")
        db_session.commit()
        res = authenticated_client.post("/api/v2/models/catalog/rev_no_fork/reviews", json=_REVIEW)
        assert res.status_code == 403, res.text

    def test_review_forked_but_not_executed_403(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _listing(db_session, test_organization, pid="rev_fork_only")
        _fork(
            db_session,
            test_organization,
            test_user,
            listing_id="rev_fork_only",
            fork_id="fork_rev_1",
        )
        db_session.commit()
        res = authenticated_client.post(
            "/api/v2/models/catalog/rev_fork_only/reviews", json=_REVIEW
        )
        assert res.status_code == 403, res.text

    def test_review_after_using_model_200(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _listing(db_session, test_organization, pid="rev_used")
        _fork(
            db_session,
            test_organization,
            test_user,
            listing_id="rev_used",
            fork_id="fork_rev_2",
        )
        _completed_execution(
            db_session, test_organization, test_user, fork_id="fork_rev_2", exe_id="exe_rev_1"
        )
        db_session.commit()

        res = authenticated_client.post("/api/v2/models/catalog/rev_used/reviews", json=_REVIEW)
        assert res.status_code == 200, res.text
        assert res.json()["catalog_id"] == "rev_used"
        assert res.json()["rating"] == 5

        # The average rating rolled up onto the listing.
        listing = db_session.get(ModelProjectListing, "rev_used")
        assert listing.avg_rating == 5.0

    def test_double_review_400(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        _listing(db_session, test_organization, pid="rev_dup")
        _fork(
            db_session,
            test_organization,
            test_user,
            listing_id="rev_dup",
            fork_id="fork_rev_3",
        )
        _completed_execution(
            db_session, test_organization, test_user, fork_id="fork_rev_3", exe_id="exe_rev_2"
        )
        db_session.add(
            ModelReview(
                id="existing_rev",
                model_project_id="rev_dup",
                user_id=test_user.id,
                organization_id=test_organization.id,
                rating=4,
            )
        )
        db_session.commit()

        res = authenticated_client.post("/api/v2/models/catalog/rev_dup/reviews", json=_REVIEW)
        assert res.status_code == 400, res.text
        assert "already reviewed" in res.json()["detail"].lower()


class TestTheReviewSurvivesItsNotification:
    """The review is committed before the author is told about it. Ringing the
    bell is best-effort by design — but "best-effort" means the failure has to be
    cleaned up, not merely caught."""

    # CONTRACT-TEST: a notification that fails AT THE DATABASE must not turn a
    # saved review into a 500. Swallowing the exception without db.rollback()
    # left the session in a failed transaction, so the very next statement — the
    # organization lookup that builds the response — raised PendingRollbackError.
    # The reader saw an error for a review that was already stored, and retrying
    # answered "you have already reviewed this model".
    def test_a_failed_notification_does_not_500_a_review_that_was_saved(
        self, authenticated_client, db_session, test_organization, test_user, monkeypatch
    ):
        author_org = Organization(id="org_rev_author", name="Author Org", is_active=True)
        db_session.add(author_org)
        db_session.flush()
        db_session.add(
            User(
                id="usr_rev_author",
                email="author_rev@example.com",
                name="Author",
                organization_id=author_org.id,
                is_active=True,
            )
        )
        _listing(db_session, test_organization, pid="rev_notify")
        db_session.flush()
        # A different org authors it, or there is nobody to notify.
        db_session.get(ModelProjectListing, "rev_notify").author_organization_id = author_org.id
        _fork(
            db_session, test_organization, test_user, listing_id="rev_notify", fork_id="fork_rev_4"
        )
        _completed_execution(
            db_session, test_organization, test_user, fork_id="fork_rev_4", exe_id="exe_rev_3"
        )
        db_session.commit()

        from app.services.notification_service import NotificationService

        def _fails_at_the_database(self, **kwargs):
            # Not a bare raise: a plain Python error leaves the session usable and
            # would pass with or without the fix. The real failure poisons the
            # transaction, which is what the rollback is there for.
            self.db.execute(text("SELECT 1 FROM a_table_that_does_not_exist"))

        monkeypatch.setattr(NotificationService, "send_author_notification", _fails_at_the_database)

        res = authenticated_client.post("/api/v2/models/catalog/rev_notify/reviews", json=_REVIEW)
        assert res.status_code == 200, res.text

        # And it is stored exactly once — a retry would now hit the unique index.
        assert db_session.query(ModelReview).filter_by(model_project_id="rev_notify").count() == 1


class TestTheProfileCountMatchesTheList:
    """The public profile header and its review list must describe the same set.

    The list drops a review whose model has left the marketplace — its row is a
    link that would 404 — while the header counted every review the user ever
    wrote. Withdraw one reviewed model and the page read "Reviews 2" above a
    list of one.
    """

    # CONTRACT-TEST: profile review count == the reviews the profile shows.
    def test_withdrawn_model_leaves_the_profile_consistent(
        self, client, db_session, test_organization, test_user
    ):
        for pid in ("prof_visible", "prof_gone"):
            _listing(db_session, test_organization, pid=pid)
        db_session.flush()
        for pid in ("prof_visible", "prof_gone"):
            db_session.add(
                ModelReview(
                    id=f"rev_{pid}",
                    model_project_id=pid,
                    user_id=test_user.id,
                    organization_id=test_organization.id,
                    rating=5,
                    title="Good",
                    comment="Solid model, would use again.",
                )
            )
        # One of the two models is withdrawn from the marketplace.
        db_session.get(ModelProjectListing, "prof_gone").is_public = False
        db_session.commit()

        profile = client.get(f"/api/v2/users/{test_user.id}/public")
        assert profile.status_code == 200, profile.text
        listed = client.get(f"/api/v2/users/{test_user.id}/reviews")
        assert listed.status_code == 200, listed.text

        assert profile.json()["total_reviews"] == len(listed.json()), (
            f"header says {profile.json()['total_reviews']}, list shows {len(listed.json())}"
        )
        assert len(listed.json()) == 1, "only the still-visible model's review is shown"
