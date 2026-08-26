"""The reaper settles stale trigger runs too (D-36).

A ``TriggerRun`` nobody will ever finish is worse than a wrong-looking history
row. ``cron_fire_task`` refuses to fire while any run of that trigger is
'pending' or 'running', so one abandoned run stops that schedule for good — and
every later tick records ``skipped_overlap``, which is exactly what normal
overlap protection looks like.

The last test is the one that matters: it runs the real cron task against a
trigger blocked by an abandoned run, and shows the sweep unblocks it.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest

from app.models import Organization, User
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.models.trigger import SolveTrigger, TriggerRun, TriggerSchedule
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id
from app.tasks import execution_reaper
from app.tasks.execution_reaper import reap_stale_trigger_runs

# Seeded from the settings registry by the _seed_platform_settings autouse fixture.
PENDING_MAX = 1800
RUNNING_MAX = 172800


@pytest.fixture(autouse=True)
def _no_broker_evidence():
    """The fleet holds nothing, stated rather than inferred from a dead broker.

    The sweep asks the broker which runs a worker is still holding. There is no
    broker in the test environment, so without this the answer would be "could
    not reach it" and every test here would be measuring the connection failure
    instead of the sweep.
    """
    with patch.object(execution_reaper, "_runs_a_worker_still_holds", return_value=frozenset()):
        yield


@pytest.fixture
def trigger(db_session, test_organization: Organization, test_user: User) -> SolveTrigger:
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=test_organization.id,
        created_by=test_user.id,
        name="Reaper document",
        canvas_json={"nodes": [], "edges": []},
        model_json={"variables": [], "constraints": [], "objective": {}},
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db_session.add(doc)
    db_session.flush()
    version = ModelVersion(
        id=generate_id("ver_"),
        document_id=doc.id,
        organization_id=test_organization.id,
        canvas_json=doc.canvas_json,
        model_json=doc.model_json,
        change_summary="v1",
        is_named=True,
        version_name="v1.0",
        sequence=1,
        created_at=now,
    )
    db_session.add(version)
    db_session.flush()
    trg = SolveTrigger(
        id=generate_id("trg_"),
        organization_id=test_organization.id,
        created_by=test_user.id,
        name="Reaper trigger",
        document_id=doc.id,
        version_id=version.id,
        trigger_secret="a" * 64,
        webhook_url="https://example.com/hook",
        is_enabled=True,
        total_runs=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(trg)
    db_session.commit()
    return trg


def _run(db_session, trigger: SolveTrigger, *, status: str, age_seconds: int) -> TriggerRun:
    run = TriggerRun(
        id=generate_id("trun_"),
        trigger_id=trigger.id,
        organization_id=trigger.organization_id,
        status=status,
        source="cron",
        webhook_attempts=0,
        created_at=utcnow() - timedelta(seconds=age_seconds),
    )
    db_session.add(run)
    db_session.commit()
    return run


def test_a_pending_run_past_the_threshold_is_failed(db_session, trigger):
    run = _run(db_session, trigger, status="pending", age_seconds=PENDING_MAX + 60)

    summary = reap_stale_trigger_runs(db_session)

    db_session.refresh(run)
    assert summary["failed"] == 1
    assert run.status == "failed"
    assert run.completed_at is not None
    assert "Reaped" in (run.error_message or "")
    # The message names the state it was stuck in, not the state it ends in.
    assert "'pending'" in run.error_message


def test_a_fresh_pending_run_is_left_alone(db_session, trigger):
    run = _run(db_session, trigger, status="pending", age_seconds=60)

    reap_stale_trigger_runs(db_session)

    db_session.refresh(run)
    assert run.status == "pending"
    assert run.error_message is None


def test_a_running_run_gets_the_longer_threshold(db_session, trigger):
    # Past the pending limit but far short of the running one: a real solve.
    run = _run(db_session, trigger, status="running", age_seconds=PENDING_MAX + 3600)

    summary = reap_stale_trigger_runs(db_session)

    db_session.refresh(run)
    assert run.status == "running", "a legitimately long solve was reaped"
    # Not merely skipped in Python: the query never selects it. The floor is per
    # status now, so a 'running' row inside its own 48-hour limit is not a
    # candidate at all and cannot crowd out the rows that are.
    assert summary["scanned"] == 0


def test_a_running_run_past_the_running_threshold_is_failed(db_session, trigger):
    run = _run(db_session, trigger, status="running", age_seconds=RUNNING_MAX + 60)

    reap_stale_trigger_runs(db_session)

    db_session.refresh(run)
    assert run.status == "failed"
    assert "'running'" in (run.error_message or "")


def test_a_settled_run_is_never_touched(db_session, trigger):
    run = _run(db_session, trigger, status="completed", age_seconds=RUNNING_MAX * 2)

    summary = reap_stale_trigger_runs(db_session)

    db_session.refresh(run)
    assert summary["scanned"] == 0
    assert run.status == "completed"
    assert run.error_message is None


def test_a_broken_row_does_not_stop_the_sweep(db_session, trigger):
    _run(db_session, trigger, status="pending", age_seconds=PENDING_MAX + 600)
    second = _run(db_session, trigger, status="pending", age_seconds=PENDING_MAX + 60)

    calls = {"n": 0}
    real = execution_reaper._reap_one_trigger_run

    def explode_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("poisoned row")
        return real(*args, **kwargs)

    with patch.object(execution_reaper, "_reap_one_trigger_run", explode_once):
        summary = reap_stale_trigger_runs(db_session)

    db_session.refresh(second)
    assert summary["errors"] == 1
    assert summary["failed"] == 1
    assert second.status == "failed", "one bad row stopped the rest of the sweep"


# The whole point of D-36: an abandoned run stops the schedule, and the sweep
# has to give it back.
def test_the_sweep_unblocks_a_schedule_an_abandoned_run_was_holding(db_session, trigger, test_user):
    from app.tasks.cron_tasks import cron_fire_task

    now = utcnow()
    schedule = TriggerSchedule(
        id=generate_id("tsch_"),
        trigger_id=trigger.id,
        organization_id=trigger.organization_id,
        cron_expression="*/5 * * * *",
        timezone="UTC",
        is_enabled=True,
        consecutive_failures=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(schedule)
    db_session.commit()

    abandoned = _run(db_session, trigger, status="pending", age_seconds=PENDING_MAX + 600)

    # `cron_fire_task` closes the session it is handed, and the test still needs it.
    with (
        patch.object(db_session, "close", lambda: None),
        patch("app.tasks.cron_tasks.SessionLocal", return_value=db_session),
        patch("app.services.trigger_service._queue_solve_task"),
    ):
        # Blocked: the abandoned run reads as "still running".
        blocked = cron_fire_task(trigger.id)
        assert blocked["status"] == "skipped_overlap"

        reap_stale_trigger_runs(db_session)
        db_session.refresh(abandoned)
        assert abandoned.status == "failed"

        # And now it fires.
        fired = cron_fire_task(trigger.id)

    assert fired["status"] == "pending", "the schedule was still blocked after the sweep"


# CONTRACT-TEST: a run a worker still holds is never reaped.
#
# 'pending' does not only mean lost — it also means queued. The pending limit is
# 30 minutes and a solve may run for 48 hours, so a busy queue would have its
# live jobs marked failed.
def test_a_run_a_worker_still_holds_is_not_reaped(db_session, trigger):
    run = _run(db_session, trigger, status="pending", age_seconds=PENDING_MAX + 600)

    with patch.object(
        execution_reaper, "_runs_a_worker_still_holds", return_value=frozenset({run.id})
    ):
        summary = reap_stale_trigger_runs(db_session)

    db_session.refresh(run)
    assert summary["failed"] == 0
    assert summary["skipped"] == 1
    assert run.status == "pending", "a solve still queued on a worker was reaped"


# CONTRACT-TEST: a run the worker settled between the SELECT and the write wins.
#
# The sweep selects without a lock. Writing 'failed' over a run the worker just
# completed reports a finished solve as a failure and orphans its result.
def test_a_run_settled_after_the_select_is_not_overwritten(db_session, trigger):
    run = _run(db_session, trigger, status="pending", age_seconds=PENDING_MAX + 600)

    real_refresh = db_session.refresh

    def settle_then_refresh(obj, *args, **kwargs):
        """Stand in for the worker finishing the run while the sweep holds it."""
        if isinstance(obj, TriggerRun) and obj.status == "pending":
            obj.status = "completed"
            return None
        return real_refresh(obj, *args, **kwargs)

    with patch.object(db_session, "refresh", settle_then_refresh):
        summary = reap_stale_trigger_runs(db_session)

    assert summary["failed"] == 0
    assert summary["skipped"] == 1
    db_session.expire_all()
    assert db_session.get(TriggerRun, run.id).status == "completed"


# CONTRACT-TEST: old 'running' rows never crowd the 'pending' rows out.
#
# A single min(pending_max, running_max) floor let every 'running' row past 30
# minutes into the window to be judged against the 48-hour limit and skipped.
# Ordered oldest first and capped at 500, those skips starve the 'pending' rows
# the sweep exists to rescue — and the summary log only fires on a failure, so
# it goes quiet exactly when it stops working.
def test_long_running_rows_do_not_crowd_out_the_pending_ones(db_session, trigger):
    for i in range(6):
        _run(db_session, trigger, status="running", age_seconds=RUNNING_MAX - 3600 - i)
    stuck = _run(db_session, trigger, status="pending", age_seconds=PENDING_MAX + 60)

    with patch.object(execution_reaper, "_MAX_ROWS_PER_SWEEP", 3):
        summary = reap_stale_trigger_runs(db_session)

    db_session.refresh(stuck)
    assert stuck.status == "failed", f"the abandoned run was never examined: {summary}"


# The sweep still runs when the broker cannot be asked. Refusing to would put
# D-36 straight back: an abandoned run blocking its cron for good.
def test_a_silent_broker_does_not_stop_the_sweep(db_session, trigger):
    run = _run(db_session, trigger, status="pending", age_seconds=PENDING_MAX + 600)

    with patch.object(execution_reaper, "_runs_a_worker_still_holds", return_value=None):
        summary = reap_stale_trigger_runs(db_session)

    db_session.refresh(run)
    assert summary["broker_answered"] is False
    assert run.status == "failed"
