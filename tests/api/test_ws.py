"""Tests for WebSocket module.

Tests the ConnectionManager and WebSocket utility functions.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v2.ws import (
    ConnectionManager,
    notify_execution_complete,
    notify_execution_failed,
    notify_execution_progress,
)


class TestConnectionManager:
    """Tests for ConnectionManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ConnectionManager for each test."""
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket."""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect_new_execution(self, manager, mock_websocket):
        """Test connecting to a new execution ID."""
        await manager.connect(mock_websocket, "exec-123")

        mock_websocket.accept.assert_called_once()
        assert "exec-123" in manager.active_connections
        assert mock_websocket in manager.active_connections["exec-123"]

    @pytest.mark.asyncio
    async def test_connect_existing_execution(self, manager, mock_websocket):
        """Test connecting multiple clients to same execution."""
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        await manager.connect(mock_websocket, "exec-123")
        await manager.connect(ws2, "exec-123")

        assert len(manager.active_connections["exec-123"]) == 2

    def test_disconnect_removes_connection(self, manager, mock_websocket):
        """Test disconnecting removes the websocket."""
        manager.active_connections["exec-123"] = [mock_websocket]

        manager.disconnect(mock_websocket, "exec-123")

        assert "exec-123" not in manager.active_connections

    def test_disconnect_keeps_other_connections(self, manager, mock_websocket):
        """Test disconnecting one client keeps others."""
        ws2 = MagicMock()
        manager.active_connections["exec-123"] = [mock_websocket, ws2]

        manager.disconnect(mock_websocket, "exec-123")

        assert "exec-123" in manager.active_connections
        assert ws2 in manager.active_connections["exec-123"]
        assert mock_websocket not in manager.active_connections["exec-123"]

    def test_disconnect_nonexistent_execution(self, manager, mock_websocket):
        """Test disconnecting from non-existent execution doesn't error."""
        manager.disconnect(mock_websocket, "nonexistent")
        # Should not raise

    @pytest.mark.asyncio
    async def test_broadcast_progress(self, manager, mock_websocket):
        """Test broadcasting progress to connected clients."""
        manager.active_connections["exec-123"] = [mock_websocket]

        await manager.broadcast_progress("exec-123", {"progress": 0.5})

        mock_websocket.send_json.assert_called_once_with({"progress": 0.5})

    @pytest.mark.asyncio
    async def test_broadcast_progress_no_connections(self, manager):
        """Test broadcasting to execution with no connections."""
        await manager.broadcast_progress("nonexistent", {"progress": 0.5})
        # Should not raise

    @pytest.mark.asyncio
    async def test_broadcast_handles_disconnected_client(self, manager):
        """Test broadcast removes clients that fail to receive."""
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = Exception("Connection closed")

        manager.active_connections["exec-123"] = [ws_good, ws_bad]

        await manager.broadcast_progress("exec-123", {"progress": 0.5})

        # Good client should receive
        ws_good.send_json.assert_called_once()
        # Bad client should be removed
        assert ws_bad not in manager.active_connections.get("exec-123", [])


class TestNotifyFunctions:
    """Tests for notification utility functions."""

    @pytest.mark.asyncio
    async def test_notify_execution_progress(self):
        """Test notify_execution_progress sends correct data."""
        with patch("app.api.v2.ws.manager") as mock_manager:
            mock_manager.broadcast_progress = AsyncMock()

            await notify_execution_progress("exec-123", {"status": "running", "progress": 0.5})

            mock_manager.broadcast_progress.assert_called_once()
            call_args = mock_manager.broadcast_progress.call_args
            assert call_args[0][0] == "exec-123"
            assert call_args[0][1]["type"] == "progress"
            assert call_args[0][1]["execution_id"] == "exec-123"

    @pytest.mark.asyncio
    async def test_notify_execution_complete(self):
        """Test notify_execution_complete sends correct data."""
        with patch("app.api.v2.ws.manager") as mock_manager:
            mock_manager.broadcast_progress = AsyncMock()

            result = {"objective_value": 100.0}
            await notify_execution_complete("exec-123", result)

            mock_manager.broadcast_progress.assert_called_once()
            call_args = mock_manager.broadcast_progress.call_args
            assert call_args[0][1]["type"] == "completed"
            assert call_args[0][1]["result"] == result

    @pytest.mark.asyncio
    async def test_notify_execution_failed(self):
        """Test notify_execution_failed sends correct data."""
        with patch("app.api.v2.ws.manager") as mock_manager:
            mock_manager.broadcast_progress = AsyncMock()

            await notify_execution_failed("exec-123", "Solver timeout")

            mock_manager.broadcast_progress.assert_called_once()
            call_args = mock_manager.broadcast_progress.call_args
            assert call_args[0][1]["type"] == "failed"
            assert call_args[0][1]["error"] == "Solver timeout"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
