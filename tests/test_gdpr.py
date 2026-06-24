"""GDPR compliance tests: data export, account deletion, ToS acceptance."""

import pytest
from sqlalchemy.orm import Session

from app.models import (
    APIKey,
    CreditTransaction,
    Notification,
    Organization,
    RefreshToken,
    User,
)
from app.services.auth import PasswordService
from app.shared.utils.datetime_helpers import utcnow


def _make_user_with_password(db: Session, org: Organization, suffix: str = "") -> User:
    """Create a user with a password hash for deletion tests."""
    pw_hash = PasswordService.hash_password("TestPass123!")
    user = User(
        id=f"usr_gdpr{suffix}",
        email=f"gdpr{suffix}@example.com",
        name=f"GDPR User {suffix}",
        organization_id=org.id,
        role="admin",
        password_hash=pw_hash,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _seed_related_records(db: Session, user: User, org: Organization) -> None:
    """Seed child records that should be cascade-deleted."""
    from app.services.auth.api_key_service import APIKeyService

    APIKeyService.create_api_key(
        db=db,
        user_id=user.id,
        organization_id=org.id,
        name="gdpr-key",
        prefix="ok_gdpr_",
    )
    db.add(
        Notification(
            id="ntf_gdpr01",
            user_id=user.id,
            organization_id=org.id,
            title="Test notification",
            message="msg",
            type="info",
        )
    )
    db.add(
        CreditTransaction(
            id="txn_gdpr01",
            organization_id=org.id,
            credits_amount=10,
            balance_after=10,
            description="seed",
            transaction_type="credit",
        )
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            jti="jti_gdpr01",
            expires_at=utcnow().replace(tzinfo=None),
        )
    )
    db.flush()


class TestDataExport:
    """GET /api/v2/user/data-export"""

    def test_data_export_returns_json_file(
        self, client, db_session, test_user, test_organization, mock_auth
    ):
        mock_auth(test_user)
        resp = client.get("/api/v2/user/data-export")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
        data = resp.json()
        assert "user" in data
        assert "organization" in data
        assert "models" in data

    def test_data_export_unauthenticated(self, client):
        resp = client.get("/api/v2/user/data-export")
        assert resp.status_code == 401

    def test_data_export_includes_all_sections(
        self, client, db_session, test_user, test_organization, mock_auth
    ):
        mock_auth(test_user)
        resp = client.get("/api/v2/user/data-export")
        data = resp.json()
        for key in [
            "exported_at",
            "user",
            "organization",
            "models",
            "executions",
            "credit_transactions",
            "api_keys",
            "notifications",
        ]:
            assert key in data, f"Missing key: {key}"

    def test_data_export_no_secrets(
        self, client, db_session, test_user, test_organization, mock_auth
    ):
        """API keys in export must NOT contain key_hash or plaintext."""
        from app.services.auth.api_key_service import APIKeyService

        APIKeyService.create_api_key(
            db=db_session,
            user_id=test_user.id,
            organization_id=test_organization.id,
            name="export-key",
            prefix="ok_test_",
        )
        db_session.flush()

        mock_auth(test_user)
        resp = client.get("/api/v2/user/data-export")
        data = resp.json()
        for ak in data["api_keys"]:
            assert "key_hash" not in ak
            assert "plaintext" not in ak


class TestAccountDeletion:
    """DELETE /api/v2/user/account"""

    def test_account_deletion_success(self, client, db_session, test_organization, mock_auth):
        user = _make_user_with_password(db_session, test_organization, "del1")
        db_session.commit()
        mock_auth(user)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "TestPass123!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 200

        # User no longer in DB
        assert db_session.get(User, user.id) is None

    def test_account_deletion_wrong_password(
        self, client, db_session, test_organization, mock_auth
    ):
        user = _make_user_with_password(db_session, test_organization, "del2")
        db_session.commit()
        mock_auth(user)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "WrongPassword!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 401

    def test_account_deletion_sole_member_deletes_org(self, client, db_session, mock_auth):
        """If user is sole org member, the org must be deleted too."""
        org = Organization(
            id="org_sole01",
            name="Sole Org",
            credits_balance=100,
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()

        user = _make_user_with_password(db_session, org, "sole1")
        db_session.commit()
        mock_auth(user)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "TestPass123!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 200
        assert db_session.get(Organization, "org_sole01") is None

    def test_account_deletion_multi_member_preserves_org(
        self, client, db_session, test_organization, mock_auth
    ):
        """If other users exist in org, org is preserved."""
        user1 = _make_user_with_password(db_session, test_organization, "multi1")
        # second user in same org
        user2 = User(
            id="usr_gdprmulti2",
            email="gdprmulti2@example.com",
            name="Other",
            organization_id=test_organization.id,
            role="member",
            is_active=True,
        )
        db_session.add(user2)
        db_session.commit()
        mock_auth(user1)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "TestPass123!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 200
        # Org preserved
        assert db_session.get(Organization, test_organization.id) is not None
        # Deleted user gone
        assert db_session.get(User, user1.id) is None

    def test_account_deletion_cascading(self, client, db_session, mock_auth):
        """After deletion, no orphaned records."""
        org = Organization(
            id="org_casc01",
            name="Cascade Org",
            credits_balance=100,
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()

        user = _make_user_with_password(db_session, org, "casc1")
        _seed_related_records(db_session, user, org)
        db_session.commit()
        mock_auth(user)

        resp = client.request(
            "DELETE",
            "/api/v2/user/account",
            json={"password": "TestPass123!", "confirmation": "DELETE"},
        )
        assert resp.status_code == 200

        # All related records gone
        assert db_session.query(APIKey).filter_by(user_id="usr_gdprcasc1").count() == 0
        assert db_session.query(Notification).filter_by(user_id="usr_gdprcasc1").count() == 0
        assert db_session.query(RefreshToken).filter_by(user_id="usr_gdprcasc1").count() == 0


@pytest.mark.usefixtures("enable_registration")
class TestTosAcceptance:
    """POST /api/v2/auth/signup/email sets tos_accepted_at."""

    def test_signup_sets_tos_accepted_at(self, client, db_session):
        resp = client.post(
            "/api/v2/auth/signup/email",
            json={
                "email": "tos@example.com",
                "name": "ToS User",
                "organization_name": "ToS Org",
                "password": "SecurePass1!",
                "confirm_password": "SecurePass1!",
                "tos_accepted": True,
            },
        )
        assert resp.status_code == 201
        user = db_session.query(User).filter_by(email="tos@example.com").first()
        assert user is not None
        assert user.tos_accepted_at is not None
