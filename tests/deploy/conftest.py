"""Conftest for deploy/ tests.

Overrides the autouse fixtures from the parent conftest.py that require
a live PostgreSQL connection. Unit-level tests in this package use
monkeypatch / importlib reload exclusively and need no DB.

Integration tests (test_api_key_service_commit.py) open their own
SessionLocal() connections and handle isolation themselves.
"""

import pytest


@pytest.fixture(autouse=True)
def _override_db_dependency():
    """No-op override of parent conftest's _override_db_dependency."""
    yield


@pytest.fixture(autouse=True)
def _seed_platform_settings():
    """No-op override of parent conftest's _seed_platform_settings."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    """No-op override of parent conftest's _clear_rate_limiter."""
    yield
