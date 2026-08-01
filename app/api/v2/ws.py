"""WebSocket endpoints for real-time execution monitoring."""

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import DBSession
from app.models import ModelExecution, Organization, User
from app.services.auth import principal_from_jwt, resolve_principal

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


def _authenticate_websocket(
    db: Session, websocket: WebSocket, token: str | None
) -> tuple[User, Organization] | None:
    """Authenticate a WebSocket connection with the same credentials as the HTTP API.

    Accepts the browser session's JWT **access** cookie (``jaot_access_token``,
    sent automatically on the handshake) **or** a Bearer **API key** supplied via
    the ``?token=`` query param / Authorization header. Browsers cannot set custom
    headers on a WebSocket, so SPA clients pass their session token as a query
    param; that token is therefore also tried as a JWT access token (same principal
    the cookie path would yield — only the transport differs). No credential is
    accepted here that the HTTP API would reject, and ``last_used_at`` is not
    committed on this path (leaves the request session untouched).

    Returns ``(user, organization)`` on success, ``None`` otherwise.
    """
    jwt_cookie = websocket.cookies.get("jaot_access_token")
    if token:
        authorization: str | None = f"Bearer {token}"
    else:
        authorization = websocket.headers.get("authorization")

    user, organization, _api_key = resolve_principal(
        db,
        jwt_cookie=jwt_cookie,
        authorization=authorization,
        commit_last_used=False,
    )
    # The SPA stores its session token under one key and passes it as the query
    # param; if it is a JWT access token (not an API key), accept it the same way
    # the cookie path would.
    if user is None and token:
        hit = principal_from_jwt(db, token)
        if hit is not None:
            user, organization = hit

    if user is None or organization is None:
        return None
    return user, organization


def _ws_origins(allowed_origins: list[str], frontend_url: str) -> list[str]:
    """Origins allowed to open a progress socket.

    ALLOWED_ORIGINS plus the origin of FRONTEND_URL, which is where this very
    app is served from: a deployment whose own interface cannot open the socket
    is a misconfiguration, and it fails silently — the handshake is refused
    before the upgrade, so the browser sees a bare 403 and the panel quietly
    falls back to polling while the UI still promises live progress.
    """
    origins = list(allowed_origins)
    if frontend_url:
        parsed = urlparse(frontend_url)
        if parsed.scheme and parsed.netloc:
            own = f"{parsed.scheme}://{parsed.netloc}"
            if own not in origins:
                origins.append(own)
    return origins


class _Refused(Exception):  # noqa: N818 — this is a close code, not an error condition
    """The handshake decided not to accept this socket. Carries the close frame."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _snapshot(execution_id: str, execution: ModelExecution) -> dict[str, Any]:
    """The opening message: where this execution stands right now."""
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
    if execution.solver_status:
        snapshot["solver_status"] = execution.solver_status
    return snapshot


def _handshake(
    db: Session, websocket: WebSocket, token: str | None, execution_id: str
) -> tuple[str, dict[str, Any]]:
    """Authenticate, check ownership and read the opening snapshot, in one hop.

    Every database call the handshake makes lives here so the caller can run the
    whole thing off the event loop: these are blocking psycopg calls, and inline
    they stalled the loop for every other connection while they ran.

    Returns ``(execution primary key, snapshot)``; raises :class:`_Refused`.
    """
    auth_result = _authenticate_websocket(db, websocket, token)
    if auth_result is None:
        raise _Refused(4001, "Authentication required")
    _user, organization = auth_result

    execution = db.query(ModelExecution).filter(ModelExecution.id == execution_id).first()
    if not execution:
        # Try finding by celery task ID
        execution = (
            db.query(ModelExecution).filter(ModelExecution.celery_task_id == execution_id).first()
        )
    if not execution:
        raise _Refused(4004, "Execution not found")
    if execution.organization_id != organization.id:
        raise _Refused(4003, "Access denied")

    return execution.id, _snapshot(execution_id, execution)


def _read_progress(execution_pk: str) -> dict[str, Any] | None:
    """One poll of the row this socket watches. Its own session, opened and closed.

    The request-scoped session is handed back to the pool before the loop starts:
    a socket lives as long as the solve it watches, and ``db.refresh`` every five
    seconds without a commit also kept a transaction open the whole time. Ten
    spectators of one long solve were enough to exhaust a thirty-connection pool
    with Postgres otherwise idle. Read here, close here — the connection is held
    for the milliseconds of the SELECT and nothing else.

    ``None`` means the row is gone; the caller closes the socket.
    """
    # Resolved at call time, like the health probes do: the test harness swaps
    # `SessionLocal` on the module, and a name bound at import would keep
    # pointing at the production engine.
    from app.shared.db.session import SessionLocal  # noqa: PLC0415

    db = SessionLocal()
    try:
        row = (
            db.query(
                ModelExecution.status,
                ModelExecution.progress_data,
                ModelExecution.result_data,
                ModelExecution.error_message,
            )
            .filter(ModelExecution.id == execution_pk)
            .first()
        )
        if row is None:
            return None
        return {
            "status": row.status,
            "progress_data": row.progress_data,
            "result_data": row.result_data,
            "error_message": row.error_message,
        }
    finally:
        db.close()


@router.websocket("/executions/{execution_id}")
async def websocket_execution_progress(
    websocket: WebSocket,
    execution_id: str,
    db: DBSession,
    token: str | None = Query(None),
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
    allowed_origins = _ws_origins(_ws_settings.ALLOWED_ORIGINS, _ws_settings.FRONTEND_URL)
    if allowed_origins and origin and origin not in allowed_origins:
        # Closing before accept() means the browser only ever sees "403" with no
        # reason, so the log line is the only place the cause is legible.
        logger.warning(
            "WebSocket origin rejected: %s (allowed: %s)", origin, ", ".join(allowed_origins)
        )
        await websocket.close(code=4003, reason="Origin not allowed")
        return

    # --- Authentication, ownership and opening snapshot ---
    # Same credentials as the HTTP API: JWT access cookie (auto-sent on the
    # handshake) or a Bearer API key passed via ?token= / Authorization header.
    # Off the event loop, and then the connection goes back to the pool: what
    # follows can run for as long as the solve does, and must not sit on one.
    try:
        execution_pk, snapshot = await run_in_threadpool(
            _handshake, db, websocket, token, execution_id
        )
    except _Refused as refused:
        await websocket.close(code=refused.code, reason=refused.reason)
        return
    finally:
        db.close()

    # --- Connection accepted ---
    await manager.connect(websocket, execution_id)

    try:
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
                state = await run_in_threadpool(_read_progress, execution_pk)
                if state is None:
                    break  # The row is gone; there is nothing left to report.

                status = state["status"]
                if status in ("completed", "failed", "cancelled"):
                    await websocket.send_json(
                        {
                            "type": status,
                            "execution_id": execution_id,
                            "status": status,
                            "result": (state["result_data"] if status == "completed" else None),
                            "error": (state["error_message"] if status == "failed" else None),
                        }
                    )
                    break
                if state["progress_data"]:
                    await websocket.send_json(
                        {
                            "type": "progress",
                            "execution_id": execution_id,
                            **state["progress_data"],
                        }
                    )

    except WebSocketDisconnect:
        logger.info(f"Client disconnected from execution {execution_id}")
    except Exception as e:
        logger.error(f"WebSocket error for execution {execution_id}: {e}")
    finally:
        manager.disconnect(websocket, execution_id)


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
