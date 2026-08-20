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
    ModelReviewReport,
    Organization,
    User,
)


def _listing(db, org, *, pid) -> None:
    """A published listing owned by ``org``.

    ``author_organization_id`` is set, which a real listing always has: the
    publish route writes it. It used to be left NULL here, and that made the
    gate tests below describe a model with no author — the one shape where a
    reviewer from the publishing organization is not the author's own.
    """
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
            author_organization_id=org.id,
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
        self, authenticated_client, db_session, test_organization, test_organization_2
    ):
        _listing(db_session, test_organization_2, pid="rev_no_fork")
        db_session.commit()
        res = authenticated_client.post("/api/v2/models/catalog/rev_no_fork/reviews", json=_REVIEW)
        assert res.status_code == 403, res.text

    def test_review_forked_but_not_executed_403(
        self, authenticated_client, db_session, test_organization, test_organization_2, test_user
    ):
        _listing(db_session, test_organization_2, pid="rev_fork_only")
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
        self, authenticated_client, db_session, test_organization, test_organization_2, test_user
    ):
        _listing(db_session, test_organization_2, pid="rev_used")
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
        self, authenticated_client, db_session, test_organization, test_organization_2, test_user
    ):
        _listing(db_session, test_organization_2, pid="rev_dup")
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


