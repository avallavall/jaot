"""Tests for the maintenance mode middleware.

Verifies that:
- Requests pass through when MAINTENANCE_MODE is off (default).
- Non-admin requests receive 503 when MAINTENANCE_MODE is on.
- Admin requests (JWT cookie) bypass maintenance mode.
- Health check, admin API, login, and metrics paths always bypass.
- The 503 response body and Retry-After header are correct.
"""

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core import maintenance_middleware as maint_mw


@pytest.fixture()
def _enable_maintenance_middleware(db_engine):
    """Temporarily enable maintenance middleware for tests that need it.

    By default the conftest sets ``maint_mw._skip_maintenance_check = True``
    to skip DB checks during most tests.  Tests that exercise maintenance
    mode behaviour need the middleware to actually query platform_settings.
    """
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    original_factory = maint_mw._session_factory
    original_skip = maint_mw._skip_maintenance_check
    maint_mw._session_factory = factory
    maint_mw._skip_maintenance_check = False
    yield factory
    maint_mw._session_factory = original_factory
    maint_mw._skip_maintenance_check = original_skip


class TestMaintenanceModeDefault:
    """Maintenance mode is OFF by default -- all requests pass through."""

    def test_requests_pass_when_maintenance_off(self, client, db_session):
        """Health endpoint returns 200 when MAINTENANCE_MODE is not set."""
        resp = client.get("/api/v2/health")
        assert resp.status_code == 200

    def test_non_health_endpoint_passes_when_maintenance_off(
        self,
        authenticated_client,
        db_session,
    ):
        """Authenticated endpoint works normally with default settings."""
        resp = authenticated_client.get("/api/v2/credits/balance")
        assert resp.status_code == 200

    def test_default_setting_is_false(self, db_session):
        """Registry default for MAINTENANCE_MODE is 'false'."""
        val = PSS.get_bool(db_session, "MAINTENANCE_MODE")
        assert val is False


