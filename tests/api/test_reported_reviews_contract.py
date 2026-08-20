"""The moderation queue's response contract (D-17).

``GET /api/v2/admin/reviews/reported`` had no ``response_model``, and the page
that consumes it was reading three fields the backend has never sent —
``model_id``, ``report_count`` and ``report_reasons`` — plus ``is_visible``,
which the endpoint really did omit. ``report_reasons.length`` on ``undefined``
threw while rendering, so the queue crashed on the first flagged review.

A review used to carry ONE report flag and ONE reason, and nothing else: the
endpoint overwrote ``report_reason`` on every call, so one person could report
the same review any number of times and two people's reasons collapsed into
whichever was written last. The moderator read one sentence with no way to tell
whose it was. ``model_review_reports`` holds one row per (review, person) now
(2026-08-20), and the queue serves ``report_count`` and ``reports`` alongside
the newest reason.

The counter the page was reading all along therefore exists at last. It is
spelled ``report_count``, and ``reports`` carries the reasons rather than the
``report_reasons`` the page once guessed at.
"""

from app.models import (
    ModelCategory,
    ModelProject,
    ModelProjectListing,
    ModelReview,
    ModelReviewReport,
)

# CONTRACT-TEST: the moderation queue serves catalog_id + report_reason +
# is_visible + report_count + reports (who complained, and why).


def _flagged_review(db, org, user, *, pid, review_id, reason, visible=True):
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Model " + pid,
            description="A model for moderation tests",
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
    db.add(
        ModelReview(
            id=review_id,
            model_project_id=pid,
            user_id=user.id,
            organization_id=org.id,
            rating=2,
            title="Not for me",
            comment="Did not fit my case",
            is_reported=True,
            report_reason=reason,
            is_visible=visible,
        )
    )
    db.flush()


class TestReportedReviewsShape:
    def test_serves_catalog_id_reason_and_visibility(
        self, admin_client, db_session, test_organization, test_admin_user
    ):
        _flagged_review(
            db_session,
            test_organization,
            test_admin_user,
            pid="mod_shape",
            review_id="rev_mod_1",
            reason="Spam link in the comment",
        )
        db_session.commit()

        res = admin_client.get("/api/v2/admin/reviews/reported")
        assert res.status_code == 200, res.text
        item = next(i for i in res.json()["items"] if i["id"] == "rev_mod_1")

        # The link target: the page builds /marketplace/{id} from this.
        assert item["catalog_id"] == "mod_shape"
        assert item["model_name"] == "Model mod_shape"
        assert item["report_reason"] == "Spam link in the comment"
        # The toggle reads this to decide hide-vs-show; omitting it made every
        # row render as hidden and every click send visible=true.
        assert item["is_visible"] is True

    def test_hidden_review_reports_is_visible_false(
        self, admin_client, db_session, test_organization, test_admin_user
    ):
        _flagged_review(
            db_session,
            test_organization,
            test_admin_user,
            pid="mod_hidden",
            review_id="rev_mod_2",
            reason="Abusive",
            visible=False,
        )
        db_session.commit()

        res = admin_client.get("/api/v2/admin/reviews/reported")
        assert res.status_code == 200, res.text
        item = next(i for i in res.json()["items"] if i["id"] == "rev_mod_2")
        assert item["is_visible"] is False

    def test_unreported_reason_is_null_not_missing(
        self, admin_client, db_session, test_organization, test_admin_user
    ):
        """A flag raised without a reason still serves the key, as null.

        The column is nullable and the page renders a placeholder for it, so the
        key must be present whatever its value.
        """
        _flagged_review(
            db_session,
            test_organization,
            test_admin_user,
            pid="mod_noreason",
            review_id="rev_mod_3",
            reason=None,
        )
        db_session.commit()

        res = admin_client.get("/api/v2/admin/reviews/reported")
        assert res.status_code == 200, res.text
        item = next(i for i in res.json()["items"] if i["id"] == "rev_mod_3")
        assert "report_reason" in item
        assert item["report_reason"] is None

    def test_only_reported_reviews_are_queued(
        self, admin_client, db_session, test_organization, test_admin_user, test_user_non_admin
    ):
        _flagged_review(
            db_session,
            test_organization,
            test_admin_user,
            pid="mod_clean",
            review_id="rev_mod_4",
            reason="Off topic",
        )
        # A review nobody flagged must never reach the moderation queue.
        #
        # It belongs to a DIFFERENT user on purpose: one review per user per
        # model is now enforced by the database (D-26), and two reviews of the
        # same model by the same person is a state the app has always refused
        # to create.
        db_session.add(
            ModelReview(
                id="rev_mod_5",
                model_project_id="mod_clean",
                user_id=test_user_non_admin.id,
                organization_id=test_organization.id,
                rating=5,
                comment="All good",
                is_reported=False,
            )
        )
        db_session.commit()

        res = admin_client.get("/api/v2/admin/reviews/reported")
        assert res.status_code == 200, res.text
        ids = {i["id"] for i in res.json()["items"]}
        assert "rev_mod_4" in ids
        assert "rev_mod_5" not in ids

    def test_requires_admin(self, authenticated_client, db_session):
        res = authenticated_client.get("/api/v2/admin/reviews/reported")
        assert res.status_code == 403, res.text


