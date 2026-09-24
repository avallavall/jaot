"""The Beat entries of the removed billing tasks are deleted, and nothing else.

``process_scheduled_withdrawals`` and ``run_balance_reconciliation`` went with
the money layer, but their Beat rows stayed enabled. Every day the worker got
both, did not know them, and logged "Received unregistered task" with a
KeyError. Seen on the local instance on 2026-09-24: 61 runs of each.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from sqlalchemy.orm import Session

_MIGRATION = (
    Path(__file__).resolve().parents[1] / "infra/alembic/versions/20260924_drop_billing_beat.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("drop_billing_beat", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_the_dead_billing_entries_are_removed(db_session: Session) -> None:
    from sqlalchemy_celery_beat.models import CrontabSchedule, PeriodicTask

    daily = CrontabSchedule(minute="0", hour="3", timezone="UTC")
    db_session.add(daily)
    db_session.flush()
    for name, task in [
        ("process-scheduled-withdrawals", "process_scheduled_withdrawals"),
        ("run-balance-reconciliation", "run_balance_reconciliation"),
        ("cron_trigger_trg_keep", "app.tasks.cron_tasks.cron_fire_task"),
    ]:
        db_session.add(
            PeriodicTask(
                name=name, task=task, schedule_model=daily, args=json.dumps([]), enabled=True
            )
        )
    db_session.commit()

    removed = _migration().delete_dead_beat_entries(db_session.connection())
    db_session.commit()

    assert removed == 2
    left = {name for (name,) in db_session.query(PeriodicTask.name)}
    assert "cron_trigger_trg_keep" in left
    assert not left & {"process-scheduled-withdrawals", "run-balance-reconciliation"}