class TestMaintenanceModeEnabled:
    """Maintenance mode is ON -- non-admin requests get 503."""

    @pytest.fixture(autouse=True)
    def _enable_maintenance(self, client, _enable_maintenance_middleware):
        """Force maintenance mode ON via middleware override."""
        client.cookies.clear()
        maint_mw._force_maintenance = True
        yield
        maint_mw._force_maintenance = None

    def test_non_admin_gets_503(self, client, db_session):
        """An unauthenticated request to a non-bypass path gets 503."""
        resp = client.get("/api/v2/credits/balance")
        assert resp.status_code == 503

        body = resp.json()
        assert body["status"] == "maintenance"
        assert "maintenance" in body["detail"].lower()

    def test_503_has_retry_after_header(self, client, db_session):
        """503 response includes Retry-After header."""
        resp = client.get("/api/v2/credits/balance")
        assert resp.status_code == 503
        assert resp.headers.get("retry-after") == "300"

    def test_503_response_body_structure(self, client, db_session):
        """503 response has the expected JSON structure."""
        resp = client.get("/api/v2/credits/balance")
        assert resp.status_code == 503

        body = resp.json()
        assert "detail" in body
        assert "status" in body
        assert body["status"] == "maintenance"
        assert isinstance(body["detail"], str)
        assert len(body["detail"]) > 0

    def test_authenticated_non_admin_gets_503(
        self,
        authenticated_client,
        db_session,
    ):
        """An authenticated non-admin user still gets 503 with full maintenance contract.

        Strengthening (12.4 Plan 05 TA-01): the legacy test asserted only
        status 503. The maintenance contract is wider:

        * SC1a status: 503 Service Unavailable.
        * SC1b structured body shape (Pydantic-equivalent — no schema exists
          for the 503 envelope, so we assert the exact 2-key dict shape the
          middleware emits via _send_maintenance_response).
        * SC1c side-effect: the request must NOT have leaked through (no
          credit consumption). The maintenance gate fires before any handler
          so balance is untouched.

        Re DB side-effect (D-03 N/A note): this test exercises the in-memory
        _force_maintenance = True override (set by _enable_maintenance), not
        the DB-backed PlatformSetting row, so we assert the override flag
        rather than the PlatformSetting row state.
        """
        from app.models import Organization

        pre_balance = (
            db_session.query(Organization)
            .filter(Organization.id == "org_test001")
            .one()
            .credits_balance
        )

        resp = authenticated_client.get("/api/v2/credits/balance")

        # SC1a: status
        assert resp.status_code == 503

        # SC1b: structured body shape (exact 2-key envelope per
        # _send_maintenance_response).
        body = resp.json()
        assert isinstance(body, dict)
        assert set(body.keys()) == {"detail", "status"}, (
            f"Expected body keys {{'detail', 'status'}}, got {body.keys()}"
        )
        assert body["status"] == "maintenance"
        assert isinstance(body["detail"], str)
        assert "maintenance" in body["detail"].lower()
        assert len(body["detail"]) > 0

        # Retry-After header is part of the 503 contract (RFC 7231 6.6.4).
        assert resp.headers.get("retry-after") == "300"

        # SC1c side-effect: the gate fires before the credits handler.
        post_balance = (
            db_session.query(Organization)
            .filter(Organization.id == "org_test001")
            .one()
            .credits_balance
        )
        assert post_balance == pre_balance, (
            f"Maintenance leaked: balance moved from {pre_balance} to {post_balance}"
        )

        # Verify the precondition: maintenance ON via in-memory override.
        assert maint_mw._force_maintenance is True

    def test_health_endpoint_bypasses_maintenance(self, client, db_session):
        """Health check always passes through maintenance mode."""
        resp = client.get("/api/v2/health")
        assert resp.status_code == 200

    def test_admin_api_bypasses_maintenance(self, client, db_session):
        """Admin API paths always pass through maintenance mode."""
        resp = client.get("/api/v2/admin/stats")
        # May return 401/403 etc but NOT 503
        assert resp.status_code != 503

    def test_login_endpoint_bypasses_maintenance(self, client, db_session):
        """Login endpoint always passes through so admins can authenticate."""
        resp = client.post(
            "/api/v2/auth/login",
            json={"email": "admin@example.com", "password": "wrong"},
        )
        # Should return 401 or 422, not 503
        assert resp.status_code != 503

    def test_refresh_endpoint_bypasses_maintenance(self, client, db_session):
        """Token refresh endpoint always passes through."""
        resp = client.post("/api/v2/auth/refresh")
        assert resp.status_code != 503

    def test_token_refresh_alt_path_bypasses_maintenance(
        self,
        client,
        db_session,
    ):
        """Alternative token refresh path also bypasses maintenance."""
        resp = client.post("/api/v2/auth/token/refresh")
        assert resp.status_code != 503

    def test_metrics_endpoint_bypasses_maintenance(self, client, db_session):
        """Metrics endpoint always passes through for monitoring."""
        resp = client.get("/metrics")
        # Should not be 503
        assert resp.status_code != 503

    def test_docs_endpoint_bypasses_maintenance(self, client, db_session):
        """Docs endpoint passes through during maintenance."""
        resp = client.get("/docs")
        assert resp.status_code != 503

    def test_multiple_non_bypass_paths_get_503(self, client, db_session):
        """Various non-bypass paths all get 503 during maintenance."""
        paths = [
            "/api/v2/credits/balance",
            "/api/v2/models",
            "/api/v2/solve",
        ]
        for path in paths:
            resp = client.get(path)
            assert resp.status_code == 503, f"Expected 503 for {path}, got {resp.status_code}"


