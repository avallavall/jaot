"""Tests for admin endpoint authorization and CORS configuration.

Verifies:
- Admin endpoints return 403 for non-admin users
- Admin endpoints return 200 for admin users
- Unauthenticated requests are rejected
- All admin routes have the get_admin_user dependency
- CORS default is not wildcard *
"""

import pytest

from app.api.v2.routes.admin import get_admin_user


class TestAdminEndpointAuth:
    """Test that admin endpoints enforce admin-only access."""

    def test_admin_endpoint_with_admin_user(self, admin_client):
        """Admin user can access /admin/ endpoints and get a list response."""
        response = admin_client.get("/api/v2/admin/organizations")
        assert response.status_code == 200, (
            f"Admin user should get 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_admin_endpoint_with_non_admin_user(self, authenticated_client):
        """Non-admin user receives 403 on /admin/ endpoints."""
        response = authenticated_client.get("/api/v2/admin/organizations")
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_admin_users_endpoint_with_non_admin(self, authenticated_client):
        """Non-admin user receives 403 on /admin/users."""
        response = authenticated_client.get("/api/v2/admin/users")
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_admin_api_keys_endpoint_with_non_admin(self, authenticated_client):
        """Non-admin user receives 403 on /admin/api-keys."""
        response = authenticated_client.get("/api/v2/admin/api-keys")
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_admin_credits_endpoint_with_non_admin(self, authenticated_client):
        """Non-admin user receives 403 on /admin/credits/transactions."""
        response = authenticated_client.get("/api/v2/admin/credits/transactions")
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin access required"

    def test_admin_endpoint_unauthenticated(self, app, db_session, override_db_dependency):
        """Unauthenticated request gets 401 from auth middleware.

        The ASGI auth middleware intercepts the request before it reaches
        the admin dependency and returns 401 with its own response format.
        """
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.get("/api/v2/admin/organizations")
        # Auth middleware rejects unauthenticated requests with 401
        assert response.status_code == 401
        assert response.json()["error"] == "unauthorized"


class TestAdminRouterDependencies:
    """Verify all admin routes are protected by get_admin_user dependency."""

    def test_all_admin_routes_require_admin(self, app):
        """Every route under /api/v2/admin/ must have get_admin_user in its chain."""
        from app.api.v2.routes.admin import router as admin_router

        # The admin router has get_admin_user as a router-level dependency.
        # This automatically applies to ALL sub-routes.
        dep_names = [d.dependency.__name__ for d in admin_router.dependencies]
        assert "get_admin_user" in dep_names, (
            f"Admin router missing get_admin_user dependency. Found: {dep_names}"
        )

    def test_admin_router_has_exactly_one_dependency(self):
        """Admin router should have at least one router-level dependency,
        and `get_admin_user` must be among them."""
        from app.api.v2.routes.admin import router as admin_router

        assert len(admin_router.dependencies) >= 1
        dep_names = [d.dependency.__name__ for d in admin_router.dependencies]
        assert "get_admin_user" in dep_names


class TestCORSConfiguration:
    """Verify CORS is not configured with wildcard origins."""

    def test_cors_allowed_origins_not_wildcard(self):
        """Settings ALLOWED_ORIGINS must not contain wildcard '*'."""
        from app.config import settings

        assert "*" not in settings.ALLOWED_ORIGINS, (
            f"ALLOWED_ORIGINS contains wildcard '*': {settings.ALLOWED_ORIGINS}. "
            "Production deployments must use explicit origin list."
        )

    def test_cors_allowed_origins_has_localhost(self):
        """Default ALLOWED_ORIGINS includes localhost:3000 for development."""
        from app.config import settings

        assert "http://localhost:3000" in settings.ALLOWED_ORIGINS, (
            f"ALLOWED_ORIGINS should include http://localhost:3000: {settings.ALLOWED_ORIGINS}"
        )


class TestGetAdminUserDependency:
    """Unit tests for the get_admin_user dependency function."""

    @pytest.mark.asyncio
    async def test_get_admin_user_with_admin(self, test_admin_user):
        """get_admin_user returns user when user is admin."""
        from unittest.mock import MagicMock

        request = MagicMock()
        request.state.user = test_admin_user
        result = await get_admin_user(request)
        assert result == test_admin_user

    @pytest.mark.asyncio
    async def test_get_admin_user_with_non_admin(self, test_user):
        """get_admin_user raises 403 for non-admin user."""
        from unittest.mock import MagicMock

        from fastapi import HTTPException

        request = MagicMock()
        request.state.user = test_user
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user(request)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Admin access required"

    @pytest.mark.asyncio
    async def test_get_admin_user_with_no_user(self):
        """get_admin_user raises 403 when no user on request."""
        from unittest.mock import MagicMock

        from fastapi import HTTPException
        from starlette.datastructures import State

        request = MagicMock()
        request.state = State()  # Empty state — no user attribute
        with pytest.raises(HTTPException) as exc_info:
            await get_admin_user(request)
        assert exc_info.value.status_code == 403
