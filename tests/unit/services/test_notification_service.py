"""Unit tests for NotificationService — Phase 7.1 Plan 01.

Covers:
  - Task 1 (TDD RED): schema + service signature for reference_type/reference_id
  - Task 2 (TDD RED → GREEN): test_create_notification_persists_reference_pair (Test G)

Tests run against real PostgreSQL (jaot_test). SAVEPOINT / flush() pattern.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.notification import Notification, NotificationType
from app.models.organization import Organization
from app.models.user import User
from app.services.notification_service import NotificationService

# Fixtures — minimal org + user sufficient for Notification FK constraints


@pytest.fixture
def notif_org(db_session: Session) -> Organization:
    org = Organization(
        id="org_notif01",
        name="Notif Test Org",
        credits_balance=100,
        rate_limit_per_minute=999_999,
        rate_limit_per_day=999_999,
    )
    db_session.add(org)
    db_session.flush()
    return org


@pytest.fixture
def notif_user(db_session: Session, notif_org: Organization) -> User:
    user = User(
        id="user_notif01",
        email="notif_user@example.com",
        name="Notif User",
        organization_id=notif_org.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


# Test 3 (Task 1, TDD RED → GREEN):
# create_notification with reference_type + reference_id persists both columns.


def test_create_notification_persists_reference_pair(
    db_session: Session,
    notif_org: Organization,
    notif_user: User,
) -> None:
    """Test G / Test 3: reference_type + reference_id kwargs are persisted.

    Corresponds to D-7.1-12: NotificationService.create_notification gains
    optional reference_type + reference_id kwargs for per-license dedup.
    """
    svc = NotificationService(db_session)
    notif = svc.create_notification(
        user_id=notif_user.id,
        organization_id=notif_org.id,
        notification_type=NotificationType.SYSTEM,
        title="Resource expiring",
        message="A linked resource expires in 7 days.",
        reference_type="solver_license",
        reference_id="lic_abc123",
    )

    assert notif.id is not None
    # Reload from DB to confirm persistence (not just in-session state)
    db_session.flush()
    fetched = db_session.query(Notification).filter(Notification.id == notif.id).one()
    assert fetched.reference_type == "solver_license"
    assert fetched.reference_id == "lic_abc123"


# Test 4 (Task 1, TDD RED → GREEN):
# Existing callers without the new kwargs continue working — backward compat.


def test_create_notification_backward_compat_no_reference(
    db_session: Session,
    notif_org: Organization,
    notif_user: User,
) -> None:
    """Test 4: Old-style call (no reference_type/reference_id) still works.

    Stored row has reference_type = reference_id = NULL.
    """
    svc = NotificationService(db_session)
    notif = svc.create_notification(
        user_id=notif_user.id,
        organization_id=notif_org.id,
        notification_type=NotificationType.EXECUTION_COMPLETED,
        title="Job done",
        message="Your solve completed.",
    )

    assert notif.id is not None
    db_session.flush()
    fetched = db_session.query(Notification).filter(Notification.id == notif.id).one()
    assert fetched.reference_type is None
    assert fetched.reference_id is None


# Test 5 (Task 1, TDD RED → GREEN):
# MeResponse schema validates is_org_owner: bool (default False).


def test_me_response_schema_has_is_org_owner() -> None:
    """Test 5: MeResponse schema accepts is_org_owner: bool, defaults to False."""
    from app.schemas.auth import MeResponse, PlanLimitsResponse

    limits = PlanLimitsResponse(
        max_variables=500,
        max_solve_time_seconds=60,
        max_daily_solves=10,
        allowed_features=["basic"],
    )

    # Roundtrip with is_org_owner=True
    resp_owner = MeResponse(
        user_id="u1",
        user_name="Alice",
        user_email="alice@example.com",
        organization_id="org_x",
        organization_name="Acme",
        plan="free",
        credits_balance=100,
        is_admin=False,
        can_build_plugins=False,
        is_org_owner=True,
        plan_limits=limits,
    )
    assert resp_owner.is_org_owner is True

    # Roundtrip with is_org_owner=False (explicit)
    resp_non_owner = MeResponse(
        user_id="u2",
        user_name="Bob",
        user_email="bob@example.com",
        organization_id="org_x",
        organization_name="Acme",
        plan="free",
        credits_balance=100,
        is_admin=True,
        can_build_plugins=False,
        is_org_owner=False,
        plan_limits=limits,
    )
    assert resp_non_owner.is_org_owner is False

    # Roundtrip without is_org_owner → defaults to False
    resp_default = MeResponse(
        user_id="u3",
        user_name="Carol",
        user_email="carol@example.com",
        organization_id="org_x",
        organization_name="Acme",
        plan="free",
        credits_balance=100,
        is_admin=False,
        can_build_plugins=False,
        plan_limits=limits,
    )
    assert resp_default.is_org_owner is False

    # Serialization round-trip: the field appears in the JSON output
    dumped = resp_owner.model_dump()
    assert "is_org_owner" in dumped
    assert dumped["is_org_owner"] is True
