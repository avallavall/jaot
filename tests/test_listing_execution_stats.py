"""Marketplace listing statistics — the tallies behind the public success rate.

`total_executions` was bumped only on success and nothing ever wrote
`success_rate`, so the column stayed NULL and the marketplace rendered a dash
beside a model with fourteen recorded runs. These tests pin the arithmetic that
replaced it: every run moves the rate, only timed successes move the average.
"""

import pytest

from app.models.model_project import ModelProject, ModelProjectListing
from app.services.marketplace_fusion import record_listing_execution
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def listing(db_session, test_organization):
    """A published listing with no runs recorded yet."""
    project = ModelProject(
        id=generate_id("mp_"),
        organization_id=test_organization.id,
        name="Stats Fixture",
    )
    db_session.add(project)
    db_session.flush()

    row = ModelProjectListing(
        model_project_id=project.id,
        name="Stats Fixture",
        display_name="Stats Fixture",
        description="Counts runs for the marketplace statistics tests.",
        category="hr",
        version="1.0.0",
        status="published",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _reload(db_session, listing):
    db_session.flush()
    db_session.refresh(listing)
    return listing


class TestRecordListingExecution:
    def test_a_success_is_counted_and_timed(self, db_session, listing):
        record_listing_execution(
            db_session, listing.model_project_id, succeeded=True, execution_time_ms=250.0
        )
        row = _reload(db_session, listing)

        assert row.total_executions == 1
        assert row.successful_executions == 1
        assert row.timed_executions == 1
        assert row.success_rate == pytest.approx(1.0)
        assert row.avg_execution_time_ms == pytest.approx(250.0)

    # CONTRACT-TEST: a failed run must reach the denominator. Counting only
    # successes is what left success_rate with nothing to divide by, and would
    # otherwise make every listing on the marketplace look flawless.
    def test_a_failure_lowers_the_success_rate(self, db_session, listing):
        for _ in range(3):
            record_listing_execution(
                db_session, listing.model_project_id, succeeded=True, execution_time_ms=100.0
            )
        record_listing_execution(
            db_session, listing.model_project_id, succeeded=False, execution_time_ms=None
        )
        row = _reload(db_session, listing)

        assert row.total_executions == 4
        assert row.successful_executions == 3
        assert row.success_rate == pytest.approx(0.75)

    def test_a_failure_does_not_move_the_average(self, db_session, listing):
        record_listing_execution(
            db_session, listing.model_project_id, succeeded=True, execution_time_ms=400.0
        )
        record_listing_execution(
            db_session, listing.model_project_id, succeeded=False, execution_time_ms=None
        )
        row = _reload(db_session, listing)

        assert row.timed_executions == 1
        assert row.avg_execution_time_ms == pytest.approx(400.0)

    def test_the_average_is_over_timed_runs_only(self, db_session, listing):
        """Runs backfilled without a duration must not dilute the mean.

        A listing carrying successes from before timings were kept has
        successful_executions > timed_executions; dividing by the larger count
        would report an average several times too fast.
        """
        listing.successful_executions = 10
        listing.total_executions = 10
        db_session.flush()

        record_listing_execution(
            db_session, listing.model_project_id, succeeded=True, execution_time_ms=600.0
        )
        row = _reload(db_session, listing)

        assert row.successful_executions == 11
        assert row.timed_executions == 1
        assert row.avg_execution_time_ms == pytest.approx(600.0)

    def test_an_untouched_listing_reports_nothing_rather_than_zero(self, db_session, listing):
        """No runs means no rate — 0% would read as "this model always fails"."""
        row = _reload(db_session, listing)

        assert row.total_executions == 0
        assert row.success_rate is None
        assert row.avg_execution_time_ms is None

    def test_an_unknown_listing_is_a_no_op(self, db_session, listing):
        record_listing_execution(
            db_session, "mp_does_not_exist", succeeded=True, execution_time_ms=10.0
        )
        row = _reload(db_session, listing)

        assert row.total_executions == 0
