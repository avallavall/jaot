"""A cancel and a finishing model execution agree on what happened.

``solve_model_async`` read the row without a lock before its final write. A
cancel that committed between that read and the worker's commit told the user
"cancelled", and then the worker wrote "completed" over it. The worker now
locks the row, as ``solve_async`` and the cancel endpoints do.

The cancel endpoints also answered ``cancelled: true`` when the row had
already finished, so the page showed "cancelled" over a finished run.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import sessionmaker

from app.domains.solver import execution_writer
from app.domains.solver.tasks.solve_tasks import solve_model_async
from app.models import ExecutionStatus, ModelExecution
from tests.contracts.test_s6_execute_model_parity import _seed_model

_PROBLEM = {
    "name": "cancel_race",
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 4}],
    "objective": {"sense": "maximize", "expression": "x"},
    "options": {"time_limit_seconds": 10},
}


def _pending_execution(db, org, model_id: str, task_id: str) -> str:
    execution = execution_writer.insert_pending(
        db,
        execution_id=f"exe_{task_id}",
        organization_id=org.id,
        celery_task_id=task_id,
        input_data={},
        solver_name="highs",
    )
    execution.model_project_id = model_id
    db.commit()
    return execution.id


def test_a_cancel_during_the_final_write_is_not_overwritten(
    db_session, db_engine, test_organization
) -> None:
    model_id = _seed_model(db_session, test_organization, "cancelrace")
    execution_id = _pending_execution(db_session, test_organization, model_id, "t-cancel-race")
    # Production session settings: the harness keeps objects loaded across
    # commits, which hides the unlocked re-read this test is about.
    production = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=True)

    cancel_said: list[bool] = []

    def cancel_from_the_endpoint() -> None:
        session = production()
        try:
            row = session.get(ModelExecution, execution_id)
            row = execution_writer.refresh_locked(session, row)
            cancel_said.append(execution_writer.apply_cancelled(row))
            session.commit()
        finally:
            session.close()

    canceller = threading.Thread(target=cancel_from_the_endpoint)
    events = MagicMock()

    def listing_executed(*args, **kwargs) -> None:
        # Runs between the worker's terminal write and its commit.
        canceller.start()
        canceller.join(timeout=1.5)

    events.listing_executed.side_effect = listing_executed

    with (
        patch("app.domains.solver.tasks.solve_tasks.SessionLocal", production),
        patch("app.domains.solver.tasks.solve_tasks.ports.solve_events", return_value=events),
    ):
        solve_model_async.apply(
            kwargs={
                "execution_id": execution_id,
                "model_id": model_id,
                "template": None,
                "input_data": {},
                "organization_id": test_organization.id,
                "solver_name": "highs",
                "problem_data": _PROBLEM,
            },
            task_id="t-cancel-race",
        )
    canceller.join(timeout=10)

    db_session.expire_all()
    final = db_session.get(ModelExecution, execution_id).status
    assert cancel_said, "the cancel never ran"
    if cancel_said[0]:
        assert final == ExecutionStatus.CANCELLED.value, "the user was told cancelled"
    else:
        assert final == ExecutionStatus.COMPLETED.value


def test_cancelling_a_finished_run_says_it_was_not_cancelled(
    authenticated_client, db_session, test_organization
) -> None:
    model_id = _seed_model(db_session, test_organization, "cancelled_done")
    execution_id = _pending_execution(db_session, test_organization, model_id, "t-done")
    row = db_session.get(ModelExecution, execution_id)
    row.status = ExecutionStatus.COMPLETED.value
    db_session.commit()

    # Celery still says PENDING: the reaper settled the row, or the result
    # expired. Only the row knows the run is over.
    with (
        patch("celery.result.AsyncResult") as async_result,
        patch("app.shared.core.celery_app.celery_app.control.revoke") as revoke,
    ):
        async_result.return_value.state = "PENDING"
        for url in ("/api/v2/solve/async/t-done/cancel", "/api/v2/models/async/t-done/cancel"):
            response = authenticated_client.post(url)
            assert response.status_code == 200, (url, response.text[:200])
            assert response.json()["cancelled"] is False, url

    assert revoke.call_count == 0
    db_session.expire_all()
    assert db_session.get(ModelExecution, execution_id).status == ExecutionStatus.COMPLETED.value
