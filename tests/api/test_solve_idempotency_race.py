"""Two /solve requests with one Idempotency-Key run one solve.

Both requests can miss the replay lookup. Both then insert the row the key
maps to, and the second insert fails on the primary key. That request rolled
back and enqueued anyway, so the model was solved twice and the second
result was written to no row. It now attaches to the solve that won.
"""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from app.api.v2 import solve_pipeline
from app.domains.solver import execution_writer
from app.models import ModelExecution

_PROBLEM = {
    "name": "idem_race",
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
    "constraints": [{"name": "c1", "expression": "x >= 1"}],
    "objective": {"expression": "x", "sense": "minimize"},
    "options": {"time_limit_seconds": 10},
}


# CONTRACT-TEST: a raced Idempotency-Key never enqueues a second solve.
def test_the_request_that_loses_the_race_attaches_to_the_winner(
    authenticated_client, test_organization, db_session, db_engine
) -> None:
    real_enqueue = solve_pipeline.enqueue_async_solve
    Session = sessionmaker(bind=db_engine)

    def raced(**kwargs):
        # The other request commits its row just after this one's lookup.
        other = Session()
        try:
            execution_writer.insert_pending(
                other,
                execution_id=kwargs["execution_id_override"],
                organization_id=test_organization.id,
                celery_task_id="task-of-the-winner",
                input_data=_PROBLEM,
                solver_name="scip",
            )
            other.commit()
        finally:
            other.close()
        return real_enqueue(**kwargs)

    with (
        patch("app.api.v2.solve.enqueue_async_solve", side_effect=raced),
        patch("app.domains.solver.tasks.solve_tasks.solve_async.apply_async") as apply_async,
        patch("app.api.v2.solve.wait_for_task", return_value=None),
    ):
        response = authenticated_client.post(
            "/api/v2/solve", json=_PROBLEM, headers={"Idempotency-Key": "race-key-1"}
        )

    assert apply_async.call_count == 0, "the losing request queued a second solve"
    assert response.status_code == 202, response.text[:300]
    assert response.json()["task_id"] == "task-of-the-winner"
    rows = (
        db_session.query(ModelExecution)
        .filter(ModelExecution.organization_id == test_organization.id)
        .count()
    )
    assert rows == 1
