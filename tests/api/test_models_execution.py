"""
Tests for Model Execution API.

These tests verify the execution functionality:
- Executing models (sync and async)
- Execution history
- Async status polling
"""

from app.models import (
    ExecutionStatus,
    ModelCatalog,
    ModelCategory,
    ModelExecution,
    OrganizationModel,
)


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
        registered.')`` and the sync path STILL charged the user. This test
        uses the REAL solver registry (no mock) so it actually exercises
        auto-routing end to end — exactly the gap that let the bug ship.
        """
        catalog = ModelCatalog(
            id="test_auto_catalog",
            name="auto_catalog",
            display_name="Auto Catalog",
            description="For auto-routing regression",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
        )
        db_session.add(catalog)
        org_model = OrganizationModel(
            id="test_auto_org_model",
            organization_id=test_organization.id,
            catalog_id="test_auto_catalog",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()

        # MILP (integer var) → auto routes to SCIP, which is always registered.
        response = authenticated_client.post(
            "/api/v2/models/test_auto_org_model/execute?solver_name=auto",
            json={
                "input_data": {
                    "variables": [
                        {"name": "x", "type": "integer", "lower_bound": 0, "upper_bound": 10}
                    ],
                    "objective": {"sense": "maximize", "expression": "x"},
                }
            },
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

    def _seed_exec_model(self, db_session, test_organization, suffix: str):
        """Activate a trivial generic catalog model for the org. Returns its id."""
        catalog = ModelCatalog(
            id=f"cat_{suffix}",
            name=f"cat_{suffix}",
            display_name="Ledger Catalog",
            description="For execution CONTRACT-TESTs",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
        )
        db_session.add(catalog)
        org_model = OrganizationModel(
            id=f"om_{suffix}",
            organization_id=test_organization.id,
            catalog_id=f"cat_{suffix}",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()
        return org_model.id

    def test_execute_inactive_model(self, authenticated_client, db_session, test_organization):
        """Test cannot execute inactive model — endpoint returns 404."""
        org_model = OrganizationModel(
            id="test_inactive_exec_model",
            organization_id=test_organization.id,
            is_active=False,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_inactive_exec_model/execute", json={"input_data": {}}
        )
        # Endpoint contract: inactive model returns 404 (filter excludes inactive)
        assert response.status_code == 404


class TestExecutionHistory:
    """Tests for GET /api/v2/models/{model_id}/executions"""

    def test_list_executions_empty(self, authenticated_client, db_session, test_organization):
        """Test listing executions when none exist."""
        org_model = OrganizationModel(
            id="test_empty_history_model",
            organization_id=test_organization.id,
            is_active=True,
        )
        db_session.add(org_model)
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
        org_model = OrganizationModel(
            id="test_history_model",
            organization_id=test_organization.id,
            is_active=True,
        )
        db_session.add(org_model)
        db_session.flush()

        # Create some executions
        for i in range(3):
            execution = ModelExecution(
                id=f"test_execution_{i}",
                organization_model_id="test_history_model",
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

    def test_list_executions_pagination(self, authenticated_client, db_session, test_organization):
        """Test execution history pagination."""
        org_model = OrganizationModel(
            id="test_paginated_history",
            organization_id=test_organization.id,
            is_active=True,
        )
        db_session.add(org_model)
        db_session.flush()

        # Create many executions
        for i in range(10):
            execution = ModelExecution(
                id=f"test_paginated_exec_{i}",
                organization_model_id="test_paginated_history",
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
        org_model = OrganizationModel(
            id="test_status_filter_model",
            organization_id=test_organization.id,
            is_active=True,
        )
        db_session.add(org_model)
        db_session.flush()

        # Create executions with different statuses
        completed = ModelExecution(
            id="test_completed_exec",
            organization_model_id="test_status_filter_model",
            organization_id=test_organization.id,
            input_data={},
            status=ExecutionStatus.COMPLETED.value,
        )
        failed = ModelExecution(
            id="test_failed_exec",
            organization_model_id="test_status_filter_model",
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
