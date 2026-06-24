"""Tests for verification request, approve, and reject workflows.

Covers:
- Successful verification request creates pending entry
- Duplicate request returns 409
- Admin approve sets Organization.is_verified=True
- Admin reject sets status to rejected
- Verified badge: after approval, org is_verified flag is True
"""

import pytest
from fastapi import HTTPException

from app.models import Organization, User
from app.models.verification_request import VerificationStatus
from app.services.verification_service import VerificationService


@pytest.fixture
def verify_org(db_session):
    """Create an organization for verification tests."""
    org = Organization(
        id="org_verify001",
        name="Verify Corp",
        credits_balance=1000,
        credits_earned=0,
        is_active=True,
        is_verified=False,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def verify_user(db_session, verify_org):
    """Create a user for verification tests."""
    user = User(
        id="user_verify001",
        email="verify@example.com",
        name="Verify User",
        organization_id=verify_org.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


class TestRequestVerification:
    """Test verification request submission."""

    def test_successful_request_creates_pending(self, db_session, verify_org, verify_user):
        """Submitting a verification request creates a pending entry."""
        service = VerificationService(db_session)
        req = service.request_verification(
            org_id=verify_org.id,
            user_id=verify_user.id,
        )
        db_session.commit()

        assert req is not None
        assert req.status == VerificationStatus.PENDING.value
        assert req.organization_id == verify_org.id

    def test_duplicate_request_returns_409(self, db_session, verify_org, verify_user):
        """Submitting a second request while one is pending raises 409."""
        service = VerificationService(db_session)
        service.request_verification(
            org_id=verify_org.id,
            user_id=verify_user.id,
        )
        db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            service.request_verification(
                org_id=verify_org.id,
                user_id=verify_user.id,
            )
        assert exc_info.value.status_code == 409


class TestAdminVerification:
    """Test admin approve and reject workflows."""

    def test_approve_sets_org_verified(self, db_session, verify_org, verify_user):
        """Approving a request sets Organization.is_verified=True."""
        service = VerificationService(db_session)
        req = service.request_verification(
            org_id=verify_org.id,
            user_id=verify_user.id,
        )
        db_session.commit()

        service.approve(req.id, "admin_001", note="Looks good")
        db_session.commit()

        db_session.refresh(req)
        assert req.status == VerificationStatus.APPROVED.value

        db_session.refresh(verify_org)
        assert verify_org.is_verified is True

    def test_reject_sets_status_rejected(self, db_session, verify_org, verify_user):
        """Rejecting a request sets status to rejected."""
        service = VerificationService(db_session)
        req = service.request_verification(
            org_id=verify_org.id,
            user_id=verify_user.id,
        )
        db_session.commit()

        service.reject(req.id, "admin_001", note="Incomplete profile")
        db_session.commit()

        db_session.refresh(req)
        assert req.status == VerificationStatus.REJECTED.value
        assert req.admin_note == "Incomplete profile"


class TestVerifiedBadge:
    """Test that verification approval leads to badge display."""

    def test_org_is_verified_after_approval(self, db_session, verify_org, verify_user):
        """After approval, the org's is_verified flag is True for badge rendering."""
        assert verify_org.is_verified is False

        service = VerificationService(db_session)
        req = service.request_verification(
            org_id=verify_org.id,
            user_id=verify_user.id,
        )
        db_session.commit()

        service.approve(req.id, "admin_001")
        db_session.commit()

        db_session.refresh(verify_org)
        assert verify_org.is_verified is True
