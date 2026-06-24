"""Pure ASGI authentication middleware.

Supports dual authentication:
1. JWT cookie (browser sessions) - checked first
2. Bearer API key (SDK/API access) - fallback

Public endpoints are matched via explicit allowlist only (no substring matching).
"""

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models import Organization, User
from app.services.auth import APIKeyService, JWTService
from app.shared.core.rate_limiter import check_rate_limit
from app.shared.db.session import SessionLocal
from app.shared.utils.request_helpers import (
    get_client_ip_from_scope,
    is_trusted_internal_request,
)

logger = logging.getLogger(__name__)

# Module-level session factory, overridable for tests.
# In production this is SessionLocal. Tests swap it to a factory that creates
# Sessions bound to the test connection (same transaction, separate Session object).
_session_factory = SessionLocal


# Public endpoints that do not require authentication.
# Each entry is (path_prefix, method_or_None).
# method=None means all HTTP methods are allowed.
# method="GET" means only GET requests are public.
# Paths use prefix matching: /api/v2/auth/login matches /api/v2/auth/login
# and also /api/v2/auth/login/ (trailing slash).
PUBLIC_PATHS: list[tuple[str, str | None]] = [
    # Infrastructure
    ("/docs", None),
    ("/redoc", None),
    ("/openapi.json", None),
    ("/.well-known/", None),
    ("/mcp", None),
    ("/metrics", None),
    # Auth endpoints (all methods)
    ("/api/v2/health", None),
    ("/api/v2/auth/signup", None),
    ("/api/v2/auth/login", None),
    ("/api/v2/auth/verify-email", None),
    ("/api/v2/auth/forgot-password", None),
    ("/api/v2/auth/reset-password", None),
    ("/api/v2/auth/refresh", None),
    ("/api/v2/auth/logout", None),
    # Public data endpoints
    ("/api/v2/solve/templates", "GET"),
    ("/api/v2/solve/validate", "POST"),
    ("/api/v2/contact", "POST"),
    ("/api/v2/billing/webhook", "POST"),
    ("/api/v2/credits/calculator", None),
    ("/api/v2/credits/rates", "GET"),
    ("/api/v2/community/status", None),
    # Catalog browsing (public, read-only)
    ("/api/v2/models/catalog", "GET"),
    # Public pricing data
    ("/api/v2/pricing", "GET"),
    # Public home page announcement banner
    ("/api/v2/home/announcement", "GET"),
]

# Dynamic public paths: routes with path parameters.
# Each entry is (prefix, method, allowed_suffixes_or_None).
# When allowed_suffixes is a set, the path after the prefix must end with one of them.
# When allowed_suffixes is None, all sub-paths are public (use sparingly).
PUBLIC_DYNAMIC_PATHS: list[tuple[str, str | None, set[str] | None]] = [
    # Profile endpoints: only /public, /reviews, and by-slug lookups
    ("/api/v2/users/", "GET", {"/public", "/reviews", "/by-slug/"}),
    ("/api/v2/organizations/", "GET", {"/public", "/by-slug/", "/models"}),
]

# Trigger fire endpoint: /api/v2/triggers/{id}/fire (POST)
# This is the only route that was previously matched via endswith("/fire").
# It uses per-trigger secret authentication (not org API key), so the
# middleware must let it through. Matched explicitly by path suffix.
_TRIGGER_FIRE_PREFIX = "/api/v2/triggers/"
_TRIGGER_FIRE_SUFFIX = "/fire"


def _is_public(path: str, method: str) -> bool:
    """Check if a request path+method combination is public.

    Uses explicit prefix matching only. No substring or endswith matching.
    """
    if path == "/" or path == "":
        return True

    for public_path, public_method in PUBLIC_PATHS:
        if path.startswith(public_path):
            if public_method is None or method == public_method:
                return True

    for public_path, public_method, allowed_suffixes in PUBLIC_DYNAMIC_PATHS:
        if path.startswith(public_path):
            if public_method is None or method == public_method:
                if allowed_suffixes is None:
                    return True
                remainder = path[len(public_path) - 1 :]  # keep leading /
                if any(suffix in remainder for suffix in allowed_suffixes):
                    return True

    # Trigger fire: POST /api/v2/triggers/{id}/fire
    if (
        method == "POST"
        and path.startswith(_TRIGGER_FIRE_PREFIX)
        and path.endswith(_TRIGGER_FIRE_SUFFIX)
        and path.count("/") == 5  # exactly: /api/v2/triggers/{id}/fire
    ):
        return True

    return False


