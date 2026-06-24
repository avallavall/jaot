"""
Tests for the webhook delivery service and Stripe webhook idempotency.

Covers:
- Payload building and signing
- Webhook delivery (success, failure, timeout)
- Event builders (execution.completed, execution.failed, credits.low)
- Celery task integration
- HMAC signature verification
- Stripe checkout.session.completed idempotency (TEST-08)
- Invalid Stripe signatures rejection
- Missing metadata handling
"""

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.webhook_service import (
    _sign_payload,
    build_webhook_payload,
    credits_low_event,
    deliver_webhook,
    execution_completed_event,
    execution_failed_event,
)


class TestBuildPayload:
    def test_basic_payload(self):
        payload = build_webhook_payload(
            event_type="test.event",
            data={"key": "value"},
            organization_id="org_123",
        )
        assert payload["event"] == "test.event"
        assert payload["organization_id"] == "org_123"
        assert payload["data"]["key"] == "value"
        assert "timestamp" in payload

    def test_timestamp_format(self):
        payload = build_webhook_payload("test", {}, "org_1")
        assert payload["timestamp"].endswith("Z")

    def test_empty_data(self):
        payload = build_webhook_payload("test", {}, "org_1")
        assert payload["data"] == {}


class TestSigning:
    def test_sign_payload(self):
        payload = b'{"event":"test"}'
        secret = "my_secret_key"
        sig = _sign_payload(payload, secret)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest

    def test_sign_deterministic(self):
        payload = b'{"event":"test"}'
        sig1 = _sign_payload(payload, "secret")
        sig2 = _sign_payload(payload, "secret")
        assert sig1 == sig2

    def test_different_secrets_different_sigs(self):
        payload = b'{"event":"test"}'
        sig1 = _sign_payload(payload, "secret1")
        sig2 = _sign_payload(payload, "secret2")
        assert sig1 != sig2

    def test_verify_signature(self):
        """Simulate what a webhook receiver would do to verify."""
        payload = b'{"event":"test"}'
        secret = "webhook_secret_123"
        signature = _sign_payload(payload, secret)

        # Receiver verifies
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(signature, expected)


