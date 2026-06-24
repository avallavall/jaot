"""Conftest for unit tests -- no database fixtures needed.

Overrides the autouse fixtures from the parent conftest.py that require
a live PostgreSQL connection. Unit tests use mocking exclusively.
"""

import pytest


@pytest.fixture(autouse=True)
def _override_db_dependency():
    """No-op override of parent conftest's _override_db_dependency."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    """No-op override of parent conftest's _clear_rate_limiter."""
    yield
