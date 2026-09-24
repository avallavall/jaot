"""A triggered solve is held to the same rules as every other solve.

# CONTRACT-TEST: a triggered solve runs on its solver's worker, with its solver, under the caps.

Found in the 2026-09-24 review:

- The task was queued on ``jaot_default``, the small worker that sends email and
  webhooks, with no Celery time limit; one long triggered solve held it for
  hours and a large one killed it for memory.
- ``SolverService().solve(problem)`` ran every triggered solve on SCIP, whatever
  solver the model chose.
- The variable cap, the time-limit ceiling and the daily quota did not apply.
- A deactivated organization kept firing through its trigger secret and its
  cron schedules.
- The fire limit was charged before the secret was checked, so anyone who saw
  the fire URL could spend a trigger's daily budget with a wrong secret.
- Deleting a trigger left its Beat entry firing forever.
- A schedule whose model failed in the worker on every tick never auto-disabled.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models import ModelExecution, Organization, User
from app.models.trigger import TriggerRun, TriggerSchedule
from app.services import trigger_service
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.services.schedule_service import validate_cron_expression
from tests.test_trigger_execution import _create_doc, _create_trigger, _create_version

_LP = {
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
        {"name": "y", "type": "continuous", "lower_bound": 0, "upper_bound": 10},
    ],
    "constraints": [{"name": "cap", "expression": "x + y <= 12"}],
    "objective": {"expression": "3*x + 2*y", "sense": "maximize"},
    "options": {"time_limit_seconds": 90},
}


def _trigger(db: Session, org: Organization, user: User, model: dict):
    doc = _create_doc(db, org, user, model_json=model)
    version = _create_version(db, doc, model_json=model)
    return _create_trigger(db, org, user, doc, version)


def _run_task(db: Session, trigger, run, **kwargs):
    from app.tasks.trigger_tasks import trigger_solve_task

    with (
        patch("app.tasks.trigger_tasks.SessionLocal", return_value=db),
        patch("app.tasks.trigger_tasks._deliver_webhook"),
    ):
        return trigger_solve_task(
            run_id=run.id, trigger_id=trigger.id, override_data=None, **kwargs
        )


@pytest.mark.parametrize(("solver", "queue"), [("highs", "solve_highs"), (None, "solve_scip")])
def test_the_solve_is_queued_on_its_solvers_worker_with_limits(
    db_session, test_organization, test_user, solver, queue
):
    trigger, _ = _trigger(db_session, test_organization, test_user, {**_LP, "solver_name": solver})
    with patch("app.tasks.trigger_tasks.trigger_solve_task.apply_async") as apply_async:
        trigger_service.fire_trigger(db_session, trigger, None)
        db_session.commit()

    assert apply_async.call_count == 1
    call = apply_async.call_args.kwargs
    assert call["queue"] == queue
    assert call["kwargs"]["solver_name"] == (solver or "scip")
    assert call["kwargs"]["time_limit_seconds"] == 90
    assert call["soft_time_limit"] > 90
    assert call["time_limit"] > call["soft_time_limit"]


def test_the_solve_uses_the_models_own_solver(db_session, test_organization, test_user):
    trigger, _ = _trigger(db_session, test_organization, test_user, {**_LP, "solver_name": "highs"})
    run = trigger_service.create_run(db_session, trigger, None, "pending")
    db_session.commit()

    result = _run_task(db_session, trigger, run)

    assert result["status"] == "completed"
    execution = db_session.get(ModelExecution, result["execution_id"])
    assert execution.solver_name == "highs"


def test_the_variable_cap_refuses_a_triggered_solve(db_session, test_organization, test_user):
    PSS.set(db_session, "instance_max_variables", "1")
    db_session.commit()
    trigger, _ = _trigger(db_session, test_organization, test_user, _LP)
    run = trigger_service.create_run(db_session, trigger, None, "pending")
    db_session.commit()
    run_id = run.id

    result = _run_task(db_session, trigger, run)

    assert result["status"] == "failed"
    stored = db_session.get(TriggerRun, run_id)
    assert stored.status == "failed"
    assert "variables" in stored.error_message


def test_a_deactivated_organization_cannot_fire(client, db_session, test_organization, test_user):
    trigger, secret = _trigger(db_session, test_organization, test_user, _LP)
    test_organization.is_active = False
    db_session.commit()

    response = client.post(
        f"/api/v2/triggers/{trigger.id}/fire",
        headers={"Authorization": f"Bearer {secret}"},
        json={},
    )
    assert response.status_code == 403

    from app.tasks.cron_tasks import cron_fire_task

    db_session.add(
        TriggerSchedule(
            id="tsch_inactive_owner",
            trigger_id=trigger.id,
            organization_id=trigger.organization_id,
            cron_expression="0 3 * * *",
            timezone="UTC",
            is_enabled=True,
            consecutive_failures=0,
        )
    )
    db_session.commit()
    with patch("app.tasks.cron_tasks.SessionLocal", return_value=db_session):
        assert cron_fire_task(trigger.id)["reason"] == "owner_inactive"
    assert db_session.query(TriggerRun).filter_by(trigger_id=trigger.id).count() == 0


def test_a_wrong_secret_does_not_spend_the_triggers_budget(
    client, db_session, test_organization, test_user
):
    from app.shared.core import rate_limiter

    trigger, secret = _trigger(db_session, test_organization, test_user, _LP)
    saved = (rate_limiter._bypass, rate_limiter._force_real)
    rate_limiter._bypass, rate_limiter._force_real = False, True
    rate_limiter.clear()
    try:
        for _ in range(12):  # more than the trigger's 10 a minute
            wrong = client.post(
                f"/api/v2/triggers/{trigger.id}/fire",
                headers={"Authorization": "Bearer not-the-secret"},
                json={},
            )
            assert wrong.status_code == 401
        with patch("app.tasks.trigger_tasks.trigger_solve_task.apply_async"):
            right = client.post(
                f"/api/v2/triggers/{trigger.id}/fire",
                headers={"Authorization": f"Bearer {secret}"},
                json={},
            )
        assert right.status_code == 202, right.text
    finally:
        rate_limiter.clear()
        rate_limiter._bypass, rate_limiter._force_real = saved


def test_a_cron_run_that_fails_in_the_worker_counts_toward_auto_disable(
    db_session, test_organization, test_user
):
    broken = {**_LP, "objective": {"expression": "3*x + ghost", "sense": "maximize"}}
    trigger, _ = _trigger(db_session, test_organization, test_user, broken)
    schedule = TriggerSchedule(
        id="tsch_counts",
        trigger_id=trigger.id,
        organization_id=trigger.organization_id,
        cron_expression="0 3 * * *",
        timezone="UTC",
        is_enabled=True,
        consecutive_failures=0,
    )
    db_session.add(schedule)
    db_session.commit()

    for expected in (1, 2):
        run = trigger_service.create_run(db_session, trigger, None, "pending")
        run.source = "cron"
        db_session.commit()
        _run_task(db_session, trigger, run)
        db_session.expire_all()
        assert db_session.get(TriggerSchedule, "tsch_counts").consecutive_failures == expected


def test_the_interval_floor_reads_the_tightest_gap_not_the_first():
    with pytest.raises(ValueError, match="too frequently"):
        validate_cron_expression("*/5 9 * * *", "UTC", min_interval_minutes=60)
    assert validate_cron_expression("0 9 * * *", "UTC", min_interval_minutes=60)["valid"]


def _beat_entry(db: Session, trigger_id: str):
    from sqlalchemy_celery_beat.models import PeriodicTask

    return db.query(PeriodicTask).filter(PeriodicTask.name == f"cron_trigger_{trigger_id}").first()


def test_deleting_a_trigger_removes_its_beat_entry(
    authenticated_client, db_session, test_organization, test_user
):
    from app.services.schedule_service import create_schedule

    trigger, _ = _trigger(db_session, test_organization, test_user, _LP)
    create_schedule(db_session, trigger, "0 3 * * *", "UTC")
    db_session.commit()
    assert _beat_entry(db_session, trigger.id) is not None

    response = authenticated_client.delete(f"/api/v2/triggers/{trigger.id}")
    assert response.status_code == 204, response.text
    db_session.expire_all()
    assert _beat_entry(db_session, trigger.id) is None


def test_a_tick_for_a_trigger_that_is_gone_retires_its_beat_entry(
    db_session, test_organization, test_user
):
    """Entries left behind before the fix, or by a cascade delete of a project."""
    from app.services.schedule_service import create_schedule
    from app.tasks.cron_tasks import cron_fire_task

    trigger, _ = _trigger(db_session, test_organization, test_user, _LP)
    create_schedule(db_session, trigger, "0 3 * * *", "UTC")
    db_session.commit()
    trigger_id = trigger.id
    db_session.delete(trigger)  # the schedule goes by cascade, the Beat row does not
    db_session.commit()
    assert _beat_entry(db_session, trigger_id) is not None

    with patch("app.tasks.cron_tasks.SessionLocal", return_value=db_session):
        assert cron_fire_task(trigger_id)["reason"] == "trigger_not_found"
    assert _beat_entry(db_session, trigger_id) is None
