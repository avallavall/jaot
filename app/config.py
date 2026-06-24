"""Application configuration using Pydantic Settings.

After the config simplification (Phase 3), Settings contains ONLY
infrastructure variables that must be available before the database is
reachable.  All business configuration lives in the ``platform_settings``
DB table, managed via ``PlatformSettingsService``.
"""

import logging
import os
import secrets
from functools import cached_property
from typing import Self

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_config_logger = logging.getLogger(__name__)

# Load environment variables from .env file (overrides .env.example).
# When TESTING=1 (set by conftest.py), skip override=True so that test
# env vars (e.g. DATABASE_URL pointing to jaot_test) are not stomped.
if os.environ.get("TESTING"):
    load_dotenv(".env", override=False)
else:
    load_dotenv(".env", override=True)


class Settings(BaseSettings):
    """Infrastructure settings loaded from environment variables.

    Business configuration (plans, LLM, Stripe, email, etc.) has been
    moved to the ``platform_settings`` DB table.  Only variables needed
    before the DB is available remain here.
    """

    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        extra="ignore",
    )

    DEBUG: bool = True

    # Server bootstrap (read by run.py before DB is available)
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    WORKERS: int = 1
    RELOAD: bool = True

    DATABASE_URL: str = ""
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600

    REDIS_URL: str = ""

    # Celery (read at module-import time by celery_app.py / email_tasks)
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_EXPIRES: int = 604800
    CELERY_MAX_RETRIES: int = 3
    CELERY_DEFAULT_RETRY_DELAY: int = 300

    # JWT secret (chicken-and-egg: needed to authenticate before DB)
    JWT_SECRET: str = ""

    # Phase 7.4 / D-09 cleanup: SOLVER_LICENSE_ENCRYPTION_KEY removed.
    # BYOL Fernet encryption is gone — platform license is plaintext on disk
    # at /etc/jaot/hexaly.lic per D-01. Operator must remove the old key from
    # .env.production on the server manually (see runbook addendum in Plan 11).

    # RAG / Qdrant (vector search for LLM formulation assistant)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    FRONTEND_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Docker Compose infra credentials (not read by app code directly)
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    # First-run bootstrap (read by the API lifespan; app/shared/db/seed_admin.py).
    # When the users table is EMPTY and email+password are set, the initial
    # admin + organization are created automatically — the "docker compose up
    # and log in" path. No-op once any user exists. Infra-tier on purpose:
    # this runs before any admin panel exists to configure anything.
    SEED_ADMIN_EMAIL: str = ""
    SEED_ADMIN_PASSWORD: str = ""  # min 12 chars, same as public signup
    SEED_ADMIN_NAME: str = "Admin"
    SEED_ADMIN_ORG_NAME: str = ""  # default: "<name>'s Organization"
    SEED_ORG_CREDITS: int = 0  # 0 = use the pro plan's default credits

    @model_validator(mode="after")
    def _validate_production_config(self) -> Self:
        """Fail fast if critical secrets are missing in production."""
        if not self.DEBUG and not self.JWT_SECRET:
            raise ValueError(
                "JWT_SECRET must be set when DEBUG=False. "
                "The application refuses to start in production "
                "without an explicit JWT secret."
            )
        return self

    @cached_property
    def jwt_secret_key(self) -> str:
        """Return the JWT secret key.

        If ``JWT_SECRET`` is not set, generates a random one and logs a
        warning.  The auto-generated key changes on every restart, so
        sessions will not survive restarts -- suitable only for dev.
        """
        if self.JWT_SECRET:
            return self.JWT_SECRET
        generated = secrets.token_hex(32)
        _config_logger.warning(
            "Using auto-generated JWT_SECRET. Set JWT_SECRET in .env for production."
        )
        return generated


settings = Settings()  # type: ignore[call-arg]
