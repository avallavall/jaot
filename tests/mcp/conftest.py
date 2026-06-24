"""MCP test configuration.

MCP tests create their own app/client via create_app() — they only test
route structure, OpenAPI schema, and basic auth. They override ALL root
conftest fixtures to avoid DB setup overhead.

Note: tests that make HTTP requests (test_mcp_auth_*) need a real DB
connection since endpoints query the database.
"""

import os

import pytest

# Use the real test DB so HTTP requests don't hang on a fake URL
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DATABASE_URL", "postgresql://jaot:jaot@localhost:5432/jaot_test")
os.environ.setdefault("JWT_SECRET", "test")


# Override all session-scoped fixtures from root conftest to no-ops.
# MCP tests define their own module-scoped mcp_app and mcp_client.


@pytest.fixture(scope="session")
def db_engine():
    yield None


@pytest.fixture(scope="session")
def _connection():
    yield None


@pytest.fixture(scope="session")
def app():
    yield None


@pytest.fixture(scope="session")
def client():
    yield None


@pytest.fixture(scope="function")
def db_session():
    yield None


@pytest.fixture(autouse=True)
def _override_db_dependency():
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    yield
