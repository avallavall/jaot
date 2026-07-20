"""ADR-007 S6 — execute_model rides the async pipeline in BOTH modes.

The sync mode is a thin wrapper: enqueue ``solve_model_async``, wait up to the
shared budget, shape the historic ``ModelExecutionResponse``; past the budget it
degrades to 202 + the async envelope. These tests pin that conversion — plus the
worker-side fix this conversion required: a solver-internal ERROR (non-raising)
must mark the row FAILED, which the old inline sync path guaranteed and the
worker previously got wrong. P1.5 fusion: the executed model is a ModelProject
(here a fork of a generator-backed listing — the fused "activated model").
"""

from app.models import (
    ExecutionStatus,
    ModelExecution,
    ModelProject,
    ModelProjectListing,
)

BOUNDED_LP_INPUT = {
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 4}],
    "objective": {"sense": "maximize", "expression": "x"},
}

# Passes validation; the solver swallows the parse failure into a non-raising
# ERROR result inside the worker.
SOLVER_ERROR_INPUT = {
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
    "objective": {"sense": "maximize", "expression": "x/0"},
}


def _seed_model(db_session, organization, suffix: str) -> str:
    """A fork ModelProject of a trivial generic listing for the org. Returns its id."""
    db_session.add(
        ModelProject(
            id=f"s6src_{suffix}",
            organization_id=organization.id,
            name=f"s6src_{suffix}",
            status="active",
        )
    )
    db_session.flush()
    db_session.add(
        ModelProjectListing(
            model_project_id=f"s6src_{suffix}",
            name=f"s6src_{suffix}",
            display_name="S6 Parity Listing",
            description="ADR-007 S6 wrapper parity",
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            status="published",
            is_public=True,
            author_organization_id=organization.id,
        )
    )
    fork = ModelProject(
        id=f"s6fork_{suffix}",
        organization_id=organization.id,
        name="S6 fork",
        status="active",
        source_type="marketplace",
        source_ref=f"s6src_{suffix}",
    )
    db_session.add(fork)
    db_session.commit()
    return fork.id


class TestS6ExecuteModelParity:
    def test_sync_mode_returns_historic_contract(
        self, authenticated_client, db_session, test_organization
    ):
        """# CONTRACT-TEST: ADR-007 S6 — wrapped sync execute returns the exact
        historic ModelExecutionResponse shape (completed, objective)."""
        model_id = _seed_model(db_session, test_organization, "sync")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute",
            json={"input_data": BOUNDED_LP_INPUT},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        for field in ("id", "status", "input_data", "created_at"):
            assert field in data, f"missing {field}: {data}"
        assert data["status"] == "completed", data
        assert data["objective_value"] == 4.0, data
        assert data["solver_status"] in ("optimal", "feasible"), data
        assert data["model_project_id"] == model_id

        # The row went through the pipeline: a celery task id was stamped.
        row = db_session.query(ModelExecution).filter(ModelExecution.id == data["id"]).first()
        assert row is not None
        assert row.celery_task_id

    def test_execute_recovers_flat_index_structure(
        self, authenticated_client, db_session, test_organization
    ):
        """# CONTRACT-TEST: A1 index recovery covers EVERY solve entry point —
        an execution launched via /models/{id}/execute must carry family/index_tuple
        on its solution variables (the worker annotates the problem it builds;
        /solve and /solve/async annotate at enqueue)."""
        model_id = _seed_model(db_session, test_organization, "a1idx")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute",
            json={
                "input_data": {
                    "variables": [
                        {
                            "name": "pick_1",
                            "type": "continuous",
                            "lower_bound": 0,
                            "upper_bound": 1,
                        },
                        {
                            "name": "pick_2",
                            "type": "continuous",
                            "lower_bound": 0,
                            "upper_bound": 1,
                        },
                    ],
                    "objective": {"sense": "maximize", "expression": "pick_1 + pick_2"},
                }
            },
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "completed", data
        variables = (data.get("result_data") or {}).get("variables") or []
        by_name = {v["name"]: v for v in variables}
        assert by_name, data.get("result_data")
        assert by_name["pick_1"]["family"] == "pick"
        assert by_name["pick_1"]["index_tuple"] == ["1"]
        assert by_name["pick_2"]["index_tuple"] == ["2"]

    def test_sync_mode_degrades_to_202_past_budget(
        self, authenticated_client, db_session, test_organization, monkeypatch
    ):
        """# CONTRACT-TEST: ADR-007 S6 — wait budget exhausted → 202 + the async
        envelope (poll_url/ws_url), never an indefinite block."""
        import app.api.v2.routes.models.execution as exec_mod

        monkeypatch.setattr(exec_mod, "_wait_for_task", lambda task: None)
        model_id = _seed_model(db_session, test_organization, "degrade")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute",
            json={"input_data": BOUNDED_LP_INPUT},
        )

        assert response.status_code == 202, response.text
        envelope = response.json()
        assert envelope["task_id"], envelope
        assert envelope["execution_id"].startswith("exe_"), envelope
        assert envelope["poll_url"].startswith("/api/v2/models/async/"), envelope
        assert envelope["ws_url"].startswith("/api/v2/ws/executions/"), envelope
        assert envelope["status"] == "pending", envelope

    def test_async_mode_envelope_unchanged(
        self, authenticated_client, db_session, test_organization
    ):
        """# CONTRACT-TEST: async_mode=true keeps the pre-S6 envelope contract."""
        model_id = _seed_model(db_session, test_organization, "env")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute",
            json={"input_data": BOUNDED_LP_INPUT, "async_mode": True},
        )

        assert response.status_code == 200, response.text
        envelope = response.json()
        for field in (
            "id",
            "execution_id",
            "model_project_id",
            "task_id",
            "ws_url",
            "poll_url",
        ):
            assert field in envelope, f"missing {field}: {envelope}"
        assert envelope["status"] == "pending"
        assert envelope["model_project_id"] == model_id

    def test_worker_internal_solver_error_fails_row(
        self, authenticated_client, db_session, test_organization
    ):
        """# CONTRACT-TEST: ADR-007 S6 — a non-raising solver ERROR in the worker
        marks the row FAILED (a solve that delivered no result must never look
        completed).

        Async mode on purpose: it pins the WORKER branch directly (the sync
        wrapper shape is covered by test_models_execution.py)."""
        model_id = _seed_model(db_session, test_organization, "werr")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute",
            json={"input_data": SOLVER_ERROR_INPUT, "async_mode": True},
        )

        assert response.status_code == 200, response.text
        execution_id = response.json()["execution_id"]

        # The (eager) worker wrote the row on its OWN session — expire the
        # shared test session's identity map so the query reads DB truth, not
        # the handler's stale in-session 'pending' object.
        db_session.expire_all()

        row = db_session.query(ModelExecution).filter(ModelExecution.id == execution_id).first()
        assert row is not None
        assert row.status == ExecutionStatus.FAILED.value, row.status
        assert row.error_message
