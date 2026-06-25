"""Tests for D-16: Seller ToS must be accepted before withdrawal."""

import pytest
from sqlalchemy.orm import Session

from app.models import Organization, SellerToSAcceptance, User
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture(autouse=True)
def _enable_monetization(enable_monetization):
    """Withdrawal endpoints are paid-only; enable monetization for this module."""


class TestWithdrawalTosCheck:
    """Verify that withdrawal requires Seller ToS acceptance (D-16)."""

    def _setup_seller(self, db_session: Session, *, tos_accepted: bool = False):
        """Create a seller org with earned credits and optionally accepted ToS."""
        org = Organization(
            id="tos-seller-org",
            name="ToS Seller",
            credits_balance=5000,
            credits_earned=5000,
            stripe_connect_onboarding_complete=True,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        user = User(
            id="tos-seller-user",
            email="tos-seller@test.com",
            name="ToS Seller User",
            organization_id=org.id,
            is_active=True,
        )
        db_session.add(user)

        if tos_accepted:
            acceptance = SellerToSAcceptance(
                id=generate_id("tos_"),
                organization_id=org.id,
                tos_version="1.0",
                accepted_at=utcnow(),
                accepted_by_user_id=user.id,
            )
            db_session.add(acceptance)

        db_session.commit()
        return org, user

    def test_withdrawal_rejected_without_tos(self, db_session: Session, client, mock_auth):
        """POST /api/v2/credits/withdrawals returns 403 when ToS not accepted."""
        org, user = self._setup_seller(db_session, tos_accepted=False)
        mock_auth(user)

        response = client.post(
            "/api/v2/credits/withdrawals",
            json={"credits_amount": 100},
        )

        assert response.status_code == 403
        assert "Seller Terms of Service" in response.json()["detail"]

    def test_withdrawal_allowed_with_tos(self, db_session: Session, client, mock_auth):
        """POST /api/v2/credits/withdrawals passes the ToS gate once ToS is accepted.

        The request below is under the 500-credit minimum, so it will be
        rejected with 400 — but the rejection MUST be a business-rule error,
        not a ToS error or a 500 server crash.
        """
        org, user = self._setup_seller(db_session, tos_accepted=True)
        mock_auth(user)

        response = client.post(
            "/api/v2/credits/withdrawals",
            json={"credits_amount": 100},
        )

        # ToS gate was passed — no 403 and no 5xx.
        assert response.status_code < 500, f"Unexpected 5xx: {response.json()}"
        assert response.status_code != 403, f"ToS gate regression: {response.json()}"
        # 100 credits is below the 500-credit minimum, so 400 is expected.
        assert response.status_code == 400
        detail = response.json()["detail"]
        # Must be a business-rule error, not a ToS error.
        assert "Terms of Service" not in detail
        assert "Minimum" in detail or "minimum" in detail


class TestWithdrawalCrossTenantIsolation:
    """Gap filled per audit missing-test #5 (withdrawal cross-tenant auth).

    Two orgs each create a withdrawal. Org A authenticated must see only
    org A's withdrawal in GET /api/v2/credits/withdrawals and must NOT see
    org B's withdrawal. The list is already filtered by organization_id
    server-side — this test locks that behaviour in.
    """

    def test_list_withdrawals_does_not_leak_other_org(self, db_session, client, mock_auth):
        from app.models import Withdrawal
        from app.shared.utils.id_generator import generate_id

        # ----- Seller A -----
        org_a = Organization(
            id=generate_id("org_"),
            name="Tenant A",
            credits_balance=5000,
            credits_earned=5000,
            stripe_connect_onboarding_complete=True,
            currency="EUR",
        )
        db_session.add(org_a)
        db_session.flush()
        user_a = User(
            id=generate_id("usr_"),
            email="user-a@tenant.test",
            name="User A",
            organization_id=org_a.id,
            is_active=True,
        )
        db_session.add(user_a)
        db_session.add(
            SellerToSAcceptance(
                id=generate_id("tos_"),
                organization_id=org_a.id,
                tos_version="1.0",
                accepted_at=utcnow(),
                accepted_by_user_id=user_a.id,
            )
        )

        # ----- Seller B -----
        org_b = Organization(
            id=generate_id("org_"),
            name="Tenant B",
            credits_balance=5000,
            credits_earned=5000,
            stripe_connect_onboarding_complete=True,
            currency="EUR",
        )
        db_session.add(org_b)
        db_session.flush()
        user_b = User(
            id=generate_id("usr_"),
            email="user-b@tenant.test",
            name="User B",
            organization_id=org_b.id,
            is_active=True,
        )
        db_session.add(user_b)
        db_session.add(
            SellerToSAcceptance(
                id=generate_id("tos_"),
                organization_id=org_b.id,
                tos_version="1.0",
                accepted_at=utcnow(),
                accepted_by_user_id=user_b.id,
            )
        )

        # Seed one withdrawal per org directly in the DB.
        wd_a = Withdrawal(
            id=generate_id("wdr_"),
            organization_id=org_a.id,
            withdrawal_type="bank_transfer",
            credits_amount=500,
            eur_amount=50.0,
            target_currency="EUR",
            exchange_rate=1.0,
            local_amount=50.0,
            status="pending",
            created_at=utcnow(),
        )
        wd_b = Withdrawal(
            id=generate_id("wdr_"),
            organization_id=org_b.id,
            withdrawal_type="bank_transfer",
            credits_amount=700,
            eur_amount=70.0,
            target_currency="EUR",
            exchange_rate=1.0,
            local_amount=70.0,
            status="pending",
            created_at=utcnow(),
        )
        db_session.add(wd_a)
        db_session.add(wd_b)
        db_session.commit()

        # Authenticated as user_a — must NOT see wd_b.
        mock_auth(user_a)
        resp = client.get("/api/v2/credits/withdrawals")
        assert resp.status_code == 200
        items = resp.json()
        ids = [item["id"] for item in items]
        assert wd_a.id in ids, "Own org withdrawal missing from list"
        assert wd_b.id not in ids, (
            f"Cross-tenant leak: tenant A saw tenant B's withdrawal {wd_b.id}"
        )
        # Every returned row belongs to org_a, never org_b.
        for item in items:
            assert item["credits_amount"] != 700, (
                "Org B's 700-credit withdrawal leaked into org A's response"
            )

        # Flip authentication to user_b — mirror check.
        mock_auth(user_b)
        resp = client.get("/api/v2/credits/withdrawals")
        assert resp.status_code == 200
        items = resp.json()
        ids = [item["id"] for item in items]
        assert wd_b.id in ids
        assert wd_a.id not in ids, (
            f"Cross-tenant leak: tenant B saw tenant A's withdrawal {wd_a.id}"
        )
