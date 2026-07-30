"""The model-execution poll contract (D-17).

``GET /api/v2/models/async/{task_id}`` is the twin of
``GET /api/v2/solve/async/{task_id}``. The solve side was fixed in 2026-07 after
a live incident: while Celery state is PROGRESS the task's own meta carries
``status: "completed"`` on its final "Model found!" tick, and spreading that meta
AFTER the endpoint's own keys let it overwrite ``"running"`` — clients then read
a completed payload with no result and reported a false failure.

The models twin kept the wrong order. Typing the endpoint surfaced it.
"""

from app.models import ExecutionStatus, ModelExecution

_FINAL_PROGRESS_META = {
    "progress": 1.0,
    "status": "completed",  # the tick that used to win
    "message": "Model found!",
    "iteration": None,
    "objective_value": None,
    "gap": None,
}


def _running_execution(db, org, user, *, exe_id, task_id):
    db.add(
        ModelExecution(
            id=exe_id,
            organization_id=org.id,
            executed_by_user_id=user.id,
            celery_task_id=task_id,
            input_data={},
            status=ExecutionStatus.RUNNING.value,
            is_async=True,
        )
    )
    db.commit()


def _stub_async_result(monkeypatch, *, state: str, info=None, result=None):
    """Replace celery's AsyncResult so the handler sees the state we want."""
    import celery.result as _celery_result_mod

    class _FakeCeleryAsyncResult:
        def __init__(self, task_id: str, **kwargs: object) -> None:  # noqa: ARG002
            self._task_id = task_id

        @property
        def state(self) -> str:
            return state

        @property
        def info(self) -> dict:
            return info or {}

        @property
        def result(self):  # noqa: ANN201
            return result

    monkeypatch.setattr(_celery_result_mod, "AsyncResult", _FakeCeleryAsyncResult)


class TestModelsAsyncStatusProgress:
    def test_progress_meta_status_cannot_fake_completion(
        self, authenticated_client, db_session, test_organization, test_user, monkeypatch
    ):
        """# CONTRACT-TEST: PROGRESS presents as running, whatever the meta says."""
        _running_execution(
            db_session, test_organization, test_user, exe_id="exe_prog_1", task_id="task_prog_1"
        )
        _stub_async_result(monkeypatch, state="PROGRESS", info=_FINAL_PROGRESS_META)

        res = authenticated_client.get("/api/v2/models/async/task_prog_1")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "running", (
            f"PROGRESS state must present as running, got {body['status']!r}: {body}"
        )
        assert body["task_id"] == "task_prog_1"
        assert body["execution_id"] == "exe_prog_1"
        # The progress meta still flows through for live UIs.
        assert body["message"] == "Model found!"
        assert body["progress"] == 1.0

    def test_pending_state_reports_pending(
        self, authenticated_client, db_session, test_organization, test_user, monkeypatch
    ):
        _running_execution(
            db_session, test_organization, test_user, exe_id="exe_prog_2", task_id="task_prog_2"
        )
        _stub_async_result(monkeypatch, state="PENDING")

        res = authenticated_client.get("/api/v2/models/async/task_prog_2")
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "pending"

    def test_success_carries_the_result_payload(
        self, authenticated_client, db_session, test_organization, test_user, monkeypatch
    ):
        _running_execution(
            db_session, test_organization, test_user, exe_id="exe_prog_3", task_id="task_prog_3"
        )
        _stub_async_result(
            monkeypatch,
            state="SUCCESS",
            result={
                "result": {"status": "success", "objective_value": 42.0},
                "execution_time_ms": 123,
                "execution_id": "exe_prog_3",
            },
        )

        res = authenticated_client.get("/api/v2/models/async/task_prog_3")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "completed"
        assert body["result"]["objective_value"] == 42.0
        assert body["execution_time_ms"] == 123

    def test_failure_carries_the_error(
        self, authenticated_client, db_session, test_organization, test_user, monkeypatch
    ):
        _running_execution(
            db_session, test_organization, test_user, exe_id="exe_prog_4", task_id="task_prog_4"
        )
        _stub_async_result(monkeypatch, state="FAILURE", result=RuntimeError("worker died"))

        res = authenticated_client.get("/api/v2/models/async/task_prog_4")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "failed"
        assert "worker died" in body["error"]

    def test_other_org_cannot_poll(
        self, authenticated_client, db_session, test_organization_2, test_user_2, monkeypatch
    ):
        """IDOR guard: ownership is checked before AsyncResult is ever built."""
        _running_execution(
            db_session, test_organization_2, test_user_2, exe_id="exe_prog_5", task_id="task_prog_5"
        )
        _stub_async_result(monkeypatch, state="PROGRESS", info=_FINAL_PROGRESS_META)

        res = authenticated_client.get("/api/v2/models/async/task_prog_5")
        assert res.status_code == 404, res.text
