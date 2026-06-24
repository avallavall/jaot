"""Tests for application settings configuration."""

import pytest

from app.config import Settings


def test_jwt_secret_required_in_production():
    """Settings must raise ValueError when DEBUG=False and JWT_SECRET is empty."""
    with pytest.raises(Exception, match="JWT_SECRET must be set"):
        Settings(DEBUG=False, JWT_SECRET="")


def test_jwt_secret_not_required_in_debug():
    """Settings should NOT raise when DEBUG=True and JWT_SECRET is empty."""
    s = Settings(DEBUG=True, JWT_SECRET="")
    assert s.DEBUG is True


def test_jwt_secret_accepted_in_production():
    """Settings should accept a non-empty JWT_SECRET in production."""
    s = Settings(DEBUG=False, JWT_SECRET="my-production-secret-key")
    assert s.JWT_SECRET == "my-production-secret-key"


def test_infra_fields_exist():
    """Settings exposes the infrastructure fields with the right type and defaults."""
    # Use a fresh Settings() so we test the documented defaults, not whatever
    # the running .env happens to set.
    s = Settings(DEBUG=True, JWT_SECRET="")

    # Strings (DSN-shaped infra config)
    assert isinstance(s.DATABASE_URL, str)
    assert isinstance(s.REDIS_URL, str)
    assert isinstance(s.CELERY_BROKER_URL, str)
    assert isinstance(s.JWT_SECRET, str)
    assert isinstance(s.FRONTEND_URL, str)
    assert isinstance(s.HOST, str)
    # Booleans
    assert isinstance(s.DEBUG, bool)
    assert isinstance(s.RELOAD, bool)
    # Integers
    assert isinstance(s.PORT, int)
    assert isinstance(s.WORKERS, int)
    assert isinstance(s.DB_POOL_SIZE, int)
    assert isinstance(s.DB_MAX_OVERFLOW, int)
    assert isinstance(s.DB_POOL_RECYCLE, int)
    assert isinstance(s.CELERY_RESULT_EXPIRES, int)
    assert isinstance(s.CELERY_MAX_RETRIES, int)
    assert isinstance(s.CELERY_DEFAULT_RETRY_DELAY, int)
    # Lists
    assert isinstance(s.ALLOWED_ORIGINS, list)

    # Critical default values must remain stable (changing these is a breaking
    # infrastructure change and should be a deliberate decision, not a drift).
    assert s.HOST == "0.0.0.0"
    assert s.PORT == 8001
    assert s.WORKERS == 1
    assert s.DB_POOL_SIZE == 20
    assert s.DB_MAX_OVERFLOW == 10
    assert s.DB_POOL_RECYCLE == 3600
    assert s.CELERY_MAX_RETRIES == 3
    assert s.CELERY_DEFAULT_RETRY_DELAY == 300
    assert s.FRONTEND_URL == "http://localhost:3000"
    assert s.ALLOWED_ORIGINS == ["http://localhost:3000"]


def test_business_fields_removed():
    """Business config fields should no longer exist on Settings."""
    from app.config import settings

    removed_fields = [
        "APP_NAME",
        "API_DESCRIPTION",
        "APP_VERSION",
        "API_V1_PREFIX",
        "GZIP_MINIMUM_SIZE",
        "DOCS_URL",
        "REDOC_URL",
        "SOLVER_DEFAULT_TIMEOUT",
        "SOLVER_VIOLATION_TOLERANCE",
        "DEFAULT_PLAN",
        "DEFAULT_USER_ROLE",
        "API_KEY_DEFAULT_NAME",
        "API_KEY_DEFAULT_PREFIX",
        "API_KEY_TEST_PREFIX",
        "API_KEY_DEFAULT_EXPIRY_DAYS",
        "API_KEY_ACTIVE_BY_DEFAULT",
        "JWT_ALGORITHM",
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        "JWT_REFRESH_TOKEN_EXPIRE_DAYS",
        "JWT_REFRESH_TOKEN_REMEMBER_DAYS",
        "ID_PREFIX_ORGANIZATION",
        "ID_PREFIX_USER",
        "ID_PREFIX_API_KEY",
        "ID_PREFIX_USAGE_RECORD",
        "ID_PREFIX_RATE_LIMIT_EVENT",
        "SOLVER_POOL_SIZE",
        "SOLVER_TIMEOUT_SECONDS",
        "CRON_DEFAULT_CREDIT_ESTIMATE",
        "RATE_LIMIT_WINDOW_SECONDS",
        "RATE_LIMIT_DAILY_WINDOW_SECONDS",
        "METRICS_MAX_RECENT_REQUESTS",
        "METRICS_DEFAULT_RECENT_LIMIT",
        "PROBLEM_TYPE_MANUAL_CREDIT_ADDITION",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "EMAIL_BACKEND",
        "SMTP_HOST",
        "SMTP_PORT",
        "ANTHROPIC_API_KEY",
        "LLM_DEFAULT_MODEL",
        "LLM_MAX_TOKENS",
        "DISCOURSE_SSO_SECRET",
        "STORAGE_ACCOUNT_ID",
        "PLAN_FREE",
        "PLAN_STARTER",
        "PLAN_PRO",
        "PLAN_BUSINESS",
    ]
    for field in removed_fields:
        assert not hasattr(settings, field), f"Settings still has removed field: {field}"
