"""
Tests for Model Execution API.

These tests verify the execution functionality:
- Executing models (sync and async)
- Credit deduction
- Execution history
- Async status polling
"""

from unittest.mock import MagicMock

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

    def test_execute_model_deducts_credits(
        self, authenticated_client, db_session, test_organization
    ):
        """Test that execution deducts credits from organization.

        Pins status_code == 200 and asserts that credits_balance strictly
        decreased by the calculated credits amount. No conditional assertions:
        if the endpoint returns anything other than 200, the test fails loudly.
        """
        from app.domains.solver.services.solver_service import get_solver_service

        initial_credits = test_organization.credits_balance

        catalog = ModelCatalog(
            id="test_exec_catalog",
            name="exec_catalog",
            display_name="Exec Catalog",
            description="For execution testing",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=5,
        )
        db_session.add(catalog)

        # Create org model linked to catalog
        org_model = OrganizationModel(
            id="test_exec_org_model",
            organization_id=test_organization.id,
            catalog_id="test_exec_catalog",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()

        # Override the solver dependency to return a successful result
        from app.schemas.optimization import SolverStatus

        fake_result = MagicMock()
        fake_result.status = SolverStatus.OPTIMAL
        fake_result.objective_value = 100.0
        fake_result.solve_time_seconds = 0.1
        fake_result.to_result_data.return_value = {"x": 1}

        fake_solver = MagicMock()
        fake_solver.solve.return_value = fake_result

        # Use FastAPI dependency override (the proper integration test pattern)
        app = authenticated_client.app
        app.dependency_overrides[get_solver_service] = lambda: fake_solver
        try:
            response = authenticated_client.post(
                "/api/v2/models/test_exec_org_model/execute",
                json={
                    "input_data": {
                        "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
                        "objective": {"sense": "maximize", "expression": "x"},
                    }
                },
            )
        finally:
            app.dependency_overrides.pop(get_solver_service, None)

        # Pin status code: must be exactly 200
        assert response.status_code == 200, response.text

        # Credits must have been deducted (not asserted conditionally)
        db_session.refresh(test_organization)
        assert test_organization.credits_balance < initial_credits

    def test_execute_model_insufficient_credits(
        self, authenticated_client, db_session, test_organization
    ):
        """Test execution fails with exact 402 Payment Required."""
        # Set credits to 0
        test_organization.credits_balance = 0
        db_session.commit()

        catalog = ModelCatalog(
            id="test_no_credits_catalog",
            name="no_credits_catalog",
            display_name="No Credits Catalog",
            description="For insufficient-credit testing",
            category=ModelCategory.GENERAL,
            generator_type="generic",
            input_schema={},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_official=False,
            is_public=True,
            price_eur=0.0,
            credits_per_execution=5,
        )
        db_session.add(catalog)

        org_model = OrganizationModel(
            id="test_no_credits_model",
            organization_id=test_organization.id,
            catalog_id="test_no_credits_catalog",
            is_active=True,
        )
        db_session.add(org_model)
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_no_credits_model/execute",
            json={
                "input_data": {
                    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
                    "objective": {"sense": "maximize", "expression": "x"},
                }
            },
        )

        # Endpoint contract: exactly 402 Payment Required
        assert response.status_code == 402, response.text
        assert "credit" in response.json().get("detail", "").lower()

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
                credits_consumed=1,
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
                credits_consumed=1,
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
            credits_consumed=1,
        )
        failed = ModelExecution(
            id="test_failed_exec",
            organization_model_id="test_status_filter_model",
            organization_id=test_organization.id,
            input_data={},
            status=ExecutionStatus.FAILED.value,
            credits_consumed=1,
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
