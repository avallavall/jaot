"""Tests for workspace credit deduction in trigger solves (Phase 12, Plan 01).

Covers:
- SolveTrigger model accepts workspace_id (nullable)
- create_trigger endpoint stores workspace_id from request body
- _trigger_to_response includes workspace_id in output
- trigger_solve_task uses workspace credit pool when workspace_id present
- trigger_solve_task falls back to org balance when workspace_id is None
- trigger_solve_task falls back to org balance when workspace pool is exhausted
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models.organization import Organization
from app.models.trigger import SolveTrigger, TriggerRun
from app.models.workspace import Workspace
from app.shared.utils.datetime_helpers import utcnow


@pytest.fixture
def org(db_session):
    """Create a test organization with credits."""
    org = Organization(
        id="org_ws_test",
        name="Workspace Test Org",
        credits_balance=500,
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def _fake_doc_and_version(db_session, org):
    """Create the ModelBuilderDocument and ModelVersion that triggers reference."""
    from app.models.builder_document import ModelBuilderDocument
    from app.models.model_version import ModelVersion

    doc = ModelBuilderDocument(
        id="doc_fake",
        organization_id=org.id,
        name="Test Doc",
        canvas_json={"nodes": [], "edges": []},
        model_json={
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
            "objective": {"sense": "minimize", "expression": "x"},
            "constraints": [],
        },
        is_active=True,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db_session.add(doc)

    ver = ModelVersion(
        id="ver_fake",
        document_id="doc_fake",
        organization_id=org.id,
        canvas_json={"nodes": [], "edges": []},
        model_json={
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
            "objective": {"sense": "minimize", "expression": "x"},
            "constraints": [],
        },
        change_summary="test",
        is_named=True,
        sequence=1,
        created_at=utcnow(),
    )
    db_session.add(ver)
    db_session.commit()
    return doc, ver


@pytest.fixture
def trigger_no_ws(db_session, org, _fake_doc_and_version):
    """Create a SolveTrigger without workspace_id."""
    t = SolveTrigger(
        id="trg_no_ws",
        organization_id=org.id,
        name="Trigger No WS",
        document_id="doc_fake",
        version_id="ver_fake",
        trigger_secret="fakehash",
        webhook_url="http://example.com/webhook",
        is_enabled=True,
        total_runs=0,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def test_workspace(db_session, org):
    """Create a workspace for trigger tests."""
    ws = Workspace(
        id="ws_test123",
        organization_id=org.id,
        name="Test Workspace",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    return ws


@pytest.fixture
def trigger_with_ws(db_session, org, _fake_doc_and_version, test_workspace):
    """Create a SolveTrigger with workspace_id set."""
    t = SolveTrigger(
        id="trg_with_ws",
        organization_id=org.id,
        name="Trigger With WS",
        document_id="doc_fake",
        version_id="ver_fake",
        trigger_secret="fakehash",
        webhook_url="http://example.com/webhook",
        workspace_id="ws_test123",
        is_enabled=True,
        total_runs=0,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t


@pytest.fixture
def run_pending(db_session, trigger_with_ws):
    """Create a pending TriggerRun for trigger_with_ws."""
    r = TriggerRun(
        id="run_ws_test",
        trigger_id=trigger_with_ws.id,
        organization_id=trigger_with_ws.organization_id,
        status="pending",
        credits_consumed=0,
        webhook_attempts=0,
        created_at=utcnow(),
    )
    db_session.add(r)
    db_session.commit()
    db_session.refresh(r)
    return r


class TestSolveTriggerWorkspaceId:
    """SolveTrigger model correctly handles workspace_id."""

    def test_workspace_id_defaults_to_none(self, db_session, trigger_no_ws):
        """workspace_id is None by default when not explicitly set."""
        assert trigger_no_ws.workspace_id is None

    def test_workspace_id_stored_when_set(self, db_session, trigger_with_ws):
        """workspace_id is stored when explicitly set on creation."""
        assert trigger_with_ws.workspace_id == "ws_test123"

    def test_workspace_id_column_exists(self):
        """SolveTrigger table has workspace_id column."""
        columns = SolveTrigger.__table__.columns.keys()
        assert "workspace_id" in columns


class TestTriggerResponseWorkspaceId:
    """_trigger_to_response includes workspace_id in output."""

    def test_response_includes_workspace_id_none(self, trigger_no_ws):
        from app.api.v2.triggers import _trigger_to_response

        resp = _trigger_to_response(trigger_no_ws)
        assert "workspace_id" in resp
        assert resp["workspace_id"] is None

    def test_response_includes_workspace_id_set(self, trigger_with_ws):
        from app.api.v2.triggers import _trigger_to_response

        resp = _trigger_to_response(trigger_with_ws)
        assert resp["workspace_id"] == "ws_test123"


class TestTriggerCreateWithWorkspaceId:
    """TriggerCreate schema accepts optional workspace_id."""

    def test_create_without_workspace_id(self):
        from app.schemas.trigger import TriggerCreate

        tc = TriggerCreate(
            name="test",
            document_id="doc1",
            version_id="ver1",
            webhook_url="http://example.com",
        )
        assert tc.workspace_id is None

    def test_create_with_workspace_id(self):
        from app.schemas.trigger import TriggerCreate

        tc = TriggerCreate(
            name="test",
            document_id="doc1",
            version_id="ver1",
            webhook_url="http://example.com",
            workspace_id="ws_abc",
        )
        assert tc.workspace_id == "ws_abc"

    def test_response_schema_has_workspace_id(self):
        from app.schemas.trigger import TriggerResponse

        fields = TriggerResponse.model_fields
        assert "workspace_id" in fields


@pytest.fixture
def workspace_pool(db_session, org, test_workspace):
    """Create a real WorkspaceCreditPool with allocated credits."""
    from app.models.workspace_credits import WorkspaceCreditPool
    from app.shared.utils.id_generator import generate_id

    pool = WorkspaceCreditPool(
        id=generate_id("wcp_"),
        workspace_id=test_workspace.id,
        organization_id=org.id,
        allocated_credits=100,
        used_credits=0,
        last_alert_threshold=None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db_session.add(pool)
    db_session.commit()
    db_session.refresh(pool)
    return pool


class TestTriggerSolveWorkspaceCredits:
    """trigger_solve_task deducts from a REAL workspace credit pool."""

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.domains.solver.services.solver_service.SolverService.solve")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_workspace_pool_deduction(
        self,
        mock_session_local,
        mock_solve,
        mock_webhook,
        db_session,
        org,
        trigger_with_ws,
        run_pending,
        workspace_pool,
    ):
        """When trigger has workspace_id, the workspace pool used_credits increases.

        No deduct_credits_for_solve patching: we plant a real workspace credit pool
        and verify the pool's used_credits actually increased after the task runs.
        """
        from app.models.workspace_credits import WorkspaceCreditPool

        initial_org_balance = org.credits_balance
        initial_pool_used = workspace_pool.used_credits
        initial_pool_id = workspace_pool.id

        # Mock solver result
        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "status": "optimal",
            "objective_value": 0.0,
            "credits_used": 2,
            "variables": [],
            "solution": {},
            "solve_time_seconds": 0.1,
        }
        mock_solve.return_value = mock_result
        mock_session_local.return_value = db_session

        # Patch close so the test session stays alive after the task returns
        with patch.object(db_session, "close", lambda: None):
            from app.tasks.trigger_tasks import trigger_solve_task

            result = trigger_solve_task(
                run_id=run_pending.id,
                trigger_id=trigger_with_ws.id,
                override_data=None,
            )

        assert result["status"] == "completed"

        # The real pool used_credits must have grown by the deducted amount
        fresh_pool = (
            db_session.query(WorkspaceCreditPool)
            .filter(WorkspaceCreditPool.id == initial_pool_id)
            .first()
        )
        assert fresh_pool is not None
        assert fresh_pool.used_credits == initial_pool_used + 2

        # Org balance must be untouched (the pool absorbed the cost)
        db_session.refresh(org)
        assert org.credits_balance == initial_org_balance


# TestTriggerSolveOrgFallback — org-level deduction with REAL credit balance


class TestTriggerSolveOrgFallback:
    """trigger_solve_task falls back to real org balance deduction."""

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.domains.solver.services.solver_service.SolverService.solve")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_org_fallback_no_workspace(
        self, mock_session_local, mock_solve, mock_webhook, db_session, org, trigger_no_ws
    ):
        """When trigger has no workspace_id, real org.credits_balance decreases."""
        run = TriggerRun(
            id="run_no_ws",
            trigger_id=trigger_no_ws.id,
            organization_id=org.id,
            status="pending",
            credits_consumed=0,
            webhook_attempts=0,
            created_at=utcnow(),
        )
        db_session.add(run)
        db_session.commit()

        initial_balance = org.credits_balance

        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "status": "optimal",
            "objective_value": 0.0,
            "credits_used": 3,
            "variables": [],
            "solution": {},
            "solve_time_seconds": 0.1,
        }
        mock_solve.return_value = mock_result
        mock_session_local.return_value = db_session

        with patch.object(db_session, "close", lambda: None):
            from app.tasks.trigger_tasks import trigger_solve_task

            result = trigger_solve_task(
                run_id=run.id,
                trigger_id=trigger_no_ws.id,
                override_data=None,
            )

        assert result["status"] == "completed"

        # Real assertion: org.credits_balance decreased by exactly 3
        db_session.refresh(org)
        assert org.credits_balance == initial_balance - 3

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.domains.solver.services.solver_service.SolverService.solve")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_org_fallback_on_pool_exhausted(
        self,
        mock_session_local,
        mock_solve,
        mock_webhook,
        db_session,
        org,
        trigger_with_ws,
        test_workspace,
    ):
        """When the real workspace pool has no credits, org balance is debited."""
        from app.models.workspace_credits import WorkspaceCreditPool
        from app.shared.utils.id_generator import generate_id

        # Plant an EMPTY pool (allocated == used)
        pool = WorkspaceCreditPool(
            id=generate_id("wcp_"),
            workspace_id=test_workspace.id,
            organization_id=org.id,
            allocated_credits=10,
            used_credits=10,  # exhausted
            last_alert_threshold=None,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db_session.add(pool)

        run = TriggerRun(
            id="run_pool_exhaust",
            trigger_id=trigger_with_ws.id,
            organization_id=org.id,
            status="pending",
            credits_consumed=0,
            webhook_attempts=0,
            created_at=utcnow(),
        )
        db_session.add(run)
        db_session.commit()

        initial_balance = org.credits_balance
        initial_pool_used = pool.used_credits

        mock_result = MagicMock()
        mock_result.model_dump.return_value = {
            "status": "optimal",
            "objective_value": 0.0,
            "credits_used": 5,
            "variables": [],
            "solution": {},
            "solve_time_seconds": 0.2,
        }
        mock_solve.return_value = mock_result
        mock_session_local.return_value = db_session

        with patch.object(db_session, "close", lambda: None):
            from app.tasks.trigger_tasks import trigger_solve_task

            result = trigger_solve_task(
                run_id=run.id,
                trigger_id=trigger_with_ws.id,
                override_data=None,
            )

        assert result["status"] == "completed"

        # Pool used_credits unchanged (exhausted, fallback path took over)
        db_session.refresh(pool)
        assert pool.used_credits == initial_pool_used

        # Org balance was decremented by the fallback path
        db_session.refresh(org)
        assert org.credits_balance == initial_balance - 5
