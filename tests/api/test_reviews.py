"""Tests for the project-native review-create gate (P1.5 G4).

``POST /api/v2/models/catalog/{id}/reviews`` — the ``{id}`` is the model-project id. A
user may review a model only after their org has *used* it: seeded a fork ModelProject
from the listing (``source_ref``) AND completed an execution. Creating a review rolls the
average rating up onto the listing.
"""

from app.models import (
    ExecutionStatus,
    ModelCategory,
    ModelExecution,
    ModelProject,
    ModelProjectListing,
    ModelReview,
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
