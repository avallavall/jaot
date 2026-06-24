"""Pure ASGI middleware that returns 503 during maintenance mode.

Admin users (identified by JWT cookie or Bearer token) bypass maintenance.
Health check, admin API, auth login, and metrics paths always pass through.
"""

import json
import logging

from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from app.shared.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Module-level session factory, overridable for tests.
# In production this is SessionLocal.  Tests swap it to a factory bound to
# the test engine so maintenance-mode checks don't open a separate connection
# that deadlocks with TRUNCATE cleanup.
_session_factory = SessionLocal

# Set True to skip maintenance checks entirely (e.g. in tests).
# Separate from _session_factory so the factory can still be swapped for
# integration tests that want to verify maintenance mode behavior.
_skip_maintenance_check = False
_force_maintenance: bool | None = None  # override for tests: True/False/None

# Paths that always bypass maintenance mode (prefix match).
_BYPASS_PREFIXES: list[str] = [
    "/api/v2/health",
    "/api/v2/admin",
    "/api/v2/auth/login",
    "/api/v2/auth/token/refresh",
    "/api/v2/auth/refresh",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/maintenance",
    "/_next/",
    "/favicon",
    "/robots.txt",
    "/sitemap",
]


class MaintenanceMiddleware:
    """Pure ASGI middleware that blocks non-admin traffic when maintenance is on.

    Resolution order for maintenance flag:
      1. DB ``platform_settings`` table (key ``MAINTENANCE_MODE``)
      2. Registry ``default_value`` fallback (``"false"``)

    Admin detection (checked in order):
      1. JWT cookie ``jaot_access_token`` with ``admin: true`` claim
      2. Bearer JWT in ``Authorization`` header with ``admin: true`` claim
      3. Bearer API key in ``Authorization`` header → DB user lookup
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        # Always bypass certain paths
        if any(path.startswith(p) for p in _BYPASS_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Skip maintenance checks when explicitly disabled (e.g. tests)
        if _skip_maintenance_check:
            await self.app(scope, receive, send)
            return

        from app.services.platform_settings_service import (
            PlatformSettingsService,
        )

        db = _session_factory()
        try:
            if _force_maintenance is not None:
                is_maintenance = _force_maintenance
            else:
                is_maintenance = PlatformSettingsService.get_bool(
                    db,
                    "MAINTENANCE_MODE",
                    default=False,
                )

            if not is_maintenance:
                await self.app(scope, receive, send)
                return

            # Maintenance is ON — check if the caller is an admin
            if self._is_admin_request(scope, db):
                await self.app(scope, receive, send)
                return
        except Exception as exc:
            # If DB is unreachable, let the request through so other
            # middleware can handle it (e.g. health check, error page).
            logger.warning("Maintenance check failed — allowing request: %s", exc)
            await self.app(scope, receive, send)
            return
        finally:
            # Rollback any pending changes (e.g. last_used_at from
            # API key verification) before returning to the pool.
            try:
                db.rollback()
            except Exception:
                pass
            db.close()

        # Non-admin during maintenance: redirect browsers, 503 for API
        if self._is_browser_request(scope):
            await self._send_maintenance_redirect(send)
        else:
            await self._send_maintenance_response(send)

    def _is_admin_request(self, scope: Scope, db: Session) -> bool:
        """Return True if the request carries valid admin credentials.

        Checks in order:
          1. JWT cookie ``jaot_access_token``
          2. Bearer JWT in Authorization header
          3. Bearer API key in Authorization header (DB lookup)
        """
        from app.config import settings

        # 1. JWT cookie
        cookie_token = self._extract_cookie(scope, "jaot_access_token")
        if cookie_token and self._jwt_is_admin(cookie_token, settings.jwt_secret_key):
            return True

        # 2-3. Bearer token (JWT or API key)
        bearer = self._extract_bearer_token(scope)
        if not bearer:
            return False

        # Try as JWT first (cheap, no DB)
        if self._jwt_is_admin(bearer, settings.jwt_secret_key):
            return True

        # Try as API key (requires DB lookup)
        return self._api_key_is_admin(bearer, db)

    @staticmethod
    def _jwt_is_admin(token: str, secret: str) -> bool:
        """Decode a JWT and return True if it has admin: true."""
        try:
            import jwt as pyjwt

            payload = pyjwt.decode(token, secret, algorithms=["HS256"])
            return bool(payload.get("admin", False))
        except Exception:
            return False

    @staticmethod
    def _api_key_is_admin(key: str, db: Session) -> bool:
        """Verify an API key and return True if its user is admin."""
        try:
            from app.services.auth import APIKeyService

            result = APIKeyService.verify_key(db, key)
            if result is None:
                return False
            _api_key_model, user, _org = result
            return bool(getattr(user, "is_admin", False))
        except Exception:
            logger.debug("API key admin check failed", exc_info=True)
            return False

    @staticmethod
    def _extract_cookie(scope: Scope, name: str) -> str | None:
        """Parse a named cookie from raw ASGI headers."""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                cookie_str = header_value.decode("latin-1")
                for part in cookie_str.split(";"):
                    part = part.strip()
                    if part.startswith(f"{name}="):
                        return part[len(name) + 1 :]
        return None

    @staticmethod
    def _extract_bearer_token(scope: Scope) -> str | None:
        """Extract Bearer token from the Authorization header."""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"authorization":
                value = header_value.decode("latin-1")
                parts = value.split(None, 1)
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    return parts[1]
        return None

    @staticmethod
    def _is_browser_request(scope: Scope) -> bool:
        """Return True if the request Accept header indicates a browser."""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"accept":
                accept = header_value.decode("latin-1")
                # Browser requests include text/html; API calls typically
                # send application/json or omit the header entirely.
                return "text/html" in accept
        return False

    @staticmethod
    async def _send_maintenance_redirect(send: Send) -> None:
        """Send a 302 redirect to the /maintenance page."""
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [
                    [b"location", b"/maintenance"],
                    [b"retry-after", b"300"],
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"",
            }
        )

    @staticmethod
    async def _send_maintenance_response(send: Send) -> None:
        """Send a 503 JSON response with Retry-After header."""
        body = json.dumps(
            {
                "detail": ("JAOT is currently under maintenance. Please try again shortly."),
                "status": "maintenance",
            }
        ).encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"retry-after", b"300"],
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