class TestMaintenanceModeAdminBypass:
    """Admin users bypass maintenance mode via JWT cookie."""

    @pytest.fixture(autouse=True)
    def _enable_maintenance(self, client, _enable_maintenance_middleware):
        """Force maintenance mode ON via middleware override."""
        client.cookies.clear()
        maint_mw._force_maintenance = True
        yield
        maint_mw._force_maintenance = None

    def _make_admin_jwt(self) -> str:
        """Create a valid admin JWT token."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "user_admin001",
            "org": "org_test001",
            "admin": True,
            "type": "access",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        return pyjwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm="HS256",
        )

    def _make_non_admin_jwt(self) -> str:
        """Create a valid non-admin JWT token."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "user_test001",
            "org": "org_test001",
            "admin": False,
            "type": "access",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        return pyjwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm="HS256",
        )

    def _make_expired_admin_jwt(self) -> str:
        """Create an expired admin JWT token."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "user_admin001",
            "org": "org_test001",
            "admin": True,
            "type": "access",
            "exp": now - timedelta(hours=1),
            "iat": now - timedelta(hours=2),
        }
        return pyjwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm="HS256",
        )

    def test_admin_jwt_cookie_bypasses_maintenance(
        self,
        client,
        db_session,
    ):
        """Admin JWT cookie lets the request through during maintenance."""
        token = self._make_admin_jwt()
        resp = client.get(
            "/api/v2/credits/balance",
            cookies={"jaot_access_token": token},
        )
        # Should NOT be 503. It may be 401 because auth is disabled in tests,
        # but that proves the maintenance middleware let it through.
        assert resp.status_code != 503

    def test_non_admin_jwt_cookie_blocked_during_maintenance(
        self,
        client,
        db_session,
    ):
        """Non-admin JWT cookie does NOT bypass maintenance."""
        token = self._make_non_admin_jwt()
        resp = client.get(
            "/api/v2/credits/balance",
            cookies={"jaot_access_token": token},
        )
        assert resp.status_code == 503

    def test_expired_admin_jwt_blocked_during_maintenance(
        self,
        client,
        db_session,
    ):
        """Expired admin JWT is treated as non-admin -- gets 503."""
        token = self._make_expired_admin_jwt()
        resp = client.get(
            "/api/v2/credits/balance",
            cookies={"jaot_access_token": token},
        )
        assert resp.status_code == 503

    def test_invalid_jwt_blocked_during_maintenance(
        self,
        client,
        db_session,
    ):
        """Malformed JWT is treated as non-admin -- gets 503."""
        resp = client.get(
            "/api/v2/credits/balance",
            cookies={"jaot_access_token": "not-a-valid-jwt"},
        )
        assert resp.status_code == 503

    def test_wrong_secret_jwt_blocked_during_maintenance(
        self,
        client,
        db_session,
    ):
        """JWT signed with wrong secret is treated as non-admin."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "user_admin001",
            "org": "org_test001",
            "admin": True,
            "type": "access",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        resp = client.get(
            "/api/v2/credits/balance",
            cookies={"jaot_access_token": token},
        )
        assert resp.status_code == 503

    def test_jwt_without_admin_claim_blocked(
        self,
        client,
        db_session,
    ):
        """JWT missing the admin claim is treated as non-admin."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "user_test001",
            "org": "org_test001",
            "type": "access",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        token = pyjwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm="HS256",
        )
        resp = client.get(
            "/api/v2/credits/balance",
            cookies={"jaot_access_token": token},
        )
        assert resp.status_code == 503


class TestMaintenanceSettingToggle:
    """Maintenance mode can be toggled on/off at runtime via the DB."""

    def test_toggle_maintenance_on_off(
        self,
        client,
        _enable_maintenance_middleware,
    ):
        """Maintenance can be flipped and takes effect immediately."""
        # Default: off
        resp = client.get("/api/v2/credits/balance")
        assert resp.status_code != 503

        # Turn on
        maint_mw._force_maintenance = True
        resp = client.get("/api/v2/credits/balance")
        assert resp.status_code == 503

        # Turn off
        maint_mw._force_maintenance = False
        resp = client.get("/api/v2/credits/balance")
        assert resp.status_code != 503

        # Cleanup
        maint_mw._force_maintenance = None

    def test_deleting_setting_disables_maintenance(
        self,
        client,
        _enable_maintenance_middleware,
    ):
        """Clearing the override falls back to default (off)."""
        maint_mw._force_maintenance = True

        resp = client.get("/api/v2/credits/balance")
        assert resp.status_code == 503

        # Clear override → default off
        maint_mw._force_maintenance = None

        resp = client.get("/api/v2/credits/balance")
        assert resp.status_code != 503


class TestMaintenanceRegistryEntry:
    """The MAINTENANCE_MODE setting is properly registered."""

    def test_setting_in_registry(self):
        """MAINTENANCE_MODE exists in the settings registry."""
        from app.services.settings_registry import REGISTRY_BY_KEY

        defn = REGISTRY_BY_KEY.get("MAINTENANCE_MODE")
        assert defn is not None
        assert defn.setting_type.value == "bool"
        assert defn.category.value == "system"
        assert defn.is_secret is False
        assert defn.is_readonly is False

    def test_setting_in_defaults(self):
        """MAINTENANCE_MODE has a default of 'false' in registry."""
        from app.services.settings_registry import REGISTRY_BY_KEY

        defn = REGISTRY_BY_KEY.get("MAINTENANCE_MODE")
        assert defn is not None
        assert defn.default_value == "false"
