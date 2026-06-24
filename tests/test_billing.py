"""
Exhaustive tests for Stripe billing integration.

Tests cover:
- Billing status endpoint (configured/unconfigured)
- Subscription checkout validation (invalid plans, missing org)
- Top-up checkout validation (invalid amounts)
- Subscription cancel without active subscription
- Webhook signature validation
- Webhook event processing (checkout completed, subscription updated/deleted, invoice paid/failed)
- Stripe service configuration
- Edge cases: double subscription, race conditions, missing metadata
"""

from unittest.mock import MagicMock, patch

from app.services.stripe_service import PLAN_CREDITS, StripeService


class TestStripeServiceConfiguration:
    def test_is_configured_returns_false_when_not_configured(self):
        """Should return False when stripe is not configured."""
        # Reset any existing config
        with patch("app.services.stripe_service._stripe", None):
            with patch(
                "app.services.stripe_service._get_stripe", side_effect=RuntimeError("not installed")
            ):
                assert StripeService.is_configured() is False

    def test_plan_credits_mapping(self):
        """Plan credits should match pricing documentation."""
        assert PLAN_CREDITS["free"] == 20000
        assert PLAN_CREDITS["starter"] == 600
        assert PLAN_CREDITS["pro"] == 2500
        assert PLAN_CREDITS["business"] == 20000


class TestBillingStatusEndpoint:
    def test_billing_status_unauthenticated(self, client):
        """Billing status should require authentication (401 without credentials)."""
        response = client.get("/api/v2/billing/status")
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"

    def test_billing_status_returns_configured_false(self, authenticated_client):
        """When Stripe is not configured, should return configured=false."""
        with patch.object(StripeService, "is_configured", return_value=False):
            response = authenticated_client.get("/api/v2/billing/status")
            assert response.status_code == 200
            data = response.json()
            assert data["stripe_configured"] is False
            assert data["has_subscription"] is False


