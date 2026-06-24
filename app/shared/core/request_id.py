"""Pure ASGI middleware that assigns a request ID to every HTTP request.

The request ID is the support-facing correlation token that appears in:

* the ``X-Request-ID`` response header (echoed back to the client)
* ``request.state.request_id`` for downstream handlers
* ``scope["state"]["request_id"]`` so other ASGI middleware can access it
* every log record emitted during the request (via the standard
  ``extra={"request_id": ...}`` pattern)

If the client already sent an ``X-Request-ID`` header we trust and reuse
it — this lets a reverse proxy (Caddy) or an upstream service attach its
own trace id to the whole chain. Otherwise we mint a fresh prefixed id
so the value is distinguishable from UUIDs in logs.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.utils.id_generator import generate_id

# Maximum length accepted from an incoming ``X-Request-ID`` header. Clients
# that want to use their own id must keep it reasonable — anything larger
# is dropped and we generate a fresh one.
_MAX_CLIENT_ID_LEN = 128


class RequestIdMiddleware:
    """Attach a stable request id to every HTTP request and response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._resolve_request_id(scope)

        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Drop any pre-existing X-Request-ID header so we always
                # echo the canonical id we generated (or accepted) above.
                headers = [
                    (name, value) for name, value in headers if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_request_id)

    @staticmethod
    def _resolve_request_id(scope: Scope) -> str:
        """Honour an incoming ``X-Request-ID`` or mint a new one."""
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                try:
                    candidate: str = value.decode("ascii").strip()
                except UnicodeDecodeError:
                    continue
                if candidate and len(candidate) <= _MAX_CLIENT_ID_LEN:
                    # Keep only printable ASCII to prevent header injection
                    # or log-forging via control chars.
                    if candidate.isprintable():
                        return candidate
                break
        return generate_id("req_")
