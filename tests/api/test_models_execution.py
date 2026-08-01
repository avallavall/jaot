"""
Tests for Model Execution API.

P1.5 fusion: ``/models/{model_id}/execute`` executes a ModelProject — a fork of a
generator-backed listing renders ``input_data`` through the TemplateEngine; a plain
project solves its draft content directly. These tests verify:
- Executing models (generator-backed and static)
- Execution history (typed + legacy-id rows)
- Async cancel guard
"""

from app.models import (
    ExecutionStatus,
    ModelExecution,
    ModelProject,
    ModelProjectListing,
)

BOUNDED_MILP_INPUT = {
    "variables": [{"name": "x", "type": "integer", "lower_bound": 0, "upper_bound": 10}],
    "objective": {"sense": "maximize", "expression": "x"},
}


def _seed_fork(db_session, organization, suffix: str) -> str:
    """A fork ModelProject of a trivial generic listing. Returns the fork id."""
    db_session.add(
        ModelProject(
            id=f"src_{suffix}",
            organization_id=organization.id,
            name=f"src_{suffix}",
            status="active",
        )
    )
    db_session.flush()
    db_session.add(
        ModelProjectListing(
            model_project_id=f"src_{suffix}",
            name=f"src_{suffix}",
            display_name="Exec Listing",
            description="For execution tests",
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
        id=f"fork_{suffix}",
        organization_id=organization.id,
        name="Exec fork",
        status="active",
        source_type="marketplace",
        source_ref=f"src_{suffix}",
    )
    db_session.add(fork)
    db_session.commit()
    return fork.id


class TestExecuteModel:
    """Tests for POST /api/v2/models/{model_id}/execute"""

    def test_execute_model_not_found(self, authenticated_client):
        """Test executing non-existent model returns 404."""
        response = authenticated_client.post(
            "/api/v2/models/nonexistent_model/execute", json={"input_data": {}}
        )
        assert response.status_code == 404

    def test_execute_model_auto_solver_resolves(
        self, authenticated_client, db_session, test_organization
    ):
        """Regression: ``?solver_name=auto`` must resolve to a concrete solver.

        Before the fix, execute_model passed ``"auto"`` straight to the solver
        registry, which raised ``SolverNotFoundError('Solver 'auto' is not
        registered.')``. This test uses the REAL solver registry (no mock) so it
        actually exercises auto-routing end to end — exactly the gap that let
        the bug ship.
        """
        model_id = _seed_fork(db_session, test_organization, "auto")

        # MILP (integer var) → auto routes to SCIP, which is always registered.
        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute?solver_name=auto",
            json={"input_data": BOUNDED_MILP_INPUT},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        # The bug surfaced as status FAILED + "Solver 'auto' is not registered".
        assert data["status"] == "completed", data
        assert data["solver_status"] in ("optimal", "feasible"), data

        # "auto" must have been resolved to a concrete solver before persisting.
        execution = db_session.query(ModelExecution).filter(ModelExecution.id == data["id"]).first()
        assert execution is not None
        assert execution.solver_name in ("scip", "highs", "hexaly")
        assert execution.solver_name != "auto"
        assert execution.auto_route_reason is not None

    def test_execute_static_project_solves_draft(
        self, authenticated_client, db_session, test_organization
    ):
        """A plain (non-generator) project executes its draft content directly."""
        project = ModelProject(
            id="test_static_exec",
            organization_id=test_organization.id,
            name="Static model",
            status="active",
            draft_model_json=BOUNDED_MILP_INPUT,
        )
        db_session.add(project)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_static_exec/execute", json={"input_data": {}}
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "completed", data
        assert data["objective_value"] == 10.0, data
        assert data["model_project_id"] == "test_static_exec"

    def test_execute_static_project_rejects_input_data(
        self, authenticated_client, db_session, test_organization
    ):
        """Non-empty input_data on a non-generator model → 422 (no schema to fill)."""
        project = ModelProject(
            id="test_static_input",
            organization_id=test_organization.id,
            name="Static model",
            status="active",
            draft_model_json=BOUNDED_MILP_INPUT,
        )
        db_session.add(project)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_static_input/execute", json={"input_data": {"budget": 5}}
        )
        assert response.status_code == 422
        assert "not generator-backed" in response.json()["detail"]

    def test_execute_empty_project_rejected(
        self, authenticated_client, db_session, test_organization
    ):
        """A project with no draft content and no generator → 422."""
        project = ModelProject(
            id="test_empty_exec",
            organization_id=test_organization.id,
            name="Empty model",
            status="active",
        )
        db_session.add(project)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_empty_exec/execute", json={"input_data": {}}
        )
        assert response.status_code == 422
        assert "no content" in response.json()["detail"]

    def test_execute_archived_model(self, authenticated_client, db_session, test_organization):
        """Test cannot execute an archived model — endpoint returns 404."""
        project = ModelProject(
            id="test_archived_exec_model",
            organization_id=test_organization.id,
            name="Archived model",
            status="archived",
            draft_model_json=BOUNDED_MILP_INPUT,
        )
        db_session.add(project)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_archived_exec_model/execute", json={"input_data": {}}
        )
        # Endpoint contract: archived model returns 404 (filter excludes it)
        assert response.status_code == 404


