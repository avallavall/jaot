"""WebSocket endpoints for real-time execution monitoring."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.models import ModelExecution
from app.shared.db.base import get_db

router = APIRouter(prefix="/ws", tags=["websocket"])
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for execution monitoring."""

    def __init__(self) -> None:
        # Map of execution_id -> list of websocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, execution_id: str) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        if execution_id not in self.active_connections:
            self.active_connections[execution_id] = []
        self.active_connections[execution_id].append(websocket)
        logger.info(f"WebSocket connected for execution {execution_id}")

    def disconnect(self, websocket: WebSocket, execution_id: str) -> None:
        """Remove a WebSocket connection."""
        if execution_id in self.active_connections:
            if websocket in self.active_connections[execution_id]:
                self.active_connections[execution_id].remove(websocket)
            if not self.active_connections[execution_id]:
                del self.active_connections[execution_id]
        logger.info(f"WebSocket disconnected for execution {execution_id}")

    async def broadcast_progress(self, execution_id: str, data: dict[str, Any]) -> None:
        """Send progress update to all connections for an execution."""
        if execution_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[execution_id]:
                try:
                    await connection.send_json(data)
                except Exception:
                    logger.debug(
                        "WebSocket send failed, marking connection for cleanup", exc_info=True
                    )
                    disconnected.append(connection)

            # Clean up disconnected
            for conn in disconnected:
                self.disconnect(conn, execution_id)


# Global connection manager
manager = ConnectionManager()

# Background task handle for Redis subscriber
_redis_listener_task: asyncio.Task[Any] | None = None


async def setup_redis_listener() -> None:
    """Start the Redis pub/sub listener as a background asyncio task.

    Called from FastAPI lifespan on startup. Subscribes to ``ws:execution:*``
    channels and forwards messages to the ConnectionManager. Falls back
    gracefully if Redis is unavailable (polling still works).
    """
    global _redis_listener_task
    if _redis_listener_task is not None:
        return  # Already running

    _redis_listener_task = asyncio.create_task(_redis_subscriber_loop())
    logger.info("Redis WebSocket subscriber started")


async def _redis_subscriber_loop() -> None:
    """Long-running loop that subscribes to Redis and pushes to WebSocket clients."""
    while True:
        try:
            import redis.asyncio as aioredis

            from app.config import settings

            redis_url = settings.REDIS_URL
            if not redis_url:
                logger.info("REDIS_URL not set -- WebSocket Redis subscriber disabled")
                return

            # socket_timeout=None: pub/sub reads MUST block — an idle subscription
            # is normal, not a failure. We poll with a per-message timeout below
            # instead, so an idle period never tears down the subscription.
            client = aioredis.from_url(redis_url, socket_timeout=None, socket_keepalive=True)
            pubsub = client.pubsub()
            await pubsub.psubscribe("ws:execution:*")
            logger.info("Redis subscriber connected, listening on ws:execution:*")

            # Poll instead of `listen()`: get_message returns None on an idle
            # timeout (keep the subscription alive, no log spam, no dropped
            # messages); we only fall through to the outer reconnect on a real
            # connection error.
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30.0)
                if message is None:
                    continue
                if message.get("type") != "pmessage":
                    continue
                try:
                    # Channel is bytes: b"ws:execution:{execution_id}"
                    channel = (
                        message["channel"].decode()
                        if isinstance(message["channel"], bytes)
                        else message["channel"]
                    )
                    execution_id = channel.split(":", 2)[2]  # ws:execution:<id>
                    data_raw = (
                        message["data"].decode()
                        if isinstance(message["data"], bytes)
                        else message["data"]
                    )
                    data = json.loads(data_raw)
                    await manager.broadcast_progress(execution_id, data)
                except Exception as e:
                    logger.debug(f"Error processing Redis message: {e}")

        except Exception as e:
            logger.warning(f"Redis subscriber error (reconnecting in 5s): {e}")
            await asyncio.sleep(5)


def _authenticate_websocket(db: Session, token: str | None) -> Any:
    """Authenticate a WebSocket connection via API key token.

    Returns:
        Tuple of (api_key, user, organization) if valid, None otherwise.
    """
    if not token:
        return None
    from app.services.auth.api_key_service import APIKeyService

    return APIKeyService.verify_key(db, token)