class TestDelivery:
    def test_successful_delivery(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        with patch("app.services.webhook_service.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            result = deliver_webhook(
                url="https://example.com/webhook",
                payload={"event": "test"},
            )
            assert result is True

    def test_failed_delivery_4xx(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        with patch("app.services.webhook_service.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            result = deliver_webhook(
                url="https://example.com/webhook",
                payload={"event": "test"},
            )
            assert result is False

    def test_timeout_returns_false(self):
        with patch("app.services.webhook_service.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            result = deliver_webhook(
                url="https://example.com/webhook",
                payload={"event": "test"},
            )
            assert result is False

    def test_connection_error_returns_false(self):
        with patch("app.services.webhook_service.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.ConnectError("refused")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            result = deliver_webhook(
                url="https://example.com/webhook",
                payload={"event": "test"},
            )
            assert result is False

    def test_delivery_with_signature(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        with patch("app.services.webhook_service.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            result = deliver_webhook(
                url="https://example.com/webhook",
                payload={"event": "test"},
                secret="my_secret",
            )
            assert result is True

            # Verify signature header was sent
            call_kwargs = mock_client.post.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert "X-Jaot-Signature" in headers
            assert headers["X-Jaot-Signature"].startswith("sha256=")

    def test_delivery_includes_event_header(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        with patch("app.services.webhook_service.httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            deliver_webhook(
                url="https://example.com/webhook",
                payload={"event": "execution.completed"},
            )

            call_kwargs = mock_client.post.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert headers["X-Jaot-Event"] == "execution.completed"


class TestEventBuilders:
    def test_execution_completed_event(self):
        event = execution_completed_event(
            organization_id="org_123",
            execution_id="exe_456",
            model_name="Knapsack",
            status="optimal",
            objective_value=1800.0,
            execution_time_ms=247,
            credits_consumed=2,
        )
        assert event["event"] == "execution.completed"
        assert event["data"]["execution_id"] == "exe_456"
        assert event["data"]["objective_value"] == 1800.0
        assert event["data"]["credits_consumed"] == 2

    def test_execution_failed_event(self):
        event = execution_failed_event(
            organization_id="org_123",
            execution_id="exe_789",
            model_name="VRP",
            error_message="Timeout exceeded",
        )
        assert event["event"] == "execution.failed"
        assert event["data"]["error_message"] == "Timeout exceeded"

    def test_credits_low_event(self):
        event = credits_low_event(
            organization_id="org_123",
            current_balance=5,
            threshold=10,
        )
        assert event["event"] == "credits.low"
        assert event["data"]["current_balance"] == 5
        assert event["data"]["threshold"] == 10


class TestWebhookTask:
    def test_deliver_webhook_task_success(self):
        with patch("app.tasks.webhook_tasks.deliver_webhook", return_value=True):
            from app.tasks.webhook_tasks import deliver_webhook_task

            result = deliver_webhook_task(
                url="https://example.com/webhook",
                payload={"event": "test"},
                secret="secret",
            )
            assert result["status"] == "delivered"

    def test_deliver_webhook_task_failure_raises(self):
        with patch("app.tasks.webhook_tasks.deliver_webhook", return_value=False):
            from app.tasks.webhook_tasks import deliver_webhook_task

            with pytest.raises(Exception, match="Webhook delivery failed"):
                deliver_webhook_task(
                    url="https://example.com/webhook",
                    payload={"event": "test"},
                )


class TestStripeWebhookIdempotency:
    """Test Stripe webhook processing idempotency.

    The StripeService._handle_checkout_completed uses CreditsService.record_transaction
    which has built-in idempotency: if a transaction with the same
    (organization_id, transaction_type, reference_type, reference_id) already exists,
    it returns the existing record without modifying the balance.
    """

    def test_duplicate_checkout_event_idempotent(self, db_session):
        """Duplicate checkout.session.completed events must not double-credit."""
        from app.models import CreditTransaction, Organization
        from app.services.stripe_service import StripeService

        # Create organization
        org = Organization(
            id="org_stripe_idem_001",
            name="Stripe Idem Test",
            credits_balance=0,
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()

        # Simulate checkout.session.completed event data
        session_data = {
            "id": "cs_test_idem_001",
            "metadata": {
                "organization_id": "org_stripe_idem_001",
                "type": "topup",
                "credits": "500",
            },
        }

        service = StripeService(db_session)

        # First call: should credit 500
        result1 = service._handle_checkout_completed(session_data)
        db_session.commit()
        assert result1.get("action") == "topup_completed"
        assert result1.get("credits") == 500

        # Check balance after first call
        db_session.expire_all()
        org_after_1 = db_session.get(Organization, "org_stripe_idem_001")
        assert org_after_1.credits_balance == 500

        # Second call: same event -- should NOT double credit
        service._handle_checkout_completed(session_data)
        db_session.commit()

        # Check balance after second call
        db_session.expire_all()
        org_after_2 = db_session.get(Organization, "org_stripe_idem_001")
        assert org_after_2.credits_balance == 500, (
            f"Duplicate event double-credited: balance is "
            f"{org_after_2.credits_balance}, expected 500"
        )

        # Verify only 1 transaction record with this reference
        txn_count = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == "org_stripe_idem_001",
                CreditTransaction.reference_id == "cs_test_idem_001",
            )
            .count()
        )
        assert txn_count == 1, f"Expected 1 transaction, found {txn_count}"

    def test_out_of_order_events(self, db_session):
        """Process checkout.session.completed when org exists but has no prior state."""
        from app.models import Organization
        from app.services.stripe_service import StripeService

        # Create organization with zero credits (fresh state)
        org = Organization(
            id="org_stripe_ooo_001",
            name="Out of Order Test",
            credits_balance=0,
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()

        session_data = {
            "id": "cs_test_ooo_001",
            "metadata": {
                "organization_id": "org_stripe_ooo_001",
                "type": "topup",
                "credits": "500",
            },
        }

        service = StripeService(db_session)
        result = service._handle_checkout_completed(session_data)
        db_session.commit()

        # Should handle gracefully
        assert result.get("action") == "topup_completed"
        db_session.expire_all()
        org_updated = db_session.get(Organization, "org_stripe_ooo_001")
        assert org_updated.credits_balance == 500

    def test_invalid_signature_rejected(self, db_session):
        """Invalid Stripe webhook signature is rejected."""
        from app.services.stripe_service import StripeService

        service = StripeService(db_session)

        # Set a webhook secret
        original_secret = StripeService._webhook_secret
        StripeService._webhook_secret = "whsec_test_secret_123"

        try:
            # Call process_webhook with invalid signature
            with pytest.raises(ValueError, match="(?i)signature|webhook"):
                service.process_webhook(
                    payload=b'{"type":"checkout.session.completed"}',
                    sig_header="invalid_signature_string",
                )
        except RuntimeError:
            # stripe package not installed -- skip gracefully
            pytest.skip("Stripe package not installed")
        finally:
            StripeService._webhook_secret = original_secret

    def test_missing_metadata_handled(self, db_session):
        """Checkout event with no metadata handled gracefully."""
        from app.models import Organization
        from app.services.stripe_service import StripeService

        # Create organization
        org = Organization(
            id="org_stripe_nometa_001",
            name="No Metadata Test",
            credits_balance=100,
            is_active=True,
        )
        db_session.add(org)
        db_session.commit()

        # Session data with empty metadata
        session_data = {
            "id": "cs_test_nometa_001",
            "metadata": {},  # No organization_id, no type, no credits
        }

        service = StripeService(db_session)
        result = service._handle_checkout_completed(session_data)

        # Should return error or action:none, not crash
        assert "error" in result or result.get("action") == "none", (
            f"Expected graceful handling, got: {result}"
        )

        # Balance should be unchanged
        db_session.expire_all()
        org_updated = db_session.get(Organization, "org_stripe_nometa_001")
        assert org_updated.credits_balance == 100
