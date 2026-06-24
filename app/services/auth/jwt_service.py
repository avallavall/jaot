"""JWT token service for access/refresh/verification/reset tokens."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)


class JWTService:
    """JWT access/refresh token creation and verification.

    All methods accept an optional ``db`` parameter.  When provided the
    runtime value stored in ``platform_settings`` is used (so admin changes
    take effect immediately).  When ``db`` is ``None`` the static config.py
    value is used -- this keeps backward compatibility for call sites that
    do not have a DB session (e.g. middleware token decode).
    """

    @staticmethod
    def _get_algorithm(db: Session | None = None) -> str:
        """Get the JWT algorithm.

        Reads from DB when *db* is provided, otherwise defaults to
        ``HS256``.
        """
        if db is not None:
            from app.services.platform_settings_service import (
                PlatformSettingsService as PSS,
            )

            val = PSS.get_str(db, "JWT_ALGORITHM")
            if val:
                return val
        return "HS256"

    @staticmethod
    def _get_secret(db: Session | None = None) -> str:
        """Get the JWT secret key.

        Reads from DB via PlatformSettingsService when *db* is provided,
        otherwise uses the cached ``settings.jwt_secret_key``.
        """
        if db is not None:
            from app.services.platform_settings_service import PlatformSettingsService as PSS

            val = PSS.get_str(db, "JWT_SECRET")
            if val:
                return val
        return settings.jwt_secret_key

    @staticmethod
    def create_access_token(
        user_id: str,
        org_id: str,
        is_admin: bool = False,
        db: Session | None = None,
    ) -> str:
        """Create a short-lived access token.

        Args:
            user_id: User ID (``sub`` claim).
            org_id: Organization ID (``org`` claim).
            is_admin: Whether the user is an admin (``admin`` claim).
            db: Optional DB session for runtime settings.

        Returns:
            Encoded JWT string.
        """
        if db is not None:
            from app.services.platform_settings_service import (
                PlatformSettingsService as PSS,
            )

            expire_minutes = PSS.get_int(db, "JWT_ACCESS_TOKEN_EXPIRE_MINUTES")
        else:
            expire_minutes = 30  # safe default when no db

        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "org": org_id,
            "admin": is_admin,
            "type": "access",
            "exp": now + timedelta(minutes=expire_minutes),
            "iat": now,
        }
        algo = JWTService._get_algorithm(db)
        return jwt.encode(payload, JWTService._get_secret(db), algorithm=algo)

    @staticmethod
    def create_refresh_token(
        user_id: str,
        remember_me: bool = False,
        db: Session | None = None,
    ) -> tuple[str, str]:
        """Create a long-lived refresh token.

        Args:
            user_id: User ID.
            remember_me: If True, token lives 30 days; otherwise 7 days.
            db: Optional DB session for runtime settings.

        Returns:
            Tuple of ``(token_string, jti)`` where ``jti`` is the unique
            token identifier stored in the database for revocation.
        """
        if db is not None:
            from app.services.platform_settings_service import (
                PlatformSettingsService as PSS,
            )

            remember_days = PSS.get_int(db, "JWT_REFRESH_TOKEN_REMEMBER_DAYS")
            expire_days = PSS.get_int(db, "JWT_REFRESH_TOKEN_EXPIRE_DAYS")
        else:
            remember_days = 30  # safe default when no db
            expire_days = 7

        now = datetime.now(timezone.utc)
        jti = secrets.token_hex(16)
        days = remember_days if remember_me else expire_days
        payload = {
            "sub": user_id,
            "type": "refresh",
            "exp": now + timedelta(days=days),
            "iat": now,
            "jti": jti,
        }
        algo = JWTService._get_algorithm(db)
        token = jwt.encode(payload, JWTService._get_secret(db), algorithm=algo)
        return token, jti

    @staticmethod
    def create_verification_token(user_id: str, db: Session | None = None) -> str:
        """Create an email verification token (24 hours).

        Args:
            user_id: User ID.
            db: Optional DB session for runtime settings.

        Returns:
            Encoded JWT string.
        """
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "type": "verify",
            "exp": now + timedelta(hours=24),
            "iat": now,
        }
        algo = JWTService._get_algorithm(db)
        return jwt.encode(payload, JWTService._get_secret(db), algorithm=algo)

    @staticmethod
    def create_reset_token(user_id: str, db: Session | None = None) -> str:
        """Create a password reset token (1 hour).

        Args:
            user_id: User ID.
            db: Optional DB session for runtime settings.

        Returns:
            Encoded JWT string.
        """
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "type": "reset",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        algo = JWTService._get_algorithm(db)
        return jwt.encode(payload, JWTService._get_secret(db), algorithm=algo)

    @staticmethod
    def decode_token(token: str, db: Session | None = None) -> dict[str, Any]:
        """Decode and verify a JWT token.

        Args:
            token: Encoded JWT string.
            db: Optional DB session for runtime settings.

        Returns:
            Decoded payload dictionary.

        Raises:
            jwt.ExpiredSignatureError: If the token has expired.
            jwt.InvalidTokenError: If the token is invalid.
        """
        algo = JWTService._get_algorithm(db)
        return jwt.decode(
            token,
            JWTService._get_secret(db),
            algorithms=[algo],
        )