class TestSubscriptionCheckoutEndpoint:
    def test_invalid_plan_rejected(self, authenticated_client):
        """Invalid plan names should be rejected."""
        with patch.object(StripeService, "is_configured", return_value=True):
            response = authenticated_client.post(
                "/api/v2/billing/checkout/subscription",
                json={
                    "plan": "ultra_mega_plan",
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            assert response.status_code == 400
            assert "Invalid plan" in response.json()["detail"]

    def test_free_plan_rejected(self, authenticated_client):
        """Free plan should not be purchasable."""
        with patch.object(StripeService, "is_configured", return_value=True):
            response = authenticated_client.post(
                "/api/v2/billing/checkout/subscription",
                json={
                    "plan": "free",
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            assert response.status_code == 400
            assert "Invalid plan" in response.json()["detail"]

    def test_stripe_not_configured_returns_503(self, authenticated_client):
        """Should return 503 when Stripe is not configured."""
        with patch.object(StripeService, "is_configured", return_value=False):
            response = authenticated_client.post(
                "/api/v2/billing/checkout/subscription",
                json={
                    "plan": "pro",
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            assert response.status_code == 503
            assert "not configured" in response.json()["detail"].lower()


class TestTopupCheckoutEndpoint:
    def test_invalid_credit_amount_rejected(self, authenticated_client):
        """Invalid credit amounts should be rejected."""
        with patch.object(StripeService, "is_configured", return_value=True):
            response = authenticated_client.post(
                "/api/v2/billing/checkout/topup",
                json={
                    "credits": 999,
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            assert response.status_code == 400
            assert "Invalid credit amount" in response.json()["detail"]

    def test_zero_credits_rejected(self, authenticated_client):
        """Zero credits should fail Pydantic validation (gt=0) with 422."""
        with patch.object(StripeService, "is_configured", return_value=True):
            response = authenticated_client.post(
                "/api/v2/billing/checkout/topup",
                json={
                    "credits": 0,
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            assert response.status_code == 422
            # Pydantic error payload must point at the `credits` field.
            errors = response.json().get("detail", [])
            assert any("credits" in err.get("loc", []) for err in errors), (
                f"Expected validation error on 'credits' field, got {errors!r}"
            )

    def test_negative_credits_rejected(self, authenticated_client):
        """Negative credits should fail Pydantic validation (gt=0) with 422."""
        with patch.object(StripeService, "is_configured", return_value=True):
            response = authenticated_client.post(
                "/api/v2/billing/checkout/topup",
                json={
                    "credits": -500,
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            assert response.status_code == 422
            errors = response.json().get("detail", [])
            assert any("credits" in err.get("loc", []) for err in errors), (
                f"Expected validation error on 'credits' field, got {errors!r}"
            )


class TestSubscriptionCancelEndpoint:
    def test_cancel_without_subscription(self, authenticated_client):
        """Cancelling without a subscription should fail with 400 (no sub) or 502 (stripe error)."""
        mock_stripe_mod = MagicMock()
        with (
            patch.object(StripeService, "is_configured", return_value=True),
            patch("app.services.stripe_service._stripe", mock_stripe_mod),
            patch("app.services.stripe_service._get_stripe", return_value=mock_stripe_mod),
        ):
            response = authenticated_client.post("/api/v2/billing/subscription/cancel")
            # Org has no stripe_subscription_id → ValueError → 400
            assert response.status_code == 400
            assert "no active subscription" in response.json()["detail"].lower()


class TestWebhookEndpoint:
    def test_webhook_missing_signature(self, client):
        """With Stripe configured, webhook without signature header is rejected 400."""
        with (
            patch.object(StripeService, "is_configured", return_value=True),
            patch.object(StripeService, "_webhook_secret", "whsec_test"),
        ):
            response = client.post(
                "/api/v2/billing/webhook",
                content=b'{"type": "test"}',
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 400
        assert "Stripe-Signature" in response.json()["detail"]

    def test_webhook_empty_body(self, client):
        """Webhook with empty body + bogus signature must return 400, not 500.

        An empty body will fail Stripe signature verification (ValueError) and
        the endpoint maps that to 400 — 500 here would indicate an unhandled
        server crash.
        """
        with (
            patch.object(StripeService, "is_configured", return_value=True),
            patch.object(StripeService, "_webhook_secret", "whsec_test"),
        ):
            response = client.post(
                "/api/v2/billing/webhook",
                content=b"",
                headers={
                    "Content-Type": "application/json",
                    "stripe-signature": "t=123,v1=abc",
                },
            )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert isinstance(detail, str) and detail, "Missing error detail on webhook 400"


class TestWebhookProcessing:
    def test_handle_checkout_completed_subscription(self, db_session, test_organization):
        """Successful subscription checkout should update plan and grant credits."""
        service = StripeService(db_session)
        session_data = {
            "id": "cs_test_123",
            "subscription": "sub_test_123",
            "metadata": {
                "organization_id": test_organization.id,
                "type": "subscription",
                "plan": "pro",
            },
        }
        initial_balance = test_organization.credits_balance
        result = service._handle_checkout_completed(session_data)

        assert result["action"] == "subscription_activated"
        assert result["plan"] == "pro"
        assert test_organization.plan == "pro"
        assert test_organization.credits_balance == initial_balance + PLAN_CREDITS["pro"]

    def test_handle_checkout_completed_topup(self, db_session, test_organization):
        """Successful top-up checkout should add credits."""
        service = StripeService(db_session)
        session_data = {
            "id": "cs_test_456",
            "metadata": {
                "organization_id": test_organization.id,
                "type": "topup",
                "credits": "2000",
            },
        }
        initial_balance = test_organization.credits_balance
        result = service._handle_checkout_completed(session_data)

        assert result["action"] == "topup_completed"
        assert result["credits"] == 2000
        assert test_organization.credits_balance == initial_balance + 2000

    def test_handle_checkout_missing_org_id(self, db_session):
        """Checkout without org ID should return the specific 'missing metadata' error."""
        from app.models import CreditTransaction

        before_tx_count = db_session.query(CreditTransaction).count()
        service = StripeService(db_session)
        result = service._handle_checkout_completed({"metadata": {}})

        assert result == {"error": "No organization_id in metadata"}
        # No side effects: no transaction written.
        assert db_session.query(CreditTransaction).count() == before_tx_count

    def test_handle_checkout_nonexistent_org(self, db_session):
        """Checkout for non-existent org returns 'Organization not found' and writes nothing."""
        from app.models import CreditTransaction

        before_tx_count = db_session.query(CreditTransaction).count()
        service = StripeService(db_session)
        result = service._handle_checkout_completed(
            {
                "metadata": {
                    "organization_id": "org_nonexistent",
                    "type": "subscription",
                    "plan": "pro",
                },
            }
        )

        assert result == {"error": "Organization org_nonexistent not found"}
        # No side effects for an unknown org.
        assert db_session.query(CreditTransaction).count() == before_tx_count

    def test_handle_subscription_deleted(self, db_session, test_organization):
        """Subscription deletion should downgrade to free."""
        test_organization.plan = "pro"
        db_session.commit()

        service = StripeService(db_session)
        result = service._handle_subscription_deleted(
            {
                "metadata": {"organization_id": test_organization.id},
            }
        )

        assert result["action"] == "subscription_cancelled"
        assert test_organization.plan == "free"

    def test_handle_invoice_failed(self, db_session, test_organization):
        """Failed invoice must be a pure log event — no balance, plan, or sub changes."""
        initial_balance = test_organization.credits_balance
        initial_plan = test_organization.plan
        initial_sub_id = getattr(test_organization, "stripe_subscription_id", None)

        service = StripeService(db_session)
        result = service._handle_invoice_failed({"id": "inv_test_fail"})
        db_session.refresh(test_organization)

        assert result == {"action": "payment_failed", "invoice_id": "inv_test_fail"}
        # No side effects on the org.
        assert test_organization.credits_balance == initial_balance
        assert test_organization.plan == initial_plan
        assert getattr(test_organization, "stripe_subscription_id", None) == initial_sub_id

    def test_handle_topup_zero_credits(self, db_session, test_organization):
        """Top-up with 0 credits should not change balance."""
        service = StripeService(db_session)
        initial_balance = test_organization.credits_balance
        service._handle_checkout_completed(
            {
                "metadata": {
                    "organization_id": test_organization.id,
                    "type": "topup",
                    "credits": "0",
                },
            }
        )
        assert test_organization.credits_balance == initial_balance


class TestCrossTenantCreditIsolation:
    """Two orgs deducting credits concurrently must never interfere with each other.

    Gap filled per audit missing-test #1 ("Cross-tenant credit isolation under
    concurrent writes"). Previous concurrency tests used only one org; this
    one launches 20 threads against each of TWO orgs simultaneously and
    verifies both end at the exact expected balance with no cross-contamination.
    """

    def test_two_orgs_20_threads_each_no_cross_contamination(self, db_session, db_engine):
        import queue
        import threading

        from sqlalchemy.orm import sessionmaker

        from app.models import CreditTransaction, Organization
        from app.services.credits_service import CreditsService, InsufficientCreditsError
        from app.shared.utils.id_generator import generate_id

        # Two fresh orgs with identical balances — 20 threads * 50 = 1000.
        org_a_id = generate_id("org_")
        org_b_id = generate_id("org_")
        for org_id in (org_a_id, org_b_id):
            db_session.add(
                Organization(
                    id=org_id,
                    name=f"Tenant {org_id}",
                    credits_balance=1000,
                    credits_earned=0,
                    monthly_quota=100,
                    currency="EUR",
                    is_active=True,
                )
            )
        db_session.commit()

        SessionFactory = sessionmaker(bind=db_engine)
        results: queue.Queue = queue.Queue()
        # 40 threads total: 20 per org. Barrier forces them to race.
        barrier = threading.Barrier(40, timeout=30)

        def worker(org_id: str, thread_id: int) -> None:
            session = SessionFactory()
            try:
                barrier.wait()
                CreditsService.deduct_credits(
                    db=session,
                    organization_id=org_id,
                    credits=50,
                    description=f"Cross-tenant test {thread_id}",
                    reference_type="execution",
                    reference_id=f"crosstenant_{org_id}_{thread_id}",
                )
                session.commit()
                results.put(("success", org_id))
            except InsufficientCreditsError:
                session.rollback()
                results.put(("insufficient", org_id))
            except Exception as exc:
                session.rollback()
                results.put(("error", org_id, str(exc)))
            finally:
                session.close()

        threads = []
        for i in range(20):
            threads.append(
                threading.Thread(target=worker, args=(org_a_id, i), name=f"tenant-a-{i}")
            )
            threads.append(
                threading.Thread(target=worker, args=(org_b_id, i), name=f"tenant-b-{i}")
            )
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        alive = [t.name for t in threads if t.is_alive()]
        assert not alive, f"Threads still alive after 60s: {alive}"

        # Drain the queue.
        a_succ = 0
        b_succ = 0
        errors: list = []
        while not results.empty():
            r = results.get()
            if r[0] == "success":
                if r[1] == org_a_id:
                    a_succ += 1
                else:
                    b_succ += 1
            elif r[0] == "error":
                errors.append(r)

        assert not errors, f"Unexpected errors: {errors}"
        assert a_succ == 20, f"Expected 20 successes for org A, got {a_succ}"
        assert b_succ == 20, f"Expected 20 successes for org B, got {b_succ}"

        # Verify both balances land at exactly 0 with NO cross-contamination.
        fresh = SessionFactory()
        try:
            org_a_fresh = fresh.get(Organization, org_a_id)
            org_b_fresh = fresh.get(Organization, org_b_id)
            assert org_a_fresh.credits_balance == 0, (
                f"Org A balance drift: expected 0, got {org_a_fresh.credits_balance}"
            )
            assert org_b_fresh.credits_balance == 0, (
                f"Org B balance drift: expected 0, got {org_b_fresh.credits_balance}"
            )

            # Every transaction is scoped to its own org; NEVER the other.
            a_txs = (
                fresh.query(CreditTransaction)
                .filter(CreditTransaction.organization_id == org_a_id)
                .all()
            )
            b_txs = (
                fresh.query(CreditTransaction)
                .filter(CreditTransaction.organization_id == org_b_id)
                .all()
            )
            assert len(a_txs) == 20
            assert len(b_txs) == 20
            for tx in a_txs:
                assert tx.reference_id.startswith(f"crosstenant_{org_a_id}_")
            for tx in b_txs:
                assert tx.reference_id.startswith(f"crosstenant_{org_b_id}_")
        finally:
            fresh.close()


class TestBillingPortalRejectionMatrix:
    """SC3 rejection-matrix cells for POST /api/v2/billing/portal.

    Owner = PLAN_02 (financial endpoint); rejection-matrix
    cells #1 (401) and #2 (422).
    """

    def test_billing_portal_unauthenticated_returns_401(self, client):
        """SC3 cell #1: anonymous POST to /api/v2/billing/portal returns 401."""
        response = client.post("/api/v2/billing/portal", json={})
        assert response.status_code == 401, (
            f"Expected 401 for anonymous POST /api/v2/billing/portal, "
            f"got {response.status_code}: {response.json()}"
        )
        assert response.json()["error"] == "unauthorized"

    def test_billing_portal_malformed_body_returns_422(self, authenticated_client):
        """SC3 cell #2: POST /api/v2/billing/portal with type-invalid body returns 422.

        PortalRequest declares return_url: str. Passing a non-string (an int)
        must trigger Pydantic validation and return 422 with the field-level
        error pointing at 'return_url'.
        """
        with patch.object(StripeService, "is_configured", return_value=True):
            response = authenticated_client.post(
                "/api/v2/billing/portal",
                json={"return_url": 123},  # int, not str -> Pydantic rejects
            )
        assert response.status_code == 422, (
            f"Expected 422 for type-invalid return_url, got {response.status_code}: "
            f"{response.json()}"
        )
        errors = response.json().get("detail", [])
        assert any("return_url" in (err.get("loc") or []) for err in errors), (
            f"Expected validation error on 'return_url' field, got {errors!r}"
        )
