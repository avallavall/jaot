"""Switching a schedule off after five failures still tells the owner.

``_increment_failure_counter`` does three things on the fifth consecutive
failure: it disables the schedule, it disables the Beat task behind it, and it
queues a webhook plus an in-app notification saying so.

Disabling the Beat task means calling
``PeriodicTaskChanged.update_from_session``. That function's ``commit``
argument defaults to True and its body is ``connection.commit()`` on the
Session's own connection, so the flushed rows become durable without the
Session knowing. Two things follow, both silent:

* ``after_commit`` never fires, so a webhook queued through
  ``queue_after_commit`` is never sent.
* The Session's transaction is now inactive, so the caller's ``db.commit()``
  raises ``InvalidRequestError``, the handler rolls back, and the rollback
  cancels every webhook the tick had queued.

Net result: the schedule is off in the database, and nobody is told. The three
calls in ``schedule_service`` already pass ``commit=False``; ``cron_tasks`` was
the one that did not.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event

from app.models.trigger import SolveTrigger, TriggerSchedule
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

pytestmark = pytest.mark.contract


@pytest.fixture
def trigger_and_schedule(db_session, test_organization, test_user):
    """A trigger one failure short of being switched off, with a Beat task id."""
    now = utcnow()
    trigger = SolveTrigger(
        id=generate_id("trg_"),
        organization_id=test_organization.id,
        created_by=test_user.id,
        name="Nightly plan",
        trigger_secret="a" * 64,
        webhook_url="https://example.com/hook",
        is_enabled=True,
        total_runs=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(trigger)
    db_session.flush()
    schedule = TriggerSchedule(
        id=generate_id("tsch_"),
        trigger_id=trigger.id,
        organization_id=test_organization.id,
        cron_expression="*/5 * * * *",
        timezone="UTC",
        is_enabled=True,
        consecutive_failures=4,
        # Any value: the code only checks that it is set before telling Beat.
        beat_task_id=1,
        created_at=now,
        updated_at=now,
    )
    db_session.add(schedule)
    db_session.commit()
    return trigger, schedule


# CONTRACT-TEST: telling Beat about the change must not commit the session.
def test_beat_is_told_without_committing_the_session(db_session, trigger_and_schedule) -> None:
    trigger, schedule = trigger_and_schedule
    from app.tasks.cron_tasks import _increment_failure_counter

    with (
        patch("sqlalchemy_celery_beat.models.PeriodicTaskChanged.update_from_session") as told,
        patch("app.services.notification_service.NotificationService", MagicMock()),
    ):
        _increment_failure_counter(db_session, schedule, trigger)

    assert told.call_count == 1
    assert told.call_args.kwargs.get("commit") is False, (
        "update_from_session was left on its commit=True default, which commits the "
        "session's connection behind its back"
    )


# CONTRACT-TEST: the auto-disabled webhook survives to the commit and is sent.
#
# This runs the real update_from_session, because the defect only exists in the
# interaction between it and queue_after_commit.
def test_the_auto_disabled_webhook_is_actually_sent(db_session, trigger_and_schedule) -> None:
    trigger, schedule = trigger_and_schedule
    from app.tasks.cron_tasks import _increment_failure_counter

    with (
        patch("app.tasks.webhook_tasks.deliver_webhook_task.delay") as delay,
        patch("app.services.notification_service.NotificationService", MagicMock()),
    ):
        _increment_failure_counter(db_session, schedule, trigger)
        # The caller's commit is what releases the queued webhook.
        db_session.commit()

    assert schedule.is_enabled is False, "the schedule was not switched off"
    assert delay.call_count == 1, (
        "the schedule was switched off and the webhook announcing it never went out"
    )
    assert delay.call_args.args[0] == trigger.webhook_url


# CONTRACT-TEST: the caller's own commit still works afterwards.
def test_the_transaction_is_still_alive_after_beat_is_told(
    db_session, trigger_and_schedule
) -> None:
    trigger, schedule = trigger_and_schedule
    from app.tasks.cron_tasks import _increment_failure_counter

    committed: list[int] = []

    def _note(_session: object) -> None:
        committed.append(1)

    event.listen(db_session, "after_commit", _note)
    try:
        with (
            patch("app.tasks.webhook_tasks.deliver_webhook_task.delay"),
            patch("app.services.notification_service.NotificationService", MagicMock()),
        ):
            _increment_failure_counter(db_session, schedule, trigger)
            db_session.commit()
    finally:
        event.remove(db_session, "after_commit", _note)

    assert committed, "the session's commit did not happen — the transaction was already closed"
