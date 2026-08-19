"""Pure ASGI middleware that rejects request bodies exceeding a size limit.

Returns 413 Payload Too Large if Content-Length exceeds the limit or if the
streamed body grows past the limit.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.shared.core.upload_capacity import upload_refusal

# Self-hosted open source: the operator owns this, via MAX_REQUEST_BODY_MB in
# .env, and the default is NO limit. Real models are big — a 400x400 assignment
# model is ~30 MB of JSON, and there is no size at which we can honestly tell a
# self-hoster their model is "too large" for their own hardware. A public
# instance with open signup should set a real number.
# File imports (/solve/import) and LLM attachments are exempt and enforce their own.
MAX_BODY_BYTES = settings.MAX_REQUEST_BODY_MB * 1024 * 1024

# Paths that handle their own size limits (e.g., file upload endpoints)
EXEMPT_PREFIXES = ("/api/v2/solve/import",)

# Upload routes with a dynamic path segment are exempt when BOTH prefix and
# suffix match. LLM document attachments enforce their own 50 MB cap
# (app/services/document_extraction.py MAX_FILE_SIZE) — without this exemption
# the global body limit silently rejects any real-world PDF.
EXEMPT_PREFIX_SUFFIX = (("/api/v2/llm/conversations/", "/attachments"),)


class BodyLimitMiddleware:
    """Reject HTTP request bodies larger than MAX_BODY_BYTES."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        declared = _declared_length(scope)

        # An import carries no body limit — capacity limits are the operator's
        # to set (D-21) — but it still has to fit on the machine. Starlette
        # spools the upload to /tmp and the importer writes it there a second
        # time, so a file bigger than half the free tmpfs fills it. This runs
        # whatever the operator set, including their default of no limit at
        # all: it is not a policy, it is whether the disk has the room. Asked
        # here it costs the user nothing; asked after the upload it cost two
        # minutes and arrived as a sentence about the server's disk.
        if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES):
            refusal = None if declared is None else upload_refusal(declared)
            if refusal is not None:
                await self._send_json(send, 413, refusal)
                return
            await self.app(scope, receive, send)
            return

        if self.max_bytes <= 0 or any(
            path.startswith(prefix) and path.endswith(suffix)
            for prefix, suffix in EXEMPT_PREFIX_SUFFIX
        ):
            await self.app(scope, receive, send)
            return

        # Fast-path: check Content-Length header if present
        if declared is not None and declared > self.max_bytes:
            await self._send_413(send)
            return

        # Streaming guard: count bytes as they arrive
        bytes_received = 0

        async def limited_receive() -> Message:
            nonlocal bytes_received
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                bytes_received += len(body)
                if bytes_received > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._send_413(send)

    async def _send_413(self, send: Send) -> None:
        await self._send_json(send, 413, {"detail": "Request body too large"})

    async def _send_json(self, send: Send, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )


def _declared_length(scope: Scope) -> int | None:
    """The request's Content-Length, or None when it is absent or malformed."""
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class _BodyTooLarge(Exception):
    pass
