"""Pytest configuration for auth-specific tests.

Most fixtures are inherited from the root conftest. Only auth-specific
data fixtures and specialized clients remain here.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.models import Organization, User
from app.services.auth.api_key_service import APIKeyService
from app.shared.utils.datetime_helpers import utcnow


@pytest.fixture
def auth_organization(db_session):
    """Create test organization for auth tests."""
    org = Organization(
        id="org_auth_test",
        name="Auth Test Company",
        credits_balance=1000,
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def auth_admin_user(db_session, auth_organization):
    """Create admin user for auth tests."""
    user = User(
        id="user_auth_admin",
        email="admin@authtest.com",
        name="Auth Admin User",
        organization_id=auth_organization.id,
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_regular_user(db_session, auth_organization):
    """Create regular user for auth tests."""
    user = User(
        id="user_auth_regular",
        email="regular@authtest.com",
        name="Auth Regular User",
        organization_id=auth_organization.id,
        role="member",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_api_key(db_session, auth_admin_user, auth_organization):
    """Provision a valid API key for the admin user."""
    api_key, plaintext = APIKeyService.create_api_key(
        db=db_session,
        user_id=auth_admin_user.id,
        organization_id=auth_organization.id,
        name="Admin Test Key",
    )
    return SimpleNamespace(model=api_key, plaintext=plaintext)


@pytest.fixture
def auth_regular_api_key(db_session, auth_regular_user, auth_organization):
    """Provision a valid API key for a regular user."""
    api_key, plaintext = APIKeyService.create_api_key(
        db=db_session,
        user_id=auth_regular_user.id,
        organization_id=auth_organization.id,
        name="Regular Test Key",
    )
    return SimpleNamespace(model=api_key, plaintext=plaintext)


@pytest.fixture
def auth_client(app, auth_api_key):
    """Authenticated client for auth admin user."""
    with TestClient(app) as c:
        c.headers = {"Authorization": f"Bearer {auth_api_key.plaintext}"}
        yield c


@pytest.fixture
def regular_auth_client(app, auth_regular_api_key):
    """Authenticated client for regular (non-admin) auth user."""
    with TestClient(app) as c:
        c.headers = {"Authorization": f"Bearer {auth_regular_api_key.plaintext}"}
        yield c


@pytest.fixture
def authenticated_regular_client(app, auth_regular_api_key):
    """Alias for regular_auth_client (backward compat)."""
    with TestClient(app) as c:
        c.headers = {"Authorization": f"Bearer {auth_regular_api_key.plaintext}"}
        yield c


@pytest.fixture
def auth_expired_api_key(db_session, auth_regular_user, auth_organization):
    """Provision an expired API key."""
    expired_date = (utcnow() - timedelta(days=1)).replace(tzinfo=None)
    api_key, plaintext = APIKeyService.create_api_key(
        db=db_session,
        user_id=auth_regular_user.id,
        organization_id=auth_organization.id,
        name="Expired Test Key",
        expires_at=expired_date,
    )
    return SimpleNamespace(model=api_key, plaintext=plaintext)


@pytest.fixture
def auth_inactive_user(db_session, auth_organization):
    """Create inactive user for auth tests."""
    user = User(
        id="user_auth_inactive",
        email="inactive@authtest.com",
        name="Auth Inactive User",
        organization_id=auth_organization.id,
        role="member",
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# Backward compat aliases for tests that reference auth_db_session or auth_app
@pytest.fixture
def auth_db_session(db_session):
    """Alias: auth tests now use the root db_session (SAVEPOINT-based)."""
    return db_session


@pytest.fixture
def auth_app(app):
    """Alias: auth tests now use the root app."""
    return app
