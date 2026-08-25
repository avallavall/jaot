"""A trigger run is committed before anybody is told it exists.

Two bugs of the same shape, found together.

``fire_trigger`` queued ``trigger_solve_task`` at the call site, while
``create_run`` had only flushed. The worker owns a different connection, so it
could look for the run before the caller committed, answer ``run_not_found``
and stop — leaving the row ``pending`` for good. The cron overlap check reads
``pending`` as "still running", and nothing reaps a stale ``TriggerRun``, so a
schedule that lost that race never fired again.

``POST /triggers/{id}/runs/{run_id}/rerun`` never committed at all. ``get_db``
closes the session without one, so the run, the bumped counters and the queued
solve were all rolled back while the response still returned a run id and
``status="pending"``. Every rerun reported success and did nothing.

The tests below hold both ends: nothing is queued before the commit, nothing is
queued when the caller rolls back, and an endpoint that answers 202 has
committed by the time it does. The queued job is the only evidence available
from this suite — the ``get_db`` override yields the test's own session and
never closes it, so a flushed-but-uncommitted row is still readable here.
Asking "was the job queued?" asks about the commit itself, which that override
cannot fake.
"""

from __future__ import annotations

import hashlib
import secrets
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.testclient import TestClient as PlainClient

from app.models import Organization, User
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.models.trigger import SolveTrigger
from app.services import trigger_service
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

pytestmark = pytest.mark.contract

QUEUE = "app.tasks.trigger_tasks.trigger_solve_task.delay"
WEBHOOK_QUEUE = "app.tasks.webhook_tasks.deliver_webhook_task.delay"


def _committed_trigger(
    db: Session,
    org: Organization,
    user: User,
    override_schema: list[dict[str, object]] | None = None,
) -> tuple[SolveTrigger, str]:
    """A trigger, its document and its version, all committed. Returns the secret too."""
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=org.id,
        created_by=user.id,
        name="Contract document",
        canvas_json={"nodes": [], "edges": []},
        model_json={"variables": [], "constraints": [], "objective": {}},
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    db.flush()

    version = ModelVersion(
        id=generate_id("ver_"),
        document_id=doc.id,
        organization_id=org.id,
        canvas_json=doc.canvas_json,
        model_json=doc.model_json,
        change_summary="Initial version",
        is_named=True,
        version_name="v1.0",
        sequence=1,
        created_at=now,
    )
    db.add(version)
    db.flush()

    plaintext = secrets.token_hex(16)
    trigger = SolveTrigger(
        id=generate_id("trg_"),
        organization_id=org.id,
        created_by=user.id,
        name="Contract trigger",
        document_id=doc.id,
        version_id=version.id,
        trigger_secret=hashlib.sha256(plaintext.encode()).hexdigest(),
        override_schema=override_schema,
        webhook_url="https://example.com/hook",
        webhook_secret=None,
        is_enabled=True,
        total_runs=0,
        created_at=now,
        updated_at=now,
    )
    db.add(trigger)
    db.commit()
    return trigger, plaintext


# CONTRACT-TEST: the solve job is queued on the commit, never before it.
def test_the_solve_job_waits_for_the_commit(
    db_session: Session, test_organization: Organization, test_user: User
) -> None:
    trigger, _ = _committed_trigger(db_session, test_organization, test_user)
    with patch(QUEUE) as delay:
        run, error = trigger_service.fire_trigger(db_session, trigger, None)
        assert error is None
        assert delay.call_count == 0, "queued before the run row was committed"

        db_session.commit()
        assert delay.call_count == 1, "the solve was never queued after the commit"
        assert delay.call_args.args[0] == run.id


# CONTRACT-TEST: a caller that rolls back queues no solve.
def test_a_rolled_back_fire_queues_nothing(
    db_session: Session, test_organization: Organization, test_user: User
) -> None:
    trigger, _ = _committed_trigger(db_session, test_organization, test_user)
    with patch(QUEUE) as delay:
        trigger_service.fire_trigger(db_session, trigger, None)
        db_session.rollback()
        assert delay.call_count == 0, "queued a solve for a run that was rolled back"


# CONTRACT-TEST: a stale listener does not queue somebody else's work.
#
# A Celery task holds one session for its whole run. If a fire is rolled back
# and the same session commits something unrelated later, the cancelled job
# must stay cancelled.
def test_a_later_unrelated_commit_does_not_revive_a_cancelled_job(
    db_session: Session, test_organization: Organization, test_user: User
) -> None:
    trigger, _ = _committed_trigger(db_session, test_organization, test_user)
    with patch(QUEUE) as delay:
        trigger_service.fire_trigger(db_session, trigger, None)
        db_session.rollback()

        trigger = db_session.merge(trigger)
        trigger.name = "Renamed, and nothing to do with that run"
        db_session.commit()
        assert delay.call_count == 0, "a rolled-back solve was queued by a later commit"


# CONTRACT-TEST: /rerun commits. A 202 that rolled back is a lie.
def test_rerun_commits_the_run_it_reports(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    test_user: User,
) -> None:
    trigger, _ = _committed_trigger(db_session, test_organization, test_user)
    original = trigger_service.create_run(db_session, trigger, {"capacity": 50}, "completed")
    db_session.commit()

    with patch(QUEUE) as delay:
        response = authenticated_client.post(
            f"/api/v2/triggers/{trigger.id}/runs/{original.id}/rerun"
        )

        assert response.status_code == 202, response.text
        assert delay.call_count == 1, "the rerun answered 202 without committing anything"
        assert delay.call_args.args[0] == response.json()["run_id"]


# CONTRACT-TEST: /fire commits too — the same 202, the same requirement.
def test_fire_commits_the_run_it_reports(
    authenticated_client: TestClient,
    db_session: Session,
    test_organization: Organization,
    test_user: User,
) -> None:
    trigger, secret = _committed_trigger(db_session, test_organization, test_user)
    with patch(QUEUE) as delay:
        # Fire authenticates on the trigger secret, not on the session.
        fresh = PlainClient(authenticated_client.app)
        response = fresh.post(
            f"/api/v2/triggers/{trigger.id}/fire",
            json={},
            headers={"Authorization": f"Bearer {secret}"},
        )

        assert response.status_code == 202, response.text
        assert delay.call_count == 1, "the fire answered 202 without committing anything"
        assert delay.call_args.args[0] == response.json()["run_id"]


# CONTRACT-TEST: the validation-failure webhook also waits for the commit.
#
# `deliver_webhook_task` writes the attempt count onto the run, so a delivery
# that starts before the run exists cannot record anything against it.
def test_a_validation_failure_queues_its_webhook_on_the_commit(
    db_session: Session, test_organization: Organization, test_user: User
) -> None:
    trigger, _ = _committed_trigger(
        db_session,
        test_organization,
        test_user,
        override_schema=[{"name": "capacity", "required": True}],
    )
    with patch(WEBHOOK_QUEUE) as delay:
        run, error = trigger_service.fire_trigger(db_session, trigger, {"unknown": 1})
        assert error is not None
        assert delay.call_count == 0, "queued before the failed run was committed"

        db_session.commit()
        assert delay.call_count == 1, "the webhook was never queued after the commit"
        assert delay.call_args.args[-1] == run.id
