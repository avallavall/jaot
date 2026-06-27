"""Pure ASGI middleware that adds security response headers.

Adds OWASP-recommended security headers to all HTTP responses:
HSTS, X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy,
and Permissions-Policy.
"""

import base64
import secrets

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Inject security headers into every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        scope.setdefault("state", {})
        scope["state"]["csp_nonce"] = nonce

        is_api = scope.get("path", "").startswith("/api/")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Authenticated API responses must never be cached by the browser
                # or an upstream CDN (Cloudflare). Without this, a stale empty
                # response (e.g. an admin list fetched before data existed) keeps
                # being served from cache and the real request never reaches the
                # server. Endpoints that opt into caching (e.g. /api/v2/pricing
                # sets `public, max-age=...`) already emit their own
                # cache-control, so we only add the default when none is present.
                if is_api and not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", b"no-store"))
                csp = (
                    f"default-src 'self'; "
                    f"script-src 'self' 'nonce-{nonce}' https://js.stripe.com; "
                    f"style-src 'self' 'nonce-{nonce}' 'unsafe-inline'; "
                    f"img-src 'self' data: https:; "
                    f"connect-src 'self' https://api.stripe.com; "
                    f"frame-src https://js.stripe.com; "
                    f"font-src 'self'; "
                    f"frame-ancestors 'none'"
                )
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
                        (b"content-security-policy", csp.encode()),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