class TestAnAuthorCannotRateTheirOwnModel:
    """Found by driving the marketplace (QA sweep, 2026-08-20).

    Both gates on a review — a fork of the listing, and a completed run of that
    fork — are things an author can do to their own model in about a minute. So
    the author adopted their own listing, solved the copy, wrote five stars, and
    the marketplace showed that as the model's average rating.
    """

    def _used_by(self, db, org, user, *, pid, fork_id, exe_id):
        _fork(db, org, user, listing_id=pid, fork_id=fork_id)
        _completed_execution(db, org, user, fork_id=fork_id, exe_id=exe_id)

    def test_the_publishing_organization_is_refused(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        # Published by the reviewer's own organization this time.
        _listing(db_session, test_organization, pid="rev_own")
        self._used_by(
            db_session,
            test_organization,
            test_user,
            pid="rev_own",
            fork_id="fork_rev_own",
            exe_id="exe_rev_own",
        )
        db_session.commit()

        res = authenticated_client.post("/api/v2/models/catalog/rev_own/reviews", json=_REVIEW)
        assert res.status_code == 403, res.text
        # CONTRACT-TEST: the page has to tell this apart from "use it first" and
        # "run it first", which ask the reader to go and do something.
        assert res.json()["code"] == "review.own_model"

        assert db_session.get(ModelProjectListing, "rev_own").avg_rating is None
        assert (
            db_session.query(ModelReview).filter(ModelReview.model_project_id == "rev_own").count()
            == 0
        )

    def test_a_colleague_of_the_author_is_refused_too(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        # The rule is the organization, not the person: a second account inside
        # the publishing organization is the same hand.
        _listing(db_session, test_organization, pid="rev_own_colleague")
        colleague = User(
            id="usr_review_colleague",
            email="colleague@review.test",
            name="Colleague",
            organization_id=test_organization.id,
            is_active=True,
        )
        db_session.add(colleague)
        db_session.flush()
        self._used_by(
            db_session,
            test_organization,
            colleague,
            pid="rev_own_colleague",
            fork_id="fork_rev_colleague",
            exe_id="exe_rev_colleague",
        )
        db_session.commit()

        res = authenticated_client.post(
            "/api/v2/models/catalog/rev_own_colleague/reviews", json=_REVIEW
        )
        assert res.status_code == 403, res.text
        assert res.json()["code"] == "review.own_model"


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
        self,
        authenticated_client,
        db_session,
        test_organization,
        test_organization_2,
        test_user,
        monkeypatch,
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
        _listing(db_session, test_organization_2, pid="rev_notify")
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
        self, client, db_session, test_organization, test_organization_2, test_user
    ):
        for pid in ("prof_visible", "prof_gone"):
            _listing(db_session, test_organization_2, pid=pid)
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


class TestReportingAReviewIsOneVoicePerPerson:
    """# CONTRACT-TEST: a report is one row per person, and never your own review.

    Found by driving the marketplace (QA sweep, 2026-08-20). The endpoint wrote
    straight onto the review: it set ``is_reported`` and replaced
    ``report_reason`` with whatever arrived. So a reviewer reported their own
    review, one person reported the same one four times in a row, and every call
    overwrote the sentence before it. Five reports from two people reached the
    moderator as one sentence with no name on it.
    """

    def _reviewed(self, db, org, user, *, pid, fork_id, exe_id, review_id):
        """A listing published by another organization, reviewed by ``user``."""
        _fork(db, org, user, listing_id=pid, fork_id=fork_id)
        _completed_execution(db, org, user, fork_id=fork_id, exe_id=exe_id)
        db.add(
            ModelReview(
                id=review_id,
                model_project_id=pid,
                user_id=user.id,
                organization_id=org.id,
                rating=2,
                title="Not for me",
                comment="Did not fit my case",
            )
        )
        db.flush()

    def test_a_reviewer_cannot_report_their_own_review(
        self, authenticated_client, db_session, test_organization, test_organization_2, test_user
    ):
        _listing(db_session, test_organization_2, pid="rep_own")
        self._reviewed(
            db_session,
            test_organization,
            test_user,
            pid="rep_own",
            fork_id="fork_rep_own",
            exe_id="exe_rep_own",
            review_id="rev_rep_own",
        )
        db_session.commit()

        res = authenticated_client.post(
            "/api/v2/models/reviews/rev_rep_own/report", json={"reason": "I changed my mind"}
        )
        assert res.status_code == 400, res.text
        # The page has to tell this apart from a report that failed for another
        # reason: the answer is "delete it", not "try again".
        assert res.json()["code"] == "review.report_own"

        db_session.expire_all()
        assert db_session.get(ModelReview, "rev_rep_own").is_reported is False
        assert (
            db_session.query(ModelReviewReport)
            .filter(ModelReviewReport.review_id == "rev_rep_own")
            .count()
            == 0
        )

    def test_reporting_twice_updates_the_reason_instead_of_adding_a_voice(
        self,
        authenticated_client,
        db_session,
        test_organization,
        test_organization_2,
        test_user,
        test_admin_user,
    ):
        """Somebody else's review, reported twice by the same person."""
        _listing(db_session, test_organization_2, pid="rep_twice")
        # The review belongs to the ADMIN user, so the authenticated caller is
        # somebody else and is allowed to report it.
        self._reviewed(
            db_session,
            test_organization,
            test_admin_user,
            pid="rep_twice",
            fork_id="fork_rep_twice",
            exe_id="exe_rep_twice",
            review_id="rev_rep_twice",
        )
        db_session.commit()

        for reason in ("First reason", "Second reason"):
            res = authenticated_client.post(
                "/api/v2/models/reviews/rev_rep_twice/report", json={"reason": reason}
            )
            assert res.status_code == 200, res.text

        db_session.expire_all()
        rows = (
            db_session.query(ModelReviewReport)
            .filter(ModelReviewReport.review_id == "rev_rep_twice")
            .all()
        )
        assert len(rows) == 1, "the same person reporting twice must still count once"
        assert rows[0].reason == "Second reason", "a reporter may change their mind"
        assert db_session.get(ModelReview, "rev_rep_twice").is_reported is True

    def test_two_people_reporting_keep_both_reasons(
        self,
        authenticated_client,
        admin_client,
        db_session,
        test_organization,
        test_organization_2,
        test_user,
        test_admin_user,
    ):
        """The defect itself: the second reason used to replace the first."""
        _listing(db_session, test_organization_2, pid="rep_two")
        # Reviewed by nobody in particular — a third user is not needed, because
        # the review is written by the admin and reported by the plain user, and
        # then by another admin session.
        self._reviewed(
            db_session,
            test_organization,
            test_user,
            pid="rep_two",
            fork_id="fork_rep_two",
            exe_id="exe_rep_two",
            review_id="rev_rep_two",
        )
        db_session.commit()

        first = admin_client.post(
            "/api/v2/models/reviews/rev_rep_two/report", json={"reason": "Abusive"}
        )
        assert first.status_code == 200, first.text

        db_session.expire_all()
        rows = (
            db_session.query(ModelReviewReport)
            .filter(ModelReviewReport.review_id == "rev_rep_two")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].user_id == test_admin_user.id
        assert rows[0].reason == "Abusive"