@router.websocket("/executions/{execution_id}")
async def websocket_execution_progress(
    websocket: WebSocket,
    execution_id: str,
    token: str | None = Query(None),
    db: Session = Depends(get_db),
) -> None:
    """
    WebSocket endpoint for real-time execution progress.

    Requires authentication via `token` query parameter (API key).
    The caller must own the execution (same organization).

    Connect to receive progress updates for a specific execution.
    Messages are JSON with format:
    {
        "type": "progress" | "completed" | "failed" | "snapshot",
        "progress": 0.0-1.0,
        "status": "pending" | "running" | "completed" | "failed",
        "message": "...",
        "iteration": 123,
        "objective_value": 1234.56,
        "gap": 0.01,
        "timestamp": "2024-01-01T12:00:00Z",
        "metrics": {"gap": 0.05, "bound": 123.4, "incumbent": 130.0}
    }
    """
    # --- Origin validation ---
    from app.config import settings as _ws_settings

    origin = websocket.headers.get("origin")
    allowed_origins = _ws_settings.ALLOWED_ORIGINS
    if allowed_origins and origin and origin not in allowed_origins:
        logger.warning(f"WebSocket origin rejected: {origin}")
        await websocket.close(code=4003, reason="Origin not allowed")
        return

    # --- Authentication ---
    # Also check Authorization header as fallback
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    auth_result = _authenticate_websocket(db, token)
    if auth_result is None:
        await websocket.close(code=4001, reason="Authentication required")
        return
    _api_key, _user, organization = auth_result

    # --- Ownership check ---
    execution = db.query(ModelExecution).filter(ModelExecution.id == execution_id).first()

    if not execution:
        # Try finding by celery task ID
        execution = (
            db.query(ModelExecution).filter(ModelExecution.celery_task_id == execution_id).first()
        )

    if not execution:
        await websocket.close(code=4004, reason="Execution not found")
        return

    if execution.organization_id != organization.id:
        await websocket.close(code=4003, reason="Access denied")
        return

    # --- Connection accepted ---
    await manager.connect(websocket, execution_id)

    try:
        snapshot: dict[str, Any] = {
            "type": "snapshot",
            "execution_id": execution_id,
            "status": execution.status,
            "progress_data": execution.progress_data,
        }
        if execution.status == "completed" and execution.result_data:
            snapshot["result"] = execution.result_data
            snapshot["objective_value"] = execution.objective_value
        elif execution.status == "failed":
            snapshot["error"] = execution.error_message
        if execution.objective_value is not None:
            snapshot["objective_value"] = execution.objective_value
        if hasattr(execution, "solver_status") and execution.solver_status:
            snapshot["solver_status"] = execution.solver_status

        await websocket.send_json(snapshot)

        # Keep connection alive and poll for updates (fallback when Redis unavailable)
        while True:
            try:
                # Wait for client message or timeout
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=5.0,
                )

                # Handle ping/pong
                if data == "ping":
                    await websocket.send_text("pong")

            except asyncio.TimeoutError:
                # Poll database for updates
                db.refresh(execution)

                if execution.status in ("completed", "failed", "cancelled"):
                    await websocket.send_json(
                        {
                            "type": execution.status,
                            "execution_id": execution_id,
                            "status": execution.status,
                            "result": (
                                execution.result_data if execution.status == "completed" else None
                            ),
                            "error": (
                                execution.error_message if execution.status == "failed" else None
                            ),
                        }
                    )
                    break
                elif execution.progress_data:
                    await websocket.send_json(
                        {
                            "type": "progress",
                            "execution_id": execution_id,
                            **execution.progress_data,
                        }
                    )

    except WebSocketDisconnect:
        logger.info(f"Client disconnected from execution {execution_id}")
    except Exception as e:
        logger.error(f"WebSocket error for execution {execution_id}: {e}")
    finally:
        manager.disconnect(websocket, execution_id)


async def notify_execution_progress(execution_id: str, progress_data: dict[str, Any]) -> None:
    """
    Utility function to notify all connected clients of progress.
    Called from Celery tasks via Redis pub/sub or direct call.
    """
    await manager.broadcast_progress(
        execution_id,
        {
            "type": "progress",
            "execution_id": execution_id,
            **progress_data,
        },
    )


async def notify_execution_complete(execution_id: str, result: dict[str, Any]) -> None:
    """Notify all connected clients that execution is complete."""
    await manager.broadcast_progress(
        execution_id,
        {
            "type": "completed",
            "execution_id": execution_id,
            "result": result,
        },
    )


async def notify_execution_failed(execution_id: str, error: str) -> None:
    """Notify all connected clients that execution failed."""
    await manager.broadcast_progress(
        execution_id,
        {
            "type": "failed",
            "execution_id": execution_id,
            "error": error,
        },
    )