class ASGIAuthMiddleware:
    """Pure ASGI middleware for authentication.

    Does not inherit from BaseHTTPMiddleware -- compatible with
    streaming responses (SSE) and does not spawn threads per request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Extract path and method
        path: str = scope.get("path", "/")
        method: str = scope.get("method", "GET")

        # Allow CORS preflight
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # WebSocket connections handle their own authentication at the
        # endpoint level (see app/api/v2/ws.py _authenticate_websocket).
        # starlette.requests.Request asserts scope["type"] == "http", so
        # we must not construct a Request for websocket scopes.
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        if _is_public(path, method):
            # Apply permissive rate limit to public API endpoints — but NOT to
            # trusted internal service traffic. The frontend's SSR fetches all
            # egress from one container IP, so rate-limiting them per-IP shares a
            # single 60/min bucket across every visitor: a burst (crawler,
            # Lighthouse, fast browsing) trips a 429 that surfaces as an SSR 500.
            # Internal traffic is identified structurally (no proxy header +
            # private source IP); see is_trusted_internal_request for the
            # security invariant. External clients always arrive via Caddy with
            # an X-Forwarded-For and remain rate-limited.
            if path.startswith("/api/v2/") and not is_trusted_internal_request(scope):
                client_ip = get_client_ip_from_scope(scope)
                allowed, rate_info = check_rate_limit(
                    f"public_ip:{client_ip}",
                    limit_per_minute=60,
                    limit_per_day=5000,
                )
                if not allowed:
                    response = JSONResponse(status_code=429, content=rate_info)
                    await response(scope, receive, send)
                    return

            # Phase 9 (D-06): opportunistic non-fatal authentication on PUBLIC_PATHS.
            # Required so /api/v2/contact (and any future public-yet-session-aware
            # endpoint) can auto-tag rows with user_id/organization_id when a session
            # is present. NEVER raises 401 — that contract belongs to authenticated
            # routes only. Reuses the same _authenticate() path as protected routes
            # so a forged JWT / expired token / deleted user fails silently the same
            # way it would on a protected route (Pitfall T-09-07).
            request = Request(scope, receive)
            has_credential = bool(
                request.cookies.get("jaot_access_token") or request.headers.get("Authorization")
            )
            if has_credential:
                db = _session_factory()
                try:
                    user, org, api_key = await self._authenticate(request, db)
                    if user is not None and org is not None:
                        scope.setdefault("state", {})
                        scope["state"]["user"] = user
                        scope["state"]["organization"] = org
                        scope["state"]["api_key"] = api_key
                except Exception:
                    # Swallow EVERY exception (HTTPException, expired JWT,
                    # forged token, deleted-user lookup, DB hiccup). Request
                    # continues anonymously — request.state stays untouched
                    # and OptionalCurrentUser returns None. We deliberately
                    # do NOT log here: public paths are visited by spam
                    # scanners hourly and noise would drown signal.
                    pass
                finally:
                    try:
                        db.rollback()
                    except Exception:
                        logger.debug("Auth middleware rollback failed", exc_info=True)
                    db.close()

            await self.app(scope, receive, send)
            return

        # Authenticate
        request = Request(scope, receive)
        db = _session_factory()
        try:
            user, org, api_key = await self._authenticate(request, db)
            if user is None or org is None:
                response = JSONResponse(
                    status_code=401,
                    content={"error": "unauthorized", "message": "Authentication required"},
                )
                await response(scope, receive, send)
                return

            # Attach to request state
            scope.setdefault("state", {})
            scope["state"]["user"] = user
            scope["state"]["organization"] = org
            scope["state"]["api_key"] = api_key

            # Wrap send to inject response headers
            async def send_with_headers(message: Message) -> None:
                if message["type"] == "http.response.start":
                    extra_headers = [
                        (b"x-organization-id", org.id.encode()),
                        (b"x-credits-balance", str(org.credits_balance).encode()),
                    ]
                    existing = list(message.get("headers", []))
                    existing.extend(extra_headers)
                    message = {**message, "headers": existing}
                await send(message)

            await self.app(scope, receive, send_with_headers)

        except Exception as e:
            logger.error(
                "Auth middleware error on %s %s: %s (%s)",
                method,
                path,
                e,
                type(e).__name__,
                exc_info=True,
            )
            if (
                "operational" in str(type(e).__name__).lower()
                or "dbapi" in str(type(e).__name__).lower()
            ):
                response = JSONResponse(
                    status_code=503,
                    content={
                        "error": "service_unavailable",
                        "message": "Database temporarily unavailable",
                    },
                )
            else:
                response = JSONResponse(
                    status_code=500,
                    content={"error": "internal_error", "message": "Authentication service error"},
                )
            await response(scope, receive, send)
        finally:
            # Explicitly rollback any open transaction before closing.
            # Without this, the underlying connection may go back to the pool
            # in "idle in transaction" state, holding AccessShareLock on tables
            # and blocking TRUNCATE cleanup in tests.
            try:
                db.rollback()
            except Exception:
                logger.debug("Auth middleware rollback failed", exc_info=True)
            db.close()

    async def _authenticate(
        self, request: Request, db: Any
    ) -> tuple[User | None, Organization | None, Any]:
        """Try JWT cookie first, then Bearer API key."""

        # Path 1: JWT cookie
        jwt_token = request.cookies.get("jaot_access_token")
        if jwt_token:
            try:
                payload = JWTService.decode_token(jwt_token)
                if payload.get("type") == "access":
                    user = db.query(User).filter(User.id == payload["sub"]).first()
                    if user:
                        org = (
                            db.query(Organization).filter(Organization.id == payload["org"]).first()
                        )
                        if org:
                            return user, org, None
            except Exception as jwt_err:
                logger.debug(
                    "JWT cookie auth failed (%s), trying API key",
                    type(jwt_err).__name__,
                )

        # Path 2: Bearer API key
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None, None, None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None, None, None

        api_key = parts[1]
        result = APIKeyService.verify_key(db, api_key)
        if not result:
            return None, None, None

        api_key_model, user, organization = result
        try:
            db.commit()  # Commit last_used_at update
        except Exception:
            # Non-critical: last_used_at update may fail in tests due to
            # concurrent TRUNCATE. Don't block authentication for this.
            db.rollback()
        return user, organization, api_key_model
