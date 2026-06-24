"""Tests for account lockout after repeated failed login attempts.

Tests POST directly to /api/v2/auth/login/email to exercise the lockout
logic in the actual login_email endpoint (no mock auth).
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.models import Organization, User
from app.services.auth import PasswordService
from app.shared.utils.datetime_helpers import utcnow

CORRECT_PASSWORD = "testpass123"
WRONG_PASSWORD = "wrongpassword"
LOGIN_URL = "/api/v2/auth/login/email"


@pytest.fixture(autouse=True)
def _bypass_rate_limit():
    """Disable rate limiting for lockout tests to avoid 429 interference."""
    with patch("app.api.v2.auth.check_rate_limit", return_value=(True, {})):
        yield


@pytest.fixture
def lockout_org(db_session):
    """Create organization for lockout tests."""
    org = Organization(
        id="org_lockout01",
        name="Lockout Test Org",
        credits_balance=100,
        is_active=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def lockout_user(db_session, lockout_org):
    """Create user with a password for lockout tests."""
    user = User(
        id="usr_lockout01",
        email="lockout@example.com",
        name="Lockout User",
        organization_id=lockout_org.id,
        password_hash=PasswordService.hash_password(CORRECT_PASSWORD),
        email_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_client(app):
    """Create a test client without auth headers."""
    return TestClient(app)


def _login(client, email, password):
    """Helper to POST login request."""
    return client.post(LOGIN_URL, json={"email": email, "password": password})


class TestAccountLockout:
    """Account lockout after failed login attempts."""

    def test_login_success_resets_counter(self, test_client, lockout_user, db_session):
        """Successful login resets failed_login_attempts to 0."""
        # Set some prior failures
        lockout_user.failed_login_attempts = 3
        db_session.commit()

        resp = _login(test_client, lockout_user.email, CORRECT_PASSWORD)
        assert resp.status_code == 200

        db_session.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == 0
        assert lockout_user.locked_until is None

    def test_lockout_after_max_failures(self, test_client, lockout_user, db_session):
        """Account is locked after 5 failed attempts; 6th returns 423."""
        for i in range(5):
            resp = _login(test_client, lockout_user.email, WRONG_PASSWORD)
            assert resp.status_code == 401, f"Attempt {i + 1} should return 401"

        # 6th attempt should be blocked with 423
        resp = _login(test_client, lockout_user.email, WRONG_PASSWORD)
        assert resp.status_code == 423

    def test_locked_account_returns_423(self, test_client, lockout_user, db_session):
        """A user with locked_until in the future gets 423."""
        lockout_user.locked_until = (utcnow() + timedelta(minutes=10)).replace(tzinfo=None)
        lockout_user.failed_login_attempts = 5
        db_session.commit()

        resp = _login(test_client, lockout_user.email, CORRECT_PASSWORD)
        assert resp.status_code == 423
        assert "temporarily locked" in resp.json()["detail"]

    def test_lockout_expires(self, test_client, lockout_user, db_session):
        """Expired lockout allows login with correct password."""
        lockout_user.locked_until = (utcnow() - timedelta(minutes=1)).replace(tzinfo=None)
        lockout_user.failed_login_attempts = 5
        db_session.commit()

        resp = _login(test_client, lockout_user.email, CORRECT_PASSWORD)
        assert resp.status_code == 200

        db_session.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == 0

    def test_partial_failures_dont_lock(self, test_client, lockout_user, db_session):
        """3 failures then correct password succeeds and resets counter."""
        for _ in range(3):
            resp = _login(test_client, lockout_user.email, WRONG_PASSWORD)
            assert resp.status_code == 401

        resp = _login(test_client, lockout_user.email, CORRECT_PASSWORD)
        assert resp.status_code == 200

        db_session.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == 0

    def test_lockout_message_includes_minutes(self, test_client, lockout_user, db_session):
        """Lockout response includes minutes remaining."""
        lockout_user.locked_until = (utcnow() + timedelta(minutes=10)).replace(tzinfo=None)
        lockout_user.failed_login_attempts = 5
        db_session.commit()

        resp = _login(test_client, lockout_user.email, CORRECT_PASSWORD)
        assert resp.status_code == 423
        assert "minutes" in resp.json()["detail"]

    def test_wrong_password_increments_counter(self, test_client, lockout_user, db_session):
        """A single wrong password increments failed_login_attempts to 1."""
        resp = _login(test_client, lockout_user.email, WRONG_PASSWORD)
        assert resp.status_code == 401

        db_session.refresh(lockout_user)
        assert lockout_user.failed_login_attempts == 1
