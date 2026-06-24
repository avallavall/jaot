"""OWASP A01: Cross-tenant isolation tests.

Verifies that Organization B cannot access Organization A's data
through any API endpoint. All tests use two separate orgs and users.

Test strategy:
- Create test data for org_a (test_organization + test_user)
- Switch auth context to test_user_2 (org_b) via mock_auth
- Attempt to access org_a's data by ID
- Assert 404 for single-resource endpoints (no information disclosure)
- Assert empty results for list endpoints
"""

# CONTRACT-TEST: cross-tenant-isolation (CR-02)
#   Organization B cannot access Organization A's data through any API endpoint.
#   Cross-tenant 404 detail string is identical to genuine 404 (anti-oracle, D-18).
#   Removing this file removes the cross-tenant IDOR regression guard.

import hashlib
import secrets
import uuid
from datetime import timedelta
from unittest.mock import patch

from app.models import (
    APIKey,
    CreditTransaction,
    Invoice,
    LLMConversation,
    ModelBuilderDocument,
    ModelCatalog,
    ModelExecution,
    ModelVersion,
    Notification,
    OrganizationModel,
    SolveTrigger,
)
from app.shared.utils.datetime_helpers import utcnow

# HELPERS: Create test data for an organization


def _create_catalog_model(db_session) -> ModelCatalog:
    """Create a shared catalog model (not org-specific)."""
    catalog = ModelCatalog(
        id=f"cat_{uuid.uuid4().hex[:12]}",
        name="test_model",
        display_name="Test Model",
        description="A test model",
        generator_type="generic",
        input_schema={},
        input_fields=[],
        example_input={},
        category="general",
        is_official=True,
        status="published",
    )
    db_session.add(catalog)
    db_session.flush()
    return catalog


def _create_org_model(db_session, org, catalog) -> OrganizationModel:
    """Create an organization model linked to a catalog entry."""
    model = OrganizationModel(
        id=f"orgm_{uuid.uuid4().hex[:12]}",
        organization_id=org.id,
        catalog_id=catalog.id,
        custom_name="Test Org Model",
        is_active=True,
    )
    db_session.add(model)
    db_session.flush()
    return model


def _create_execution(db_session, org, user, org_model=None) -> ModelExecution:
    """Create a test execution for an org."""
    execution = ModelExecution(
        id=f"exe_{uuid.uuid4().hex[:12]}",
        organization_id=org.id,
        organization_model_id=org_model.id if org_model else None,
        executed_by_user_id=user.id,
        input_data={"test": True},
        status="completed",
        result_data={"solution": {"x": 1.0}},
        solver_status="optimal",
        objective_value=42.0,
        credits_consumed=1,
        credits_base=1,
        execution_time_ms=100,
        created_at=utcnow(),
        completed_at=utcnow(),
    )
    db_session.add(execution)
    db_session.flush()
    return execution


def _create_api_key(db_session, user, org) -> APIKey:
    """Create a test API key for an org."""
    raw_key = f"ok_test_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = APIKey(
        id=f"key_{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        organization_id=org.id,
        name="Test Key for Isolation",
        key_hash=key_hash,
        key_prefix=raw_key[:12],
        is_active=True,
    )
    db_session.add(api_key)
    db_session.flush()
    return api_key


def _create_credit_transaction(db_session, org) -> CreditTransaction:
    """Create a test credit transaction for an org."""
    txn = CreditTransaction(
        id=f"txn_{uuid.uuid4().hex[:12]}",
        organization_id=org.id,
        transaction_type="purchase",
        credits_amount=100,
        balance_after=1100,
        description="Test purchase",
        created_at=utcnow(),
    )
    db_session.add(txn)
    db_session.flush()
    return txn


