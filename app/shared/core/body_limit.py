"""Pure ASGI middleware that rejects request bodies exceeding a size limit.

Returns 413 Payload Too Large if Content-Length exceeds the limit or if the
streamed body grows past the limit.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 1 MB default — matches deferred-items.md recommendation
MAX_BODY_BYTES = 1_048_576

# Paths that handle their own size limits (e.g., file upload endpoints)
EXEMPT_PREFIXES = ("/api/v2/solve/import",)

# Upload routes with a dynamic path segment are exempt when BOTH prefix and
# suffix match. LLM document attachments enforce their own 10 MB cap
# (app/api/v2/llm.py MAX_FILE_SIZE) — without this exemption the global 1 MB
# limit silently rejects any real-world PDF.
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

        # Skip limit for exempt paths (they enforce their own limits)
        path = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in EXEMPT_PREFIXES) or any(
            path.startswith(prefix) and path.endswith(suffix)
            for prefix, suffix in EXEMPT_PREFIX_SUFFIX
        ):
            await self.app(scope, receive, send)
            return

        # Fast-path: check Content-Length header if present
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._send_413(send)
                    return
            except ValueError:
                pass

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
        body = b'{"detail":"Request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
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


class _BodyTooLarge(Exception):
    pass
