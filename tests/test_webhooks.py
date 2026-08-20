"""
Tests for the outbound webhook delivery service.

Covers:
- Payload building and signing
- Webhook delivery (success, failure, timeout)
- Event builders (execution.completed, execution.failed)
- Celery task integration
- HMAC signature verification
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
        )
        assert event["event"] == "execution.completed"
        assert event["data"]["execution_id"] == "exe_456"
        assert event["data"]["objective_value"] == 1800.0

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


class TestWebhookOutcomeIsRecorded:
    """Every attempt and the final verdict land on the TriggerRun.

    Found by driving the app (QA sweep, 2026-08-20): ``webhook_attempts`` and
    ``webhook_delivered`` were columns nobody ever wrote. The Run History table
    has a Webhook column that reads them, so it always showed "—", and the admin
    panel's webhook delivery rate was a ratio over an empty set.
    """

    @staticmethod
    def _run(db, org, user):
        from app.models.trigger import SolveTrigger, TriggerRun
        from app.shared.utils.datetime_helpers import utcnow
        from app.shared.utils.id_generator import generate_id

        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=org.id,
            created_by=user.id,
            name="Webhook outcome",
            trigger_secret="hash",
            webhook_url="https://example.com/webhook",
            is_enabled=True,
            total_runs=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(trigger)
        db.flush()
        run = TriggerRun(
            id=generate_id("trun_"),
            trigger_id=trigger.id,
            organization_id=org.id,
            status="completed",
            webhook_attempts=0,
            created_at=utcnow(),
        )
        db.add(run)
        db.commit()
        return trigger, run

    def test_a_delivered_webhook_is_recorded_on_the_run(
        self, db_session, test_organization, test_user
    ):
        from app.tasks.webhook_tasks import deliver_webhook_task

        _, run = self._run(db_session, test_organization, test_user)

        with patch("app.tasks.webhook_tasks.deliver_webhook", return_value=True):
            result = deliver_webhook_task(
                url="https://example.com/webhook",
                payload={"event": "test"},
                run_id=run.id,
            )
        assert result["status"] == "delivered"

        db_session.expire_all()
        db_session.refresh(run)
        assert run.webhook_attempts == 1
        assert run.webhook_delivered is True

    def test_an_attempt_that_still_has_retries_left_counts_without_a_verdict(
        self, db_session, test_organization, test_user
    ):
        from app.tasks.webhook_tasks import deliver_webhook_task

        _, run = self._run(db_session, test_organization, test_user)

        with patch("app.tasks.webhook_tasks.deliver_webhook", return_value=False):
            with pytest.raises(Exception, match="Webhook delivery failed"):
                deliver_webhook_task(
                    url="https://example.com/webhook",
                    payload={"event": "test"},
                    run_id=run.id,
                )

        db_session.expire_all()
        db_session.refresh(run)
        assert run.webhook_attempts == 1
        # Still trying: a verdict now would read as "never arrived" while a retry
        # is still queued.
        assert run.webhook_delivered is None

    def test_the_last_attempt_writes_the_verdict_and_tells_the_owner(
        self, db_session, test_organization, test_user
    ):
        from app.models.notification import Notification
        from app.tasks.webhook_tasks import deliver_webhook_task

        trigger, run = self._run(db_session, test_organization, test_user)

        # The worker's own state on the final try, so the task takes the branch
        # a fourth failure takes in production.
        deliver_webhook_task.push_request(retries=deliver_webhook_task.max_retries)
        try:
            with patch("app.tasks.webhook_tasks.deliver_webhook", return_value=False):
                with pytest.raises(Exception, match="Webhook delivery failed"):
                    deliver_webhook_task(
                        url="https://example.com/webhook",
                        payload={"event": "test"},
                        run_id=run.id,
                    )
        finally:
            deliver_webhook_task.pop_request()

        db_session.expire_all()
        db_session.refresh(run)
        assert run.webhook_attempts == 1
        assert run.webhook_delivered is False

        notes = (
            db_session.query(Notification).filter(Notification.user_id == trigger.created_by).all()
        )
        assert any("Webhook delivery failed" in (n.title or "") for n in notes), (
            "the person who owns the trigger is never told the result did not arrive"
        )

    def test_without_a_run_id_nothing_is_written_and_nothing_breaks(self):
        # cron_tasks sends an auto_disabled webhook that belongs to no run.
        from app.tasks.webhook_tasks import deliver_webhook_task

        with patch("app.tasks.webhook_tasks.deliver_webhook", return_value=True):
            result = deliver_webhook_task(url="https://example.com/webhook", payload={"event": "t"})
        assert result["status"] == "delivered"
