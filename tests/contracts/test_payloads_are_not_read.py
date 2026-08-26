"""The list routes must not read the payloads they never write.

A `ModelExecution` carries the compiled problem and the whole solution. Measured
on the development database, that is **113 kB per row on average** across 1,253
runs — 128 MB in one table. A `ModelProject` carries the working copy of the
model the same way.

So a query that loads the whole entity to render a compact row pays that per
row, invisibly. It has bitten this repo four times now: the author panel, the
GDPR export (128 MB read to write 252 KB, 19.5 s), the studio's
reconcile-on-open, and the reaper's sweep. Each one was found by measuring, not
by reading the code.

These tests ask the database what it was actually sent. Inspecting the objects
afterwards cannot answer it: the session hands the same instances back and
refreshes what it needs, so everything reads as loaded and the test passes on
the broken code.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import ModelExecution, ModelProject, Organization
from app.shared.utils.datetime_helpers import utcnow

pytestmark = pytest.mark.contract

#: Columns that hold a whole problem, a whole solution or a whole model.
_EXECUTION_PAYLOADS = (
    "input_data",
    "result_data",
    "progress_data",
    "scenario_analysis",
)
_PROJECT_PAYLOADS = ("draft_model_json", "draft_canvas_json")


class _Statements:
    """Every statement the database was sent while this was open."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self.seen: list[str] = []

    def __enter__(self) -> _Statements:
        event.listen(self._db.bind, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self._db.bind, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, params, context, executemany) -> None:  # noqa: ANN001
        self.seen.append(statement)

    def assert_never_selected(self, table: str, columns: tuple[str, ...]) -> None:
        for column in columns:
            assert not any(f"{table}.{column}" in q for q in self.seen), (
                f"selected {table}.{column}, which this route never renders"
            )


def _project(db: Session, org: Organization, pid: str) -> ModelProject:
    project = ModelProject(
        id=pid,
        organization_id=org.id,
        name=f"Project {pid}",
        status="active",
        draft_model_json={"variables": [{"name": "x"}]},
        draft_canvas_json={"nodes": []},
    )
    db.add(project)
    db.flush()
    return project


def _run(db: Session, org: Organization, eid: str, project: ModelProject, **over: object):
    fields: dict = {
        "id": eid,
        "organization_id": org.id,
        "model_project_id": project.id,
        "status": "completed",
        "input_data": {"variables": [{"name": "x"}]},
        "result_data": {"objective_value": 1.0},
    }
    fields.update(over)
    run = ModelExecution(**fields)
    db.add(run)
    db.flush()
    return run


# CONTRACT-TEST: the studio's reconcile-on-open reads no payloads.
# `ProjectExecutionItem` is a compact row by design — a status, a task id, an
# objective value. At its limit of 100 rows the query used to pull ~11 MB.
def test_the_project_run_list_does_not_read_the_payloads(
    authenticated_client, db_session: Session, test_organization: Organization
) -> None:
    project = _project(db_session, test_organization, "mp_payload_runs")
    _run(db_session, test_organization, "exe_payload_runs", project)
    db_session.commit()

    with _Statements(db_session) as sql:
        resp = authenticated_client.get(f"/api/v2/projects/{project.id}/executions")

    assert resp.status_code == 200, resp.text
    assert any(r["id"] == "exe_payload_runs" for r in resp.json())
    sql.assert_never_selected("model_executions", _EXECUTION_PAYLOADS)


# CONTRACT-TEST: naming the model on a run row reads no working copy.
def test_the_execution_table_does_not_read_the_model_drafts(
    authenticated_client, db_session: Session, test_organization: Organization
) -> None:
    project = _project(db_session, test_organization, "mp_payload_names")
    _run(db_session, test_organization, "exe_payload_names", project)
    db_session.commit()

    with _Statements(db_session) as sql:
        resp = authenticated_client.get("/api/v2/models/executions/all")

    assert resp.status_code == 200, resp.text
    sql.assert_never_selected("model_projects", _PROJECT_PAYLOADS)


# CONTRACT-TEST: the reaper's sweep reads no payloads.
# It scans up to 500 rows to decide whether a run has gone quiet, and reads four
# fields to do it. Loading the entity made that sweep ~55 MB, on a schedule.
def test_the_reaper_sweep_does_not_read_the_payloads(
    db_session: Session, test_organization: Organization
) -> None:
    from datetime import timedelta

    from app.tasks.execution_reaper import reap_stale_executions

    project = _project(db_session, test_organization, "mp_payload_reaper")
    _run(
        db_session,
        test_organization,
        "exe_payload_reaper",
        project,
        status="pending",
        result_data=None,
        created_at=utcnow() - timedelta(days=2),
        celery_task_id=None,
    )
    db_session.commit()

    with _Statements(db_session) as sql:
        summary = reap_stale_executions(db_session)

    assert summary["scanned"] >= 1
    sql.assert_never_selected("model_executions", _EXECUTION_PAYLOADS)


# CONTRACT-TEST: the trigger-run sweep reads no payloads either.
#
# The sweep commits once per row, and a commit expires every instance in the
# session. Whatever the next attribute touch reloads has to stay inside the
# columns the sweep actually uses — a status and two timestamps — or the
# deferred options on the candidate query buy nothing and the sweep pulls a
# whole solver result per row all over again.
def test_the_trigger_run_sweep_does_not_read_the_payloads(
    db_session: Session, test_organization: Organization
) -> None:
    from datetime import timedelta
    from unittest.mock import patch

    from app.models.trigger import SolveTrigger, TriggerRun
    from app.shared.utils.id_generator import generate_id
    from app.tasks import execution_reaper
    from app.tasks.execution_reaper import reap_stale_trigger_runs

    now = utcnow()
    trigger = SolveTrigger(
        id=generate_id("trg_"),
        organization_id=test_organization.id,
        name="Payload sweep trigger",
        trigger_secret="a" * 64,
        webhook_url="https://example.com/hook",
        is_enabled=True,
        total_runs=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(trigger)
    db_session.flush()
    for i in range(3):
        db_session.add(
            TriggerRun(
                id=generate_id("trun_"),
                trigger_id=trigger.id,
                organization_id=test_organization.id,
                status="pending",
                source="cron",
                webhook_attempts=0,
                result_data={"objective_value": 1.0},
                override_data={"x": 1},
                created_at=now - timedelta(days=2) - timedelta(seconds=i),
            )
        )
    db_session.commit()

    # A session configured like production, not like the harness. `db_session`
    # is built with expire_on_commit=False; `SessionLocal` is not. The sweep
    # commits once per row, and only under expire_on_commit=True does that
    # commit expire the remaining instances and force the reloads this test is
    # here to measure. Measured on the harness session, the reloads never happen
    # and the test passes on code that would read a whole solver result per row.
    from sqlalchemy.orm import Session as SASession

    production_like = SASession(bind=db_session.bind, expire_on_commit=True)
    try:
        with (
            patch.object(execution_reaper, "_runs_a_worker_still_holds", return_value=frozenset()),
            _Statements(production_like) as sql,
        ):
            summary = reap_stale_trigger_runs(production_like)
    finally:
        production_like.close()

    assert summary["failed"] == 3
    sql.assert_never_selected("trigger_runs", ("result_data", "override_data"))