class TestVisibilityToggleShape:
    def test_toggle_reports_the_new_visibility(
        self, admin_client, db_session, test_organization, test_admin_user
    ):
        _flagged_review(
            db_session,
            test_organization,
            test_admin_user,
            pid="mod_toggle",
            review_id="rev_mod_6",
            reason="Spam",
        )
        db_session.commit()

        res = admin_client.patch("/api/v2/admin/reviews/rev_mod_6/visibility?visible=false")
        assert res.status_code == 200, res.text
        assert res.json() == {"status": "updated", "is_visible": False}

        db_session.expire_all()
        review = db_session.get(ModelReview, "rev_mod_6")
        assert review.is_visible is False
        # Acting on a report clears the flag — the row leaves the queue.
        assert review.is_reported is False


class TestTheQueueSaysWhoComplained:
    """# CONTRACT-TEST: the moderator sees how many people reported, and which.

    The review row's single reason answered neither question. Driving the app
    showed the consequence (QA, 2026-08-20): five reports from two people, and
    the queue row carried one sentence, the last one written.
    """

    @staticmethod
    def _report(db, review_id, user, reason):
        from app.shared.utils.id_generator import generate_id

        db.add(
            ModelReviewReport(
                id=generate_id("rrp_"),
                review_id=review_id,
                user_id=user.id,
                organization_id=user.organization_id,
                reason=reason,
            )
        )
        db.flush()

    def test_the_row_counts_the_people_and_names_them(
        self, admin_client, db_session, test_organization, test_admin_user, test_user
    ):
        _flagged_review(
            db_session,
            test_organization,
            test_admin_user,
            pid="mod_who",
            review_id="rev_mod_who",
            reason="Abusive",
        )
        self._report(db_session, "rev_mod_who", test_admin_user, "Abusive")
        self._report(db_session, "rev_mod_who", test_user, "Spam link in the comment")
        db_session.commit()

        res = admin_client.get("/api/v2/admin/reviews/reported")
        assert res.status_code == 200, res.text
        item = next(i for i in res.json()["items"] if i["id"] == "rev_mod_who")

        assert item["report_count"] == 2
        reasons = {r["reason"] for r in item["reports"]}
        assert reasons == {"Abusive", "Spam link in the comment"}
        reporters = {r["user_id"] for r in item["reports"]}
        assert reporters == {test_admin_user.id, test_user.id}

    def test_a_review_nobody_reported_through_the_endpoint_counts_zero(
        self, admin_client, db_session, test_organization, test_admin_user
    ):
        """The flag can be set without rows behind it — a review flagged before
        the table existed. The count says zero rather than guessing one."""
        _flagged_review(
            db_session,
            test_organization,
            test_admin_user,
            pid="mod_legacy",
            review_id="rev_mod_legacy",
            reason="Flagged the old way",
        )
        db_session.commit()

        res = admin_client.get("/api/v2/admin/reviews/reported")
        item = next(i for i in res.json()["items"] if i["id"] == "rev_mod_legacy")
        assert item["report_count"] == 0
        assert item["reports"] == []
        assert item["report_reason"] == "Flagged the old way"

    def test_deciding_the_review_answers_the_reports(
        self, admin_client, db_session, test_organization, test_admin_user, test_user
    ):
        """Hiding or restoring a review is the decision the reports asked for.

        Leaving the rows behind would let one answered complaint keep counting.
        """
        _flagged_review(
            db_session,
            test_organization,
            test_admin_user,
            pid="mod_decided",
            review_id="rev_mod_decided",
            reason="Abusive",
        )
        self._report(db_session, "rev_mod_decided", test_user, "Abusive")
        db_session.commit()

        res = admin_client.patch("/api/v2/admin/reviews/rev_mod_decided/visibility?visible=false")
        assert res.status_code == 200, res.text

        remaining = (
            db_session.query(ModelReviewReport)
            .filter(ModelReviewReport.review_id == "rev_mod_decided")
            .count()
        )
        assert remaining == 0