class TestExecutionHistory:
    """Tests for GET /api/v2/models/{model_id}/executions"""

    def _seed_project(self, db_session, organization, pid: str) -> None:
        db_session.add(
            ModelProject(
                id=pid,
                organization_id=organization.id,
                name="History model",
                status="active",
            )
        )
        db_session.flush()

    def test_list_executions_empty(self, authenticated_client, db_session, test_organization):
        """Test listing executions when none exist."""
        self._seed_project(db_session, test_organization, "test_empty_history_model")
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/test_empty_history_model/executions")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert data["total"] == 0

    def test_list_executions_with_history(
        self, authenticated_client, db_session, test_organization
    ):
        """Test listing executions with history."""
        self._seed_project(db_session, test_organization, "test_history_model")

        # Create some executions
        for i in range(3):
            execution = ModelExecution(
                id=f"test_execution_{i}",
                model_project_id="test_history_model",
                organization_id=test_organization.id,
                input_data={"iteration": i},
                status=ExecutionStatus.COMPLETED.value,
            )
            db_session.add(execution)
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/test_history_model/executions")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 3
        assert len(data["items"]) == 3

    def test_list_executions_includes_legacy_rows(
        self, authenticated_client, db_session, test_organization
    ):
        """Historic executions carry only organization_model_id — the P1.5
        backfill preserved that id as the project id, so history includes them.

        D-26 dropped ``organization_models`` but kept this column for exactly
        this reason: the shared id is what still ties an old run to its model.
        """
        self._seed_project(db_session, test_organization, "test_legacy_history")
        db_session.add(
            ModelExecution(
                id="test_legacy_exec",
                organization_model_id="test_legacy_history",
                organization_id=test_organization.id,
                input_data={},
                status=ExecutionStatus.COMPLETED.value,
            )
        )
        db_session.add(
            ModelExecution(
                id="test_typed_exec",
                model_project_id="test_legacy_history",
                organization_id=test_organization.id,
                input_data={},
                status=ExecutionStatus.COMPLETED.value,
            )
        )
        db_session.commit()

        response = authenticated_client.get("/api/v2/models/test_legacy_history/executions")
        assert response.status_code == 200
        data = response.json()
        ids = {e["id"] for e in data["items"]}
        assert ids == {"test_legacy_exec", "test_typed_exec"}

    def test_list_executions_pagination(self, authenticated_client, db_session, test_organization):
        """Test execution history pagination."""
        self._seed_project(db_session, test_organization, "test_paginated_history")

        # Create many executions
        for i in range(10):
            execution = ModelExecution(
                id=f"test_paginated_exec_{i}",
                model_project_id="test_paginated_history",
                organization_id=test_organization.id,
                input_data={},
                status=ExecutionStatus.COMPLETED.value,
            )
            db_session.add(execution)
        db_session.commit()

        response = authenticated_client.get(
            "/api/v2/models/test_paginated_history/executions?page=1&page_size=3"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 3
        assert len(data["items"]) == 3
        assert data["total"] == 10

    def test_list_executions_filter_by_status(
        self, authenticated_client, db_session, test_organization
    ):
        """Test filtering executions by status."""
        self._seed_project(db_session, test_organization, "test_status_filter_model")

        # Create executions with different statuses
        completed = ModelExecution(
            id="test_completed_exec",
            model_project_id="test_status_filter_model",
            organization_id=test_organization.id,
            input_data={},
            status=ExecutionStatus.COMPLETED.value,
        )
        failed = ModelExecution(
            id="test_failed_exec",
            model_project_id="test_status_filter_model",
            organization_id=test_organization.id,
            input_data={},
            status=ExecutionStatus.FAILED.value,
        )
        db_session.add_all([completed, failed])
        db_session.commit()

        response = authenticated_client.get(
            "/api/v2/models/test_status_filter_model/executions?status=completed"
        )
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["status"] == "completed"


class TestAsyncExecution:
    """Tests for async execution endpoints."""

    def test_cancel_execution_not_found(self, authenticated_client):
        """Test cancelling non-existent execution."""
        response = authenticated_client.post("/api/v2/models/async/nonexistent_task/cancel")
        assert response.status_code == 404
