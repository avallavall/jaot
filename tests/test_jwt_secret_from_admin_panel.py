"""A JWT_SECRET set in the admin panel must sign AND verify every session.

# CONTRACT-TEST: the key that signs a token is the key that verifies it.

The Secrets tab offers ``JWT_SECRET`` and says it takes precedence over the
environment. The login signed with it, but the auth middleware, the WebSocket
handshake and the maintenance bypass verified with the environment value. From
the moment an admin saved the setting, every cookie failed its signature check,
including the one a fresh login returned, and the admin panel (cookie-only)
could no longer be reached to undo it.
"""

from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Organization, User
from app.services.auth import PasswordService
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core import maintenance_middleware as maint_mw

PASSWORD = "rotation-pass-123"
PANEL_SECRET = "a-secret-an-admin-typed-into-the-panel"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.api.v2.auth.check_rate_limit", return_value=(True, {})):
        yield


@pytest.fixture
def panel_secret(db_session):
    PSS.set(db_session, "JWT_SECRET", PANEL_SECRET)
    db_session.commit()
    yield PANEL_SECRET
    PSS.set(db_session, "JWT_SECRET", "")
    db_session.commit()


def _make_user(db_session, *, admin: bool) -> User:
    org = Organization(id="org_jwtrot01", name="JWT Rotation Org", is_active=True)
    db_session.add(org)
    user = User(
        id="usr_jwtrot01",
        email="rotation@example.com",
        name="Rotation User",
        organization_id=org.id,
        password_hash=PasswordService.hash_password(PASSWORD),
        email_verified=True,
        is_active=True,
        role="admin" if admin else "member",
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client: TestClient) -> None:
    resp = client.post(
        "/api/v2/auth/login/email",
        json={"email": "rotation@example.com", "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    assert client.cookies.get("jaot_access_token")


def test_a_session_signed_with_the_panel_secret_is_accepted(app, db_session, panel_secret):
    _make_user(db_session, admin=False)
    client = TestClient(app)
    _login(client)

    token = client.cookies.get("jaot_access_token")
    # The login really used the panel secret, not the environment one.
    pyjwt.decode(token, panel_secret, algorithms=["HS256"])
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])

    me = client.get("/api/v2/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["user_email"] == "rotation@example.com"


def test_a_token_signed_with_the_environment_secret_is_refused_after_rotation(
    app, db_session, panel_secret
):
    """Rotating the secret signs everyone out, which the setting promises."""
    user = _make_user(db_session, admin=False)
    stale = pyjwt.encode(
        {"sub": user.id, "org": user.organization_id, "type": "access", "admin": False},
        settings.jwt_secret_key,
        algorithm="HS256",
    )
    client = TestClient(app)
    resp = client.get("/api/v2/auth/me", cookies={"jaot_access_token": stale})
    assert resp.status_code == 401


def test_an_admin_keeps_the_maintenance_bypass_after_rotation(
    app, db_session, db_engine, panel_secret
):
    _make_user(db_session, admin=True)
    client = TestClient(app)
    _login(client)

    original = (
        maint_mw._session_factory,
        maint_mw._skip_maintenance_check,
        maint_mw._force_maintenance,
    )
    maint_mw._session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    maint_mw._skip_maintenance_check = False
    maint_mw._force_maintenance = True
    try:
        resp = client.get("/api/v2/projects")
    finally:
        (
            maint_mw._session_factory,
            maint_mw._skip_maintenance_check,
            maint_mw._force_maintenance,
        ) = original
    assert resp.status_code != 503, resp.text
