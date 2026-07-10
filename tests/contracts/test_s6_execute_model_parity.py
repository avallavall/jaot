"""ADR-007 S6 — execute_model (marketplace) rides the async pipeline in BOTH modes.

The sync mode is a thin wrapper: enqueue ``solve_model_async``, wait up to the
shared budget, shape the historic ``ModelExecutionResponse``; past the budget it
degrades to 202 + the async envelope. These tests pin that conversion — plus the
worker-side fix this conversion required: a solver-internal ERROR (non-raising)
must mark the row FAILED and net the ledger to zero, which the old inline sync
path guaranteed and the worker previously got wrong (completed + charged).
"""

from app.models import (
    CreditTransaction,
    ExecutionStatus,
    ModelCatalog,
    ModelCategory,
    ModelExecution,
    OrganizationModel,
    TransactionType,
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
    """Activate a trivial generic catalog model for the org. Returns its id."""
    catalog = ModelCatalog(
        id=f"s6cat_{suffix}",
        name=f"s6cat_{suffix}",
        display_name="S6 Parity Catalog",
        description="ADR-007 S6 wrapper parity",
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
        id=f"s6om_{suffix}",
        organization_id=organization.id,
        catalog_id=catalog.id,
        is_active=True,
    )
    db_session.add(org_model)
    db_session.commit()
    return org_model.id


class TestS6ExecuteModelParity:
    def test_sync_mode_returns_historic_contract(
        self, authenticated_client, db_session, test_organization
    ):
        """# CONTRACT-TEST: ADR-007 S6 — wrapped sync execute returns the exact
        historic ModelExecutionResponse shape (completed, objective, credits)."""
        model_id = _seed_model(db_session, test_organization, "sync")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/execute",
            json={"input_data": BOUNDED_LP_INPUT},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        for field in ("id", "status", "input_data", "credits_consumed", "created_at"):
            assert field in data, f"missing {field}: {data}"
        assert data["status"] == "completed", data
        assert data["objective_value"] == 4.0, data
        assert data["credits_consumed"] >= 1, data
        assert data["solver_status"] in ("optimal", "feasible"), data
        assert data["organization_model_id"] == model_id

        # The row went through the pipeline: a celery task id was stamped.
        row = db_session.query(ModelExecution).filter(ModelExecution.id == data["id"]).first()
        assert row is not None
        assert row.celery_task_id

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
            "organization_model_id",
            "task_id",
            "ws_url",
            "poll_url",
        ):
            assert field in envelope, f"missing {field}: {envelope}"
        assert envelope["status"] == "pending"
        assert envelope["organization_model_id"] == model_id

    def test_worker_internal_solver_error_fails_row_and_nets_zero(
        self, authenticated_client, db_session, test_organization
    ):
        """# CONTRACT-TEST: ADR-007 S6 — a non-raising solver ERROR in the worker
        marks the row FAILED and the ledger nets to zero (pre-pay + refund pair).

        Async mode on purpose: it pins the WORKER branch directly (the sync
        wrapper shape is covered by test_models_execution.py)."""
        model_id = _seed_model(db_session, test_organization, "werr")
        initial_credits = test_organization.credits_balance

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
        assert (row.credits_consumed or 0) == 0

        db_session.refresh(test_organization)
        assert test_organization.credits_balance == initial_credits

        txns = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == test_organization.id,
                CreditTransaction.reference_type == "execution",
                CreditTransaction.reference_id == execution_id,
            )
            .all()
        )
        by_type = {t.transaction_type: t for t in txns}
        assert TransactionType.EXECUTION.value in by_type, txns
        assert TransactionType.REFUND.value in by_type, txns
        assert by_type[TransactionType.EXECUTION.value].credits_amount == -(
            by_type[TransactionType.REFUND.value].credits_amount
        )
