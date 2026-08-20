"""Shared credential resolution.

The single source of truth for turning a presented credential into
``(user, organization)`` — used by the HTTP path (``ASGIAuthMiddleware``) and the
WebSocket path (``app/api/v2/ws.py``) so both accept *exactly* the same set of
principals: a JWT **access** cookie (``jaot_access_token``) or a Bearer **API key**.

Factoring this out keeps the auth logic in one place (was previously duplicated in
the middleware) and lets the live-progress WebSocket authenticate the same browser
session the rest of the API does, without re-implementing token parsing.
"""

import logging
from typing import Any

from app.models import Organization, User
from app.services.auth.api_key_service import APIKeyService
from app.services.auth.jwt_service import JWTService

logger = logging.getLogger(__name__)


def principal_from_jwt(db: Any, token: str | None) -> tuple[User, Organization] | None:
    """Resolve ``(user, organization)`` from a JWT **access** token, or ``None``.

    Mirrors the middleware's cookie path exactly: the token must decode, be of
    type ``access``, and reference a live user + organization. Never raises — a
    forged/expired/garbage token returns ``None``.
    """
    if not token:
        return None
    try:
        payload = JWTService.decode_token(token)
    except Exception as exc:  # forged / expired / malformed
        logger.debug("JWT auth failed (%s)", type(exc).__name__)
        return None
    if payload.get("type") != "access":
        return None
    user = db.query(User).filter(User.id == payload.get("sub")).first()
    if not user:
        return None
    org = db.query(Organization).filter(Organization.id == payload.get("org")).first()
    if not org:
        return None
    # "Live" is what the docstring above always promised, and only the API-key
    # path checked it. A browser session outlived both switches: an admin who
    # deactivated an organization, or deleted a user (which is a soft delete),
    # cut off that account's API keys and nothing else — the person kept
    # reading, kept creating models and could sign in again.
    if not user.is_active or not org.is_active:
        return None
    return user, org


def resolve_principal(
    db: Any,
    *,
    jwt_cookie: str | None = None,
    authorization: str | None = None,
    commit_last_used: bool = True,
) -> tuple[User | None, Organization | None, Any]:
    """Resolve ``(user, organization, api_key)`` exactly as the HTTP API does.

    JWT access cookie first (browser sessions), then a Bearer API key
    (SDK/API access). Returns ``(None, None, None)`` when neither authenticates.

    ``commit_last_used`` controls whether the API-key ``last_used_at`` bump is
    committed (the WebSocket path passes ``False`` to leave the request session
    untouched, matching its previous behaviour).
    """
    # Path 1: JWT access cookie.
    hit = principal_from_jwt(db, jwt_cookie)
    if hit is not None:
        return hit[0], hit[1], None

    # Path 2: Bearer API key.
    if not authorization:
        return None, None, None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None, None, None

    result = APIKeyService.verify_key(db, parts[1])
    if not result:
        return None, None, None

    api_key_model, user, organization = result
    if commit_last_used:
        try:
            db.commit()  # persist last_used_at
        except Exception:
            # Non-critical (e.g. concurrent TRUNCATE in tests) — never block auth.
            db.rollback()
    return user, organization, api_key_model
