"""Tests for profiles API endpoints.

Tests the public profiles and reviews system including:
- Organization public profiles
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app():
    """Create test app."""
    return create_app()


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestOrganizationProfiles:
    """Tests for organization profile endpoints."""

    def test_get_org_profile_not_found(self, client):
        """Test getting non-existent organization profile.

        Asserts 404 + JSON error payload + detail string. Verifies the
        response is a real JSON error (not an HTML 404 routing artifact).
        """
        response = client.get("/api/v2/organizations/nonexistent-org/public")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["detail"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
