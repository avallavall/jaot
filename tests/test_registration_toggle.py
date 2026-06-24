"""Tests for the REGISTRATION_ENABLED toggle.

Verifies that:
- Signup is blocked (503) when registration is disabled (default).
- Signup succeeds when registration is explicitly enabled.
- Both /signup and /signup/email endpoints are guarded.
- Login still works when registration is disabled.
- Admin can toggle the setting via /api/v2/admin/settings/values.
"""

from app.services.platform_settings_service import PlatformSettingsService

_EMAIL_SIGNUP_PAYLOAD = {
    "email": "newuser@example.com",
    "name": "New User",
    "organization_name": "New Org",
    "plan": "free",
    "password": "StrongP@ss1234",
    "confirm_password": "StrongP@ss1234",
    "tos_accepted": True,
}

_API_SIGNUP_PAYLOAD = {
    "email": "apiuser@example.com",
    "name": "API User",
    "organization_name": "API Org",
    "plan": "free",
}


def _enable_registration(db_session):
    """Set REGISTRATION_ENABLED=true in the DB."""
    PlatformSettingsService.set(db_session, "REGISTRATION_ENABLED", "true")
    db_session.commit()


def _disable_registration(db_session):
    """Explicitly set REGISTRATION_ENABLED=false in the DB."""
    PlatformSettingsService.set(db_session, "REGISTRATION_ENABLED", "false")
    db_session.commit()


class TestRegistrationDisabledByDefault:
    """With no DB override, registration defaults to disabled."""

    def test_signup_email_returns_503_when_disabled(self, client, db_session):
        """POST /api/v2/auth/signup/email returns 503 by default."""
        resp = client.post("/api/v2/auth/signup/email", json=_EMAIL_SIGNUP_PAYLOAD)
        assert resp.status_code == 503
        body = resp.json()
        assert "disabled" in body["detail"].lower()
        assert "support@jaot.io" in body["detail"]

    def test_signup_api_returns_503_when_disabled(self, client, db_session):
        """POST /api/v2/auth/signup returns 503 by default."""
        resp = client.post("/api/v2/auth/signup", json=_API_SIGNUP_PAYLOAD)
        assert resp.status_code == 503
        body = resp.json()
        assert "disabled" in body["detail"].lower()

    def test_no_user_created_when_disabled(self, client, db_session):
        """No user or org should be created when registration is disabled."""
        from app.models import User

        client.post("/api/v2/auth/signup/email", json=_EMAIL_SIGNUP_PAYLOAD)
        user = db_session.query(User).filter(User.email == _EMAIL_SIGNUP_PAYLOAD["email"]).first()
        assert user is None


class TestRegistrationEnabled:
    """With REGISTRATION_ENABLED=true, signup works normally."""

    def test_signup_email_succeeds_when_enabled(self, client, db_session):
        """POST /api/v2/auth/signup/email returns 201 when enabled."""
        _enable_registration(db_session)
        resp = client.post("/api/v2/auth/signup/email", json=_EMAIL_SIGNUP_PAYLOAD)
        assert resp.status_code == 201
        body = resp.json()
        assert "user_id" in body
        assert "api_key" in body

    def test_signup_api_succeeds_when_enabled(self, client, db_session):
        """POST /api/v2/auth/signup returns 200 when enabled."""
        _enable_registration(db_session)
        resp = client.post("/api/v2/auth/signup", json=_API_SIGNUP_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert "user_id" in body
        assert "api_key" in body


class TestRegistrationExplicitlyDisabled:
    """Setting can be toggled off after being on."""

    def test_signup_blocked_after_explicit_disable(self, client, db_session):
        _enable_registration(db_session)
        # Verify it works first
        resp = client.post("/api/v2/auth/signup", json=_API_SIGNUP_PAYLOAD)
        assert resp.status_code == 200

        # Disable again
        _disable_registration(db_session)
        resp = client.post(
            "/api/v2/auth/signup",
            json={
                **_API_SIGNUP_PAYLOAD,
                "email": "another@example.com",
            },
        )
        assert resp.status_code == 503


class TestLoginUnaffectedByRegistrationToggle:
    """Login endpoints must remain functional regardless of toggle."""

    def test_login_email_works_when_registration_disabled(self, client, db_session):
        """POST /api/v2/auth/login/email still works with valid creds."""
        from app.models import Organization, User
        from app.services.auth import PasswordService

        # Create a user with password (manually, since signup is disabled)
        org = Organization(
            id="org_logintest01",
            name="Login Test Org",
            credits_balance=100,
        )
        db_session.add(org)
        user = User(
            id="usr_logintest01",
            email="logintest@example.com",
            name="Login Test",
            organization_id="org_logintest01",
            password_hash=PasswordService.hash_password("TestP@ss1234"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()

        # Registration is disabled by default — login should still work
        resp = client.post(
            "/api/v2/auth/login/email",
            json={"email": "logintest@example.com", "password": "TestP@ss1234"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_api_key_login_works_when_registration_disabled(self, client, db_session, test_api_key):
        """POST /api/v2/auth/login still works with valid API key."""
        resp = client.post(
            "/api/v2/auth/login",
            json={"api_key": test_api_key.plaintext},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True


class TestAdminToggle:
    """Admin can toggle REGISTRATION_ENABLED via settings values endpoint."""

    def test_admin_can_enable_registration(self, admin_client, db_session):
        """PUT /api/v2/admin/settings/values toggles registration on."""
        resp = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"REGISTRATION_ENABLED": "true"}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "REGISTRATION_ENABLED" in body["updated"]

        # Verify the DB value
        assert PlatformSettingsService.get_bool(db_session, "REGISTRATION_ENABLED") is True

    def test_admin_can_disable_registration(self, admin_client, db_session):
        """Admin can disable registration after enabling it."""
        _enable_registration(db_session)

        resp = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"REGISTRATION_ENABLED": "false"}},
        )
        assert resp.status_code == 200

        assert PlatformSettingsService.get_bool(db_session, "REGISTRATION_ENABLED") is False

    def test_toggle_round_trip(self, admin_client, client, db_session):
        """Enable via admin, signup works; disable via admin, signup blocked."""
        # Enable
        r = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"REGISTRATION_ENABLED": "true"}},
        )
        assert r.status_code == 200

        resp = client.post("/api/v2/auth/signup/email", json=_EMAIL_SIGNUP_PAYLOAD)
        assert resp.status_code == 201

        # The signup above set a member ``jaot_access_token`` cookie in the shared
        # TestClient jar. ``ASGIAuthMiddleware._authenticate`` tries the JWT cookie
        # BEFORE the Bearer API key, so leaving it would make the admin PUT below
        # authenticate as that (non-admin) member → 403 → the disable is silently
        # skipped. Clear it so admin_client authenticates via its admin API key.
        client.cookies.clear()

        # Disable
        r = admin_client.put(
            "/api/v2/admin/settings/values",
            json={"updates": {"REGISTRATION_ENABLED": "false"}},
        )
        assert r.status_code == 200

        resp = client.post(
            "/api/v2/auth/signup/email",
            json={
                **_EMAIL_SIGNUP_PAYLOAD,
                "email": "blocked@example.com",
            },
        )
        assert resp.status_code == 503
