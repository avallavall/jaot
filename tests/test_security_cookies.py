"""Tests for cookie security attributes in auth and GDPR endpoints.

Verifies behavior (not source code) for:
- Login Set-Cookie Secure attribute respects env (DEBUG=False ⇒ Secure)
- Login Set-Cookie sets HttpOnly + SameSite=Lax unconditionally
- Logout Set-Cookie clears both access and refresh cookies
- Module-level _cookie_secure constant is derived from settings.DEBUG
"""

import importlib

import pytest

from app.models import Organization, User
from app.services.auth.password_service import PasswordService


# Override autouse fixtures from conftest.py that are unneeded here.
@pytest.fixture(autouse=True)
def _truncate_tables():
    yield


@pytest.fixture(autouse=True)
def override_db_dependency():
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    yield


def _create_login_user(db_session):
    """Create a user with an argon2id password so we can hit the login endpoint."""
    org = Organization(
        id="org_cookie001",
        name="Cookie Org",
        credits_balance=100,
        is_active=True,
    )
    db_session.add(org)
    user = User(
        id="usr_cookie001",
        email="cookie@example.com",
        name="Cookie User",
        organization_id="org_cookie001",
        password_hash=PasswordService.hash_password("password123"),
        email_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    return user, org


class TestAuthCookieSecureFlag:
    """Behavior tests for login Set-Cookie attributes."""

    def test_login_cookies_have_httponly_and_samesite(self, client, db_session):
        """Login Set-Cookie headers must carry HttpOnly + SameSite=Lax.

        This replaces the old source-grep assertion. We hit the real login
        endpoint and inspect the actual Set-Cookie headers the client sees.
        """
        _create_login_user(db_session)
        response = client.post(
            "/api/v2/auth/login/email",
            json={"email": "cookie@example.com", "password": "password123"},
        )
        assert response.status_code == 200

        set_cookie_headers = response.headers.get_list("set-cookie")
        access_hdr = next(
            (h for h in set_cookie_headers if h.startswith("jaot_access_token=")), None
        )
        refresh_hdr = next(
            (h for h in set_cookie_headers if h.startswith("jaot_refresh_token=")), None
        )
        assert access_hdr is not None
        assert refresh_hdr is not None

        for header in (access_hdr, refresh_hdr):
            lower = header.lower()
            assert "httponly" in lower, f"cookie missing HttpOnly: {header}"
            assert "samesite=lax" in lower, f"cookie missing SameSite=Lax: {header}"

    def test_logout_clears_both_cookies(self, client):
        """Logout Set-Cookie headers must clear access + refresh cookies.

        Replaces the old source-grep test. The logout handler calls
        delete_cookie() twice; starlette translates that into Set-Cookie
        with Max-Age=0 or an expired Expires header. Either is acceptable.
        """
        response = client.post("/api/v2/auth/logout")
        assert response.status_code == 200

        set_cookie_headers = response.headers.get_list("set-cookie")
        access_hdr = next(
            (h for h in set_cookie_headers if h.startswith("jaot_access_token=")), None
        )
        refresh_hdr = next(
            (h for h in set_cookie_headers if h.startswith("jaot_refresh_token=")), None
        )
        assert access_hdr is not None, "logout did not clear jaot_access_token"
        assert refresh_hdr is not None, "logout did not clear jaot_refresh_token"

        for header in (access_hdr, refresh_hdr):
            lower = header.lower()
            assert "max-age=0" in lower or "expires=thu, 01 jan 1970" in lower, (
                f"logout cookie not cleared: {header}"
            )


class TestCookieSecureValueByEnvironment:
    """Verify behavior of _cookie_secure in production vs debug mode.

    The constant is captured at module import time, so we patch
    settings.DEBUG and reload the module to pin the actual constant
    — then also verify the live login endpoint emits Secure when the
    constant is forced True.
    """

    def test_cookie_secure_true_when_debug_false(self):
        """With DEBUG=False, auth._cookie_secure is True."""
        from app.api.v2 import auth
        from app.config import settings

        original_debug = settings.DEBUG
        try:
            object.__setattr__(settings, "DEBUG", False)
            importlib.reload(auth)
            assert auth._cookie_secure is True
        finally:
            object.__setattr__(settings, "DEBUG", original_debug)
            importlib.reload(auth)

    def test_cookie_secure_false_when_debug_true(self):
        """With DEBUG=True, auth._cookie_secure is False (dev over http)."""
        from app.api.v2 import auth
        from app.config import settings

        original_debug = settings.DEBUG
        try:
            object.__setattr__(settings, "DEBUG", True)
            importlib.reload(auth)
            assert auth._cookie_secure is False
        finally:
            object.__setattr__(settings, "DEBUG", original_debug)
            importlib.reload(auth)

    def test_login_cookies_have_secure_when_cookie_secure_true(
        self, client, db_session, monkeypatch
    ):
        """When _cookie_secure is True at runtime, the real login response
        must carry 'Secure' on both Set-Cookie headers.

        We monkeypatch `auth._cookie_secure` directly (rather than reloading
        the module, which would break the already-mounted router) and hit
        the live endpoint to inspect the Set-Cookie.
        """
        from app.api.v2 import auth as auth_mod

        monkeypatch.setattr(auth_mod, "_cookie_secure", True)

        _create_login_user(db_session)
        response = client.post(
            "/api/v2/auth/login/email",
            json={"email": "cookie@example.com", "password": "password123"},
        )
        assert response.status_code == 200

        set_cookie_headers = response.headers.get_list("set-cookie")
        assert any(
            "secure" in h.lower() and h.startswith("jaot_access_token=") for h in set_cookie_headers
        ), f"access_token cookie missing Secure: {set_cookie_headers}"
        assert any(
            "secure" in h.lower() and h.startswith("jaot_refresh_token=")
            for h in set_cookie_headers
        ), f"refresh_token cookie missing Secure: {set_cookie_headers}"
