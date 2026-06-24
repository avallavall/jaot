"""Integration tests for GET /api/v2/auth/me — Phase 7.1 Plan 01.

Covers D-7.1-06/07 (is_org_owner signal):

    Test A: Seed user is org owner → GET /me → is_org_owner is True
    Test B: Second user in same org (not owner) → is_org_owner is False,
            is_admin preserved
    Test C: Platform admin NOT org owner → is_org_owner is False, is_admin is True
            (proves platform-admin does NOT silently bypass)

Tests run against real PostgreSQL (jaot_test).
Note: User.is_admin is a property (role == "admin"), not a direct column.
      Use role="admin" / role="member" to control admin status.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.user import User
from app.services.auth.api_key_service import APIKeyService

# Auth client helper (same pattern as test_solvers_license.py)


class _AuthClient:
    """TestClient wrapper that injects Authorization header on every request."""

    def __init__(self, inner, token: str) -> None:
        self._inner = inner
        self._headers = {"Authorization": f"Bearer {token}"}

    def _merge(self, kwargs: dict) -> dict:
        merged = dict(self._headers)
        merged.update(kwargs.get("headers", {}) or {})
        kwargs["headers"] = merged
        return kwargs

    def get(self, *a, **kw):
        return self._inner.get(*a, **self._merge(kw))

    def post(self, *a, **kw):
        return self._inner.post(*a, **self._merge(kw))

    def delete(self, *a, **kw):
        return self._inner.delete(*a, **self._merge(kw))


def _make_user_with_key(
    db: Session,
    user_id: str,
    email: str,
    name: str,
    org_id: str,
    role: str = "member",
) -> tuple[User, str]:
    """Create a user + API key; return (user, plaintext_key)."""
    user = User(
        id=user_id,
        email=email,
        name=name,
        organization_id=org_id,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    _, plaintext = APIKeyService.create_api_key(
        db=db,
        user_id=user_id,
        organization_id=org_id,
        name="test-key",
        prefix="ok_test_",
    )
    return user, plaintext


# Test A: org owner → is_org_owner = True


def test_me_returns_is_org_owner_true_for_org_owner(
    client,
    db_session: Session,
) -> None:
    """Test A: Authenticated user IS the org owner → is_org_owner: true."""
    org = Organization(
        id="org_me_owner_a",
        name="Owner Org A",
        credits_balance=200,
        rate_limit_per_minute=999_999,
        rate_limit_per_day=999_999,
    )
    db_session.add(org)
    db_session.flush()

    user, key = _make_user_with_key(
        db=db_session,
        user_id="user_me_owner_a",
        email="owner_a@example.com",
        name="Owner A",
        org_id=org.id,
        role="admin",
    )

    # Set this user as the org owner
    org.owner_user_id = user.id
    db_session.commit()

    auth_client = _AuthClient(client, key)
    resp = auth_client.get("/api/v2/auth/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_org_owner"] is True
    assert body["user_id"] == user.id
    assert body["organization_id"] == org.id


# Test B: non-owner member in same org → is_org_owner = False


def test_me_returns_is_org_owner_false_for_non_owner(
    client,
    db_session: Session,
) -> None:
    """Test B: Second user in same org (not owner) → is_org_owner: false.

    Confirms is_admin is preserved independently of is_org_owner.
    """
    org = Organization(
        id="org_me_nonowner_b",
        name="Non-Owner Org B",
        credits_balance=200,
        rate_limit_per_minute=999_999,
        rate_limit_per_day=999_999,
    )
    db_session.add(org)
    db_session.flush()

    # User B1 = owner (role=admin)
    user_b1, _ = _make_user_with_key(
        db=db_session,
        user_id="user_me_b1_owner",
        email="b1_owner@example.com",
        name="B1 Owner",
        org_id=org.id,
        role="admin",
    )
    org.owner_user_id = user_b1.id
    db_session.flush()

    # User B2 = non-owner member (role=member → is_admin=False)
    user_b2, key_b2 = _make_user_with_key(
        db=db_session,
        user_id="user_me_b2_nonowner",
        email="b2_nonowner@example.com",
        name="B2 Non-Owner",
        org_id=org.id,
        role="member",
    )
    db_session.commit()

    auth_client = _AuthClient(client, key_b2)
    resp = auth_client.get("/api/v2/auth/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_org_owner"] is False
    # is_admin must be False for a member role (independent of is_org_owner)
    assert body["is_admin"] is False


# Test C: platform admin NOT org owner → is_org_owner=False, is_admin=True


def test_me_returns_is_org_owner_false_for_cross_org_platform_admin(
    client,
    db_session: Session,
) -> None:
    """Test C: Platform admin (role="admin", is_admin=True) who is NOT the org owner.

    This test closes D-7.1-07: platform admins must NOT silently bypass
    the is_org_owner check. is_admin can be True while is_org_owner=False.
    """
    org_c = Organization(
        id="org_me_plat_c",
        name="Plat Admin Org C",
        credits_balance=200,
        rate_limit_per_minute=999_999,
        rate_limit_per_day=999_999,
    )
    db_session.add(org_c)
    db_session.flush()

    # user_c1 is the actual org owner (role=member — owner_user_id is the authority)
    user_c1, _ = _make_user_with_key(
        db=db_session,
        user_id="user_me_c1_owner",
        email="c1_owner@example.com",
        name="C1 Owner",
        org_id=org_c.id,
        role="member",
    )
    org_c.owner_user_id = user_c1.id
    db_session.flush()

    # user_c2 is a platform admin (role="admin" → is_admin=True) but NOT the org owner
    user_c2, key_c2 = _make_user_with_key(
        db=db_session,
        user_id="user_me_c2_platadmin",
        email="c2_platadmin@example.com",
        name="C2 Platform Admin",
        org_id=org_c.id,
        role="admin",  # platform admin: is_admin=True
    )
    db_session.commit()

    auth_client = _AuthClient(client, key_c2)
    resp = auth_client.get("/api/v2/auth/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Critical assertions: platform admin is NOT silently the org owner
    assert body["is_org_owner"] is False, (
        "Platform admin with is_admin=True must NOT inherit is_org_owner=True "
        "(D-7.1-07: no silent bypass)"
    )
    assert body["is_admin"] is True, "is_admin must remain True for platform admin (role=admin)"
