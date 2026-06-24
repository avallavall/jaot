"""Tests for WebSocket authentication/ownership and cancel endpoint ownership.

Covers:
- WebSocket rejects unauthenticated connections (4001)
- WebSocket rejects invalid tokens (4001)
- WebSocket rejects cross-org connections (4003)
- WebSocket rejects non-existent execution IDs (4004)
- WebSocket accepts valid owner connections
- Cancel returns 403 for cross-org tasks
- Cancel returns 403 for non-existent tasks
- Cancel succeeds for own tasks
- Cookie auth is consistently rejected (4001) -- not implemented for WS
- Token reconnection works correctly
- Multiple concurrent WS connections supported
"""

from unittest.mock import patch

import pytest

from app.models import ModelExecution, Organization, User
from app.services.auth.api_key_service import APIKeyService


@pytest.fixture
def org_a(db_session):
    """Organization A."""
    org = Organization(
        id="org_wsa",
        name="Org A",
        credits_balance=1000,
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def org_b(db_session):
    """Organization B."""
    org = Organization(
        id="org_wsb",
        name="Org B",
        credits_balance=500,
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def user_a(db_session, org_a):
    user = User(
        id="usr_wsa",
        email="ws_a@example.com",
        name="User A",
        organization_id=org_a.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def user_b(db_session, org_b):
    user = User(
        id="usr_wsb",
        email="ws_b@example.com",
        name="User B",
        organization_id=org_b.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def api_key_a(db_session, user_a, org_a):
    """API key for org A."""
    key_model, plaintext = APIKeyService.create_api_key(
        db=db_session,
        user_id=user_a.id,
        organization_id=org_a.id,
        name="Key A",
        prefix="ok_test_",
    )
    key_model.plaintext = plaintext
    return key_model


@pytest.fixture
def api_key_b(db_session, user_b, org_b):
    """API key for org B."""
    key_model, plaintext = APIKeyService.create_api_key(
        db=db_session,
        user_id=user_b.id,
        organization_id=org_b.id,
        name="Key B",
        prefix="ok_test_",
    )
    key_model.plaintext = plaintext
    return key_model


@pytest.fixture
def execution_a(db_session, org_a):
    """Execution owned by org A."""
    exe = ModelExecution(
        id="exe_ws001",
        organization_id=org_a.id,
        input_data={"test": True},
        status="running",
        celery_task_id="celery_ws001",
    )
    db_session.add(exe)
    db_session.commit()
    db_session.refresh(exe)
    return exe


@pytest.fixture
def execution_b(db_session, org_b):
    """Execution owned by org B."""
    exe = ModelExecution(
        id="exe_ws002",
        organization_id=org_b.id,
        input_data={"test": True},
        status="running",
        celery_task_id="celery_ws002",
    )
    db_session.add(exe)
    db_session.commit()
    db_session.refresh(exe)
    return exe


class TestWebSocketAuth:
    """WebSocket authentication and ownership tests."""

    def test_websocket_no_token_rejected(self, app, client, execution_a):
        """Connection without token is closed with 4001."""
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/api/v2/ws/executions/{execution_a.id}"):
                pass  # pragma: no cover
        assert exc_info.value.code == 4001

    def test_websocket_invalid_token_rejected(self, app, client, execution_a):
        """Connection with invalid token is closed with 4001."""
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/api/v2/ws/executions/{execution_a.id}?token=bad_token_value"
            ):
                pass  # pragma: no cover
        assert exc_info.value.code == 4001

    def test_websocket_wrong_org_rejected(self, app, client, execution_a, api_key_b):
        """Org B cannot connect to org A's execution (4003)."""
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/api/v2/ws/executions/{execution_a.id}?token={api_key_b.plaintext}"
            ):
                pass  # pragma: no cover
        assert exc_info.value.code == 4003

    def test_websocket_execution_not_found(self, app, client, api_key_a):
        """Valid token but non-existent execution returns 4004."""
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/api/v2/ws/executions/exe_nonexistent?token={api_key_a.plaintext}"
            ):
                pass  # pragma: no cover
        assert exc_info.value.code == 4004

    def test_websocket_valid_owner_accepted(self, app, client, execution_a, api_key_a):
        """Valid owner can connect and receives initial status."""
        with client.websocket_connect(
            f"/api/v2/ws/executions/{execution_a.id}?token={api_key_a.plaintext}"
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "snapshot"
            assert data["execution_id"] == execution_a.id
            assert data["status"] == "running"


class TestCancelOwnership:
    """Cancel endpoint ownership verification tests."""

    def test_cancel_other_org_task_returns_403(
        self,
        app,
        client,
        db_session,
        execution_a,
        user_b,
        api_key_b,
        org_b,
        mock_auth,
    ):
        """Org B cannot cancel org A's task."""
        mock_auth(user_b)
        resp = client.post(f"/api/v2/solve/async/{execution_a.celery_task_id}/cancel")
        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"]["error"] == "forbidden"

    def test_cancel_nonexistent_task_returns_403(
        self,
        app,
        client,
        db_session,
        user_a,
        api_key_a,
        org_a,
        mock_auth,
    ):
        """Cancelling a random task_id returns 403 (no info leakage)."""
        mock_auth(user_a)
        resp = client.post("/api/v2/solve/async/nonexistent_task_id/cancel")
        assert resp.status_code == 403

    @patch("celery.result.AsyncResult")
    @patch("app.shared.core.celery_app.celery_app")
    def test_cancel_own_task_succeeds(
        self,
        mock_celery,
        mock_async_result_cls,
        app,
        client,
        db_session,
        execution_a,
        user_a,
        api_key_a,
        org_a,
        mock_auth,
    ):
        """Owner can cancel their own task."""
        # Mock celery to avoid needing a real broker
        mock_celery.control.revoke.return_value = None
        mock_async_result_cls.return_value.state = "PENDING"

        mock_auth(user_a)
        resp = client.post(f"/api/v2/solve/async/{execution_a.celery_task_id}/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["cancelled"] is True
        assert body["task_id"] == execution_a.celery_task_id


# Cookie auth tests (documents that cookie auth is NOT implemented for WS)


class TestWebSocketCookieAuth:
    """Cookie-based auth is not supported on the WebSocket endpoint.

    The _authenticate_websocket function in ws.py only checks:
    1. token query param (API key)
    2. Authorization: Bearer header
    It does NOT check cookies. All cookie-only connections are rejected
    with close code 4001 ("Authentication required").
    """

    def test_cookie_auth_not_supported_rejected(self, app, client, execution_a, user_a, org_a):
        """Cookie-only auth with valid JWT is rejected with 4001.

        The WebSocket endpoint does NOT implement cookie auth.
        Even a valid JWT in the access_token cookie is ignored --
        the endpoint requires a token query param or Bearer header.
        """
        from starlette.websockets import WebSocketDisconnect

        from app.services.auth.jwt_service import JWTService

        jwt_token = JWTService.create_access_token(
            user_id=user_a.id,
            org_id=org_a.id,
        )

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/api/v2/ws/executions/{execution_a.id}",
                cookies={"access_token": jwt_token},
            ):
                pass  # pragma: no cover
        assert exc_info.value.code == 4001


class TestWebSocketReconnection:
    """Sequential reconnection tests.

    Renamed from TestWebSocketTokenExpiry / test_multiple_concurrent_ws_connections
    — the Starlette TestClient is synchronous so these do NOT test concurrency
    or expiry. They verify that repeat connect/disconnect cycles through
    ConnectionManager all hand back a fresh snapshot.
    """

    def test_sequential_reconnection_works(self, app, client, execution_a, api_key_a):
        """Reconnecting with the same valid token works and gives fresh snapshot."""
        url = f"/api/v2/ws/executions/{execution_a.id}?token={api_key_a.plaintext}"

        # First connection
        with client.websocket_connect(url) as ws:
            data1 = ws.receive_json()
            assert data1["type"] == "snapshot"
            assert data1["execution_id"] == execution_a.id

        # Second connection (reconnect with same token)
        with client.websocket_connect(url) as ws:
            data2 = ws.receive_json()
            assert data2["type"] == "snapshot"
            assert data2["execution_id"] == execution_a.id

    def test_sequential_ws_connections_both_receive_snapshot(
        self, app, client, execution_a, api_key_a
    ):
        """Two sequential WS connections to the same execution both receive
        the initial snapshot independently.
        """
        url = f"/api/v2/ws/executions/{execution_a.id}?token={api_key_a.plaintext}"

        with client.websocket_connect(url) as ws1:
            data1 = ws1.receive_json()
            assert data1["type"] == "snapshot"
            assert data1["status"] == execution_a.status

        with client.websocket_connect(url) as ws2:
            data2 = ws2.receive_json()
            assert data2["type"] == "snapshot"
            assert data2["status"] == execution_a.status