def _create_invoice(db_session, org) -> Invoice:
    """Create a test invoice for an org."""
    invoice = Invoice(
        id=f"inv_{uuid.uuid4().hex[:12]}",
        invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
        organization_id=org.id,
        invoice_type="topup",
        status="paid",
        org_name=org.name,
        org_plan="free",
        subtotal_eur=10.0,
        tax_rate=0.0,
        tax_amount_eur=0.0,
        total_eur=10.0,
        currency="EUR",
        exchange_rate=1.0,
        total_local=10.0,
        credits_granted=500,
        issued_at=utcnow(),
        paid_at=utcnow(),
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


def _create_llm_conversation(db_session, org, user) -> LLMConversation:
    """Create a test LLM conversation for an org/user."""
    conv = LLMConversation(
        id=f"conv_{uuid.uuid4().hex[:12]}",
        organization_id=org.id,
        user_id=user.id,
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(hours=24),
    )
    db_session.add(conv)
    db_session.flush()
    return conv


def _create_builder_document(db_session, org, user) -> ModelBuilderDocument:
    """Create a test builder document for an org."""
    doc = ModelBuilderDocument(
        id=f"doc_{uuid.uuid4().hex[:12]}",
        organization_id=org.id,
        created_by=user.id,
        name="Test Document",
        canvas_json={"nodes": [], "edges": []},
        is_active=True,
    )
    db_session.add(doc)
    db_session.flush()
    return doc


def _create_trigger(db_session, org, user, doc, version) -> SolveTrigger:
    """Create a test solve trigger for an org."""
    trigger = SolveTrigger(
        id=f"trg_{uuid.uuid4().hex[:12]}",
        organization_id=org.id,
        created_by=user.id,
        name="Test Trigger",
        document_id=doc.id,
        version_id=version.id,
        trigger_secret=hashlib.sha256(b"secret").hexdigest(),
        webhook_url="https://example.com/webhook",
        is_enabled=True,
    )
    db_session.add(trigger)
    db_session.flush()
    return trigger


def _create_model_version(db_session, org, doc) -> ModelVersion:
    """Create a model version snapshot."""
    version = ModelVersion(
        id=f"ver_{uuid.uuid4().hex[:12]}",
        document_id=doc.id,
        organization_id=org.id,
        canvas_json={"nodes": [], "edges": []},
        sequence=1,
    )
    db_session.add(version)
    db_session.flush()
    return version


def _create_notification(db_session, org, user) -> Notification:
    """Create a test notification for a user."""
    notification = Notification(
        id=f"ntf_{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        organization_id=org.id,
        type="system",
        title="Test Notification",
        message="This is a test notification",
        is_read=False,
        created_at=utcnow(),
    )
    db_session.add(notification)
    db_session.flush()
    return notification


class TestCrossTenantExecutionStatus:
    """Org B cannot access Org A's execution via solve status endpoint."""

    def test_cross_tenant_execution_status(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/models/executions/{id} returns 404 for cross-tenant access."""
        # Create execution for org_a
        mock_auth(test_user)
        execution = _create_execution(db_session, test_organization, test_user)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Attempt to access org_a's execution
        response = client.get(f"/api/v2/models/executions/{execution.id}")
        assert response.status_code == 404


class TestCrossTenantAsyncExecution:
    """CR-02: GET /api/v2/models/async/{task_id} must not leak cross-tenant data.

    Regression lock for CR-02 — verifies
    app/api/v2/routes/models/execution.py::get_async_execution_status enforces the
    organization_id filter (lines 349-366). The production fix is already in HEAD
    (added during Phase 6). These tests exist ONLY to fail loudly if a future
    refactor silently removes the `ModelExecution.organization_id == current_user.
    organization_id` filter or weakens the anti-oracle 404 response body.

    Anti-oracle invariant (CONTEXT D-18): the 404 response body is IDENTICAL whether
    the task_id exists in another org or does not exist anywhere. Returning 403 for
    "exists in another org" would tell an attacker the task is real — hence 404 with
    the exact message `"Task not found or not authorized"` for both cases.
    """

    def test_cross_tenant_async_task_status_returns_404(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """Org B user cannot read Org A's async task status.

        Regression lock: asserts the `organization_id` filter on
        get_async_execution_status (execution.py:354-361) blocks cross-tenant reads
        and returns 404 (not 403) to avoid leaking task existence to outsiders.
        """
        mock_auth(test_user)
        execution = _create_execution(db_session, test_organization, test_user)
        execution.celery_task_id = "celery_task_ab_xtenant_01"
        db_session.flush()
        db_session.commit()

        mock_auth(test_user_2)

        response = client.get("/api/v2/models/async/celery_task_ab_xtenant_01")
        assert response.status_code == 404, (
            f"Expected 404, got {response.status_code}: {response.text}"
        )

        body = response.json()
        assert body.get("detail") == "Task not found or not authorized", (
            f"Anti-oracle violated: unexpected detail: {body}"
        )

        body_text = response.text.lower()
        assert execution.id.lower() not in body_text
        assert test_organization.id.lower() not in body_text
        assert "forbidden" not in body_text

    @patch("celery.result.AsyncResult")
    def test_same_tenant_async_task_status_returns_non_404(
        self,
        mock_async_result_cls,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_organization,
    ):
        """Positive control: Org A user CAN read their own task status.

        Regression lock: verifies the ownership filter does NOT over-match and
        erroneously 404 the task owner. Without this control, a buggy refactor
        that swaps `==` for `!=` would silently pass the cross-tenant 404 test
        while breaking the happy path.

        Mocking note (Phase 06.1-05 / Rule 1 fix): after the tenant filter
        passes, the production route reads ``AsyncResult(task_id, app=celery_app).state``
        — which lazily connects to the broker. CI has ``CELERY_BROKER_URL=""``
        so the connection fails with kombu ``Errno 111`` before we can assert
        on the tenant-filter behavior. Patch ``celery.result.AsyncResult`` to
        return a PENDING state and keep the test focused on the ownership
        filter, NOT on broker IO. Mirrors the pattern already used in
        ``tests/test_ws_auth.py::test_cancel_own_task_succeeds``.
        """
        mock_async_result_cls.return_value.state = "PENDING"

        mock_auth(test_user)
        execution = _create_execution(db_session, test_organization, test_user)
        execution.celery_task_id = "celery_task_same_tenant_01"
        db_session.flush()
        db_session.commit()

        response = client.get("/api/v2/models/async/celery_task_same_tenant_01")
        assert response.status_code != 404, (
            f"Same-tenant request should NOT 404, got {response.status_code}: {response.text}"
        )
        assert 200 <= response.status_code < 300, (
            f"Expected 2xx, got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body.get("task_id") == "celery_task_same_tenant_01"

    def test_nonexistent_task_id_returns_same_404_as_cross_tenant(
        self,
        app,
        client,
        mock_auth,
        test_user,
    ):
        """Anti-oracle: 404 body is identical for 'not in my org' and 'does not exist'.

        Regression lock: verifies the 404 detail string matches the cross-tenant
        case exactly. Any divergence (e.g. adding "in this organization" to the
        "not found" case) would give attackers an oracle distinguishing
        "exists-elsewhere" from "does-not-exist".
        """
        mock_auth(test_user)
        response = client.get("/api/v2/models/async/celery_task_does_not_exist_anywhere")
        assert response.status_code == 404
        assert response.json().get("detail") == "Task not found or not authorized"


class TestCrossTenantCredits:
    """Org B cannot see Org A's credit transactions."""

    def test_cross_tenant_credit_transactions(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/credits/transactions returns empty list for cross-tenant access."""
        # Create transaction for org_a
        mock_auth(test_user)
        _create_credit_transaction(db_session, test_organization)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty transaction list (not org A's data)
        response = client.get("/api/v2/credits/transactions")
        assert response.status_code == 200
        data = response.json()
        assert data == [] or len(data) == 0


class TestCrossTenantAPIKeys:
    """Org B cannot delete Org A's API keys."""

    def test_cross_tenant_api_key_delete(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """DELETE /api/v2/keys/{id} returns 404 for cross-tenant access."""
        # Create API key for org_a
        mock_auth(test_user)
        api_key = _create_api_key(db_session, test_user, test_organization)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Attempt to delete org_a's API key
        response = client.delete(f"/api/v2/keys/{api_key.id}")
        assert response.status_code == 404

    def test_cross_tenant_api_key_list_isolation(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/keys/ returns only the requesting user's keys."""
        # Create API key for org_a
        mock_auth(test_user)
        _create_api_key(db_session, test_user, test_organization)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty key list
        response = client.get("/api/v2/keys/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestCrossTenantBilling:
    """Org B cannot access Org A's invoices."""

    def test_cross_tenant_invoice_access(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/billing/invoices/{id} returns 404 for cross-tenant access."""
        # Create invoice for org_a
        mock_auth(test_user)
        invoice = _create_invoice(db_session, test_organization)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Attempt to access org_a's invoice
        response = client.get(f"/api/v2/billing/invoices/{invoice.id}")
        assert response.status_code == 404

    def test_cross_tenant_invoice_list_isolation(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/billing/invoices returns only the requesting org's invoices."""
        # Create invoice for org_a
        mock_auth(test_user)
        _create_invoice(db_session, test_organization)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty invoice list
        response = client.get("/api/v2/billing/invoices")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestCrossTenantModelExecution:
    """Org B cannot access Org A's model execution details."""

    def test_cross_tenant_execution_list_isolation(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/models/executions/all returns only org's own executions."""
        # Create execution for org_a
        mock_auth(test_user)
        _create_execution(db_session, test_organization, test_user)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty execution list
        response = client.get("/api/v2/models/executions/all")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestCrossTenantMyModels:
    """Org B cannot access Org A's private models."""

    def test_cross_tenant_my_model_access(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/models/{id} returns 404 for cross-tenant model access."""
        # Create model for org_a
        mock_auth(test_user)
        catalog = _create_catalog_model(db_session)
        org_model = _create_org_model(db_session, test_organization, catalog)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Attempt to access org_a's model
        response = client.get(f"/api/v2/models/{org_model.id}")
        assert response.status_code == 404

    def test_cross_tenant_model_list_isolation(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/models/ returns only the requesting org's models."""
        # Create model for org_a
        mock_auth(test_user)
        catalog = _create_catalog_model(db_session)
        _create_org_model(db_session, test_organization, catalog)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty model list
        response = client.get("/api/v2/models/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestCrossTenantLLMConversation:
    """Org B cannot access Org A's LLM conversations."""

    def test_cross_tenant_llm_conversation(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/llm/conversations/{id} returns 404 for cross-tenant access."""
        # Create conversation for org_a
        mock_auth(test_user)
        conv = _create_llm_conversation(db_session, test_organization, test_user)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Attempt to access org_a's conversation
        response = client.get(f"/api/v2/llm/conversations/{conv.id}")
        assert response.status_code == 404

    def test_cross_tenant_llm_conversation_list_isolation(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/llm/conversations returns empty for cross-tenant access."""
        # Create conversation for org_a
        mock_auth(test_user)
        _create_llm_conversation(db_session, test_organization, test_user)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty conversation list
        response = client.get("/api/v2/llm/conversations")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []


class TestCrossTenantBuilderDocument:
    """Org B cannot access Org A's builder documents."""

    def test_cross_tenant_builder_document(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/builder/documents/{id} returns 404 for cross-tenant access."""
        # Create builder document for org_a
        mock_auth(test_user)
        doc = _create_builder_document(db_session, test_organization, test_user)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Attempt to access org_a's document
        response = client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 404

    def test_cross_tenant_builder_list_isolation(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/builder/ returns only the requesting org's documents."""
        # Create builder document for org_a
        mock_auth(test_user)
        _create_builder_document(db_session, test_organization, test_user)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty document list (builder returns a plain list)
        response = client.get("/api/v2/builder/")
        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestCrossTenantTrigger:
    """Org B cannot access Org A's triggers."""

    def test_cross_tenant_trigger_access(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/triggers/{id} returns 404 for cross-tenant access."""
        # Create trigger for org_a (needs doc + version)
        mock_auth(test_user)
        doc = _create_builder_document(db_session, test_organization, test_user)
        version = _create_model_version(db_session, test_organization, doc)
        trigger = _create_trigger(db_session, test_organization, test_user, doc, version)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Attempt to access org_a's trigger
        response = client.get(f"/api/v2/triggers/{trigger.id}")
        assert response.status_code == 404

    def test_cross_tenant_trigger_list_isolation(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/triggers/ returns only the requesting org's triggers."""
        # Create trigger for org_a
        mock_auth(test_user)
        doc = _create_builder_document(db_session, test_organization, test_user)
        version = _create_model_version(db_session, test_organization, doc)
        _create_trigger(db_session, test_organization, test_user, doc, version)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty trigger list (triggers returns a plain list)
        response = client.get("/api/v2/triggers/")
        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestCrossTenantNotifications:
    """Org B cannot see Org A's notifications."""

    def test_cross_tenant_notification_access(
        self,
        app,
        client,
        db_session,
        mock_auth,
        test_user,
        test_user_2,
        test_organization,
        test_organization_2,
    ):
        """GET /api/v2/notifications returns empty for cross-tenant access."""
        # Create notification for org_a user
        mock_auth(test_user)
        _create_notification(db_session, test_organization, test_user)
        db_session.commit()

        # Switch to org_b user
        mock_auth(test_user_2)

        # Org B should see empty notification list (scoped by user_id)
        response = client.get("/api/v2/notifications")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["unread_count"] == 0
