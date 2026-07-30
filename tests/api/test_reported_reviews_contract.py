"""The moderation queue's response contract (D-17).

``GET /api/v2/admin/reviews/reported`` had no ``response_model``, and the page
that consumes it was reading three fields the backend has never sent —
``model_id``, ``report_count`` and ``report_reasons`` — plus ``is_visible``,
which the endpoint really did omit. ``report_reasons.length`` on ``undefined``
threw while rendering, so the queue crashed on the first flagged review.

A review carries ONE report flag and ONE reason (``ModelReview.is_reported`` /
``report_reason``). There is no counter anywhere in the model, so these tests
assert the shape the moderator actually needs: the id that links to the
listing, the single reason, and the visibility the toggle acts on.
"""

from app.models import ModelCategory, ModelProject, ModelProjectListing, ModelReview

# CONTRACT-TEST: the moderation queue serves catalog_id + report_reason +
# is_visible; a per-review report counter does not exist in the model.


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
        self, admin_client, db_session, test_organization, test_admin_user
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
        db_session.add(
            ModelReview(
                id="rev_mod_5",
                model_project_id="mod_clean",
                user_id=test_admin_user.id,
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
