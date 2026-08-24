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
