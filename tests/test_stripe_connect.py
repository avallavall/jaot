"""Tests for Stripe Connect service (Phase 10).

Covers: FIN-08, D-03, D-05, D-16.
Verifies: Express account creation, ToS acceptance tracking,
onboarding idempotency.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models import Organization, SellerToSAcceptance
from app.services.stripe_connect_service import StripeConnectService
from app.shared.utils.id_generator import generate_id


class TestConnectAccountCreation:
    """D-03: Create Stripe Connect Express account for sellers."""

    @patch("app.services.stripe_connect_service._get_stripe")
    def test_create_connect_account(self, mock_get_stripe, db_session):
        """Creates Express account and sets stripe_connect_account_id."""
        mock_stripe = MagicMock()
        mock_get_stripe.return_value = mock_stripe
        mock_stripe.Account.create.return_value = MagicMock(id="acct_test123")

        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        account_id = service.create_connect_account(org)

        assert account_id == "acct_test123"
        db_session.refresh(org)
        assert org.stripe_connect_account_id == "acct_test123"

        # Verify Stripe API was called correctly
        mock_stripe.Account.create.assert_called_once()
        call_kwargs = mock_stripe.Account.create.call_args[1]
        assert call_kwargs["type"] == "express"
        assert call_kwargs["country"] == "ES"

    def test_create_connect_account_idempotent(self, db_session):
        """Second call returns existing account ID without Stripe API call."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_account_id="acct_existing",
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        # Should NOT call Stripe API
        account_id = service.create_connect_account(org)
        assert account_id == "acct_existing"

    @patch("app.services.stripe_connect_service._get_stripe")
    def test_create_onboarding_link(self, mock_get_stripe, db_session):
        """Generate onboarding link for existing Connect account.

        Asserts the exact URL and that AccountLink.create was called with
        the exact return_url / refresh_url / account / type kwargs.
        """
        expected_url = "https://connect.stripe.com/setup/e/acct_test/link"
        mock_stripe = MagicMock()
        mock_get_stripe.return_value = mock_stripe
        mock_stripe.AccountLink.create.return_value = MagicMock(url=expected_url)

        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_account_id="acct_test",
        )
        db_session.add(org)
        db_session.flush()

        return_url = "https://app.example.com/settings"
        refresh_url = "https://app.example.com/settings/refresh"

        service = StripeConnectService(db_session)
        url = service.create_onboarding_link(
            org,
            return_url=return_url,
            refresh_url=refresh_url,
        )
        assert url == expected_url

        # Verify the call kwargs so we know we're not just asserting the mock
        # value back at ourselves.
        mock_stripe.AccountLink.create.assert_called_once()
        kwargs = mock_stripe.AccountLink.create.call_args.kwargs
        assert kwargs["account"] == "acct_test"
        assert kwargs["return_url"] == return_url
        assert kwargs["refresh_url"] == refresh_url
        assert kwargs["type"] == "account_onboarding"

    def test_create_onboarding_link_no_account_raises(self, db_session):
        """Onboarding link without Connect account raises ValueError."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        with pytest.raises(ValueError, match="No Stripe Connect account"):
            service.create_onboarding_link(
                org,
                return_url="https://example.com/return",
                refresh_url="https://example.com/refresh",
            )


class TestToSAcceptance:
    """D-16: Seller ToS acceptance tracking."""

    def test_accept_tos_creates_record(self, db_session):
        """accept_seller_tos creates SellerToSAcceptance record."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        acceptance = service.accept_seller_tos(
            organization_id=org.id,
            user_id="user_test",
            tos_version="1.0",
        )

        assert acceptance is not None
        assert acceptance.organization_id == org.id
        assert acceptance.tos_version == "1.0"
        assert acceptance.accepted_by_user_id == "user_test"

        # Verify in DB
        record = (
            db_session.query(SellerToSAcceptance)
            .filter(SellerToSAcceptance.organization_id == org.id)
            .first()
        )
        assert record is not None

    def test_accept_tos_idempotent(self, db_session):
        """Second acceptance of same version returns existing."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        acceptance1 = service.accept_seller_tos(
            organization_id=org.id,
            user_id="user_test",
            tos_version="1.0",
        )
        acceptance2 = service.accept_seller_tos(
            organization_id=org.id,
            user_id="user_test",
            tos_version="1.0",
        )
        assert acceptance1.id == acceptance2.id

        # Only one record in DB
        count = (
            db_session.query(SellerToSAcceptance)
            .filter(SellerToSAcceptance.organization_id == org.id)
            .count()
        )
        assert count == 1

    def test_has_accepted_tos_false_before(self, db_session):
        """has_accepted_seller_tos returns False before acceptance."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        assert service.has_accepted_seller_tos(org.id) is False

    def test_has_accepted_tos_true_after(self, db_session):
        """has_accepted_seller_tos returns True after acceptance."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=0,
            credits_earned=0,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        service.accept_seller_tos(
            organization_id=org.id,
            user_id="user_test",
            tos_version="1.0",
        )
        assert service.has_accepted_seller_tos(org.id) is True


class TestPayoutExecution:
    """D-02: Stripe Connect payout via Transfer."""

    @patch("app.services.stripe_connect_service._get_stripe")
    def test_create_payout_success(self, mock_get_stripe, db_session):
        """create_payout creates Stripe Transfer to seller."""
        mock_stripe = MagicMock()
        mock_get_stripe.return_value = mock_stripe
        mock_stripe.Transfer.create.return_value = MagicMock(id="tr_test123")

        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=500,
            credits_earned=500,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_account_id="acct_seller",
            stripe_connect_onboarding_complete=True,
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        transfer_id = service.create_payout(
            org=org,
            amount_eur=50.0,
            withdrawal_id="wd_test123",
        )

        assert transfer_id == "tr_test123"
        mock_stripe.Transfer.create.assert_called_once()
        call_kwargs = mock_stripe.Transfer.create.call_args[1]
        assert call_kwargs["amount"] == 5000  # 50 EUR * 100 cents
        assert call_kwargs["currency"] == "eur"
        assert call_kwargs["destination"] == "acct_seller"

    def test_create_payout_no_account_raises(self, db_session):
        """Payout without Connect account raises ValueError."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=500,
            credits_earned=500,
            monthly_quota=100,
            currency="EUR",
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        with pytest.raises(ValueError, match="No Stripe Connect account"):
            service.create_payout(org=org, amount_eur=50.0, withdrawal_id="wd_test")

    def test_create_payout_incomplete_onboarding_raises(self, db_session):
        """Payout with incomplete onboarding raises ValueError."""
        org = Organization(
            id=generate_id("org_"),
            name="Seller",
            credits_balance=500,
            credits_earned=500,
            monthly_quota=100,
            currency="EUR",
            stripe_connect_account_id="acct_incomplete",
            stripe_connect_onboarding_complete=False,
        )
        db_session.add(org)
        db_session.flush()

        service = StripeConnectService(db_session)
        with pytest.raises(ValueError, match="onboarding not complete"):
            service.create_payout(org=org, amount_eur=50.0, withdrawal_id="wd_test")
