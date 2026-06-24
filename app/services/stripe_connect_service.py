"""Stripe Connect Express service for seller payouts.

Per D-02: Stripe Connect Express is the ONLY payout mechanism.
Platform never touches seller funds directly.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import Organization, SellerToSAcceptance
from app.services.stripe_service import _get_stripe
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)


class StripeConnectService:
    """Manages Stripe Connect Express accounts for seller payouts."""

    def __init__(self, db: Session):
        self.db = db

    def create_connect_account(self, org: Organization) -> str:
        """Create a Stripe Connect Express account for a seller org.

        Per D-03: Adds stripe_connect_account_id to Organization.
        Per D-05: Called when seller clicks "Configure payment account".

        Args:
            org: The seller organization.

        Returns:
            The Stripe Connect account ID (acct_xxx).

        Raises:
            ValueError: If org already has a Connect account.
        """
        if org.stripe_connect_account_id:
            return org.stripe_connect_account_id  # Idempotent

        stripe = _get_stripe()
        account = stripe.Account.create(
            type="express",
            country="ES",  # Default to platform country (EUR-only launch)
            capabilities={"transfers": {"requested": True}},
            metadata={"organization_id": org.id},
        )

        org.stripe_connect_account_id = account.id
        self.db.flush()

        logger.info(f"Created Connect account {account.id} for org {org.id}")
        return account.id

    def create_onboarding_link(
        self,
        org: Organization,
        return_url: str,
        refresh_url: str,
    ) -> str:
        """Generate a Stripe Express onboarding link.

        Per Pitfall 4: Account Links are single-use and expire.
        Always generate a fresh one when the seller clicks "Configure payment account."

        Args:
            org: The seller organization (must have stripe_connect_account_id).
            return_url: URL to redirect after onboarding completes.
            refresh_url: URL to redirect if the link expires (generates a new one).

        Returns:
            The onboarding URL to redirect the seller to.
        """
        if not org.stripe_connect_account_id:
            raise ValueError("No Stripe Connect account. Call create_connect_account first.")

        stripe = _get_stripe()
        link = stripe.AccountLink.create(
            account=org.stripe_connect_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type="account_onboarding",
        )

        return link.url

    def get_account_status(self, org: Organization) -> dict[str, Any]:
        """Check the current status of a Connect account.

        Returns:
            Dict with charges_enabled, payouts_enabled, onboarding_complete.
        """
        if not org.stripe_connect_account_id:
            return {
                "has_account": False,
                "charges_enabled": False,
                "payouts_enabled": False,
                "onboarding_complete": False,
            }

        stripe = _get_stripe()
        try:
            account = stripe.Account.retrieve(org.stripe_connect_account_id)
            onboarding_complete = getattr(account, "charges_enabled", False) and getattr(
                account, "payouts_enabled", False
            )

            # Sync local state if Stripe says onboarding is complete
            if onboarding_complete and not org.stripe_connect_onboarding_complete:
                org.stripe_connect_onboarding_complete = True
                self.db.flush()

            return {
                "has_account": True,
                "account_id": org.stripe_connect_account_id,
                "charges_enabled": getattr(account, "charges_enabled", False),
                "payouts_enabled": getattr(account, "payouts_enabled", False),
                "onboarding_complete": onboarding_complete,
            }
        except Exception as e:
            logger.error(f"Failed to retrieve Connect account {org.stripe_connect_account_id}: {e}")
            return {
                "has_account": True,
                "account_id": org.stripe_connect_account_id,
                "error": str(e),
                "onboarding_complete": org.stripe_connect_onboarding_complete,
            }

    def create_payout(
        self,
        org: Organization,
        amount_eur: float,
        withdrawal_id: str,
    ) -> str:
        """Create a Stripe Transfer to the seller's Connect account.

        Per D-02: Platform never touches seller funds directly.

        Args:
            org: Seller organization (must have completed onboarding).
            amount_eur: Amount in EUR to transfer.
            withdrawal_id: Reference to the Withdrawal record.

        Returns:
            Stripe Transfer ID.
        """
        if not org.stripe_connect_account_id:
            raise ValueError("No Stripe Connect account")

        if not org.stripe_connect_onboarding_complete:
            raise ValueError("Stripe Connect onboarding not complete")

        stripe = _get_stripe()
        transfer = stripe.Transfer.create(
            amount=int(amount_eur * 100),  # Stripe uses cents
            currency="eur",
            destination=org.stripe_connect_account_id,
            metadata={
                "withdrawal_id": withdrawal_id,
                "organization_id": org.id,
            },
        )

        logger.info(
            f"Payout created: transfer={transfer.id}, org={org.id}, "
            f"amount={amount_eur:.2f} EUR, withdrawal={withdrawal_id}"
        )
        return transfer.id

    def accept_seller_tos(
        self,
        organization_id: str,
        user_id: str,
        tos_version: str = "1.0",
    ) -> SellerToSAcceptance:
        """Record seller ToS acceptance (per D-16).

        Required before first withdrawal, not before publishing.

        Args:
            organization_id: The seller organization.
            user_id: The user accepting on behalf of the org.
            tos_version: Version of the ToS being accepted.

        Returns:
            The SellerToSAcceptance record.
        """
        existing = (
            self.db.query(SellerToSAcceptance)
            .filter(
                SellerToSAcceptance.organization_id == organization_id,
                SellerToSAcceptance.tos_version == tos_version,
            )
            .first()
        )
        if existing:
            return existing  # Idempotent

        acceptance = SellerToSAcceptance(
            id=generate_id("tos_"),
            organization_id=organization_id,
            tos_version=tos_version,
            accepted_at=utcnow(),
            accepted_by_user_id=user_id,
        )
        self.db.add(acceptance)
        self.db.flush()

        logger.info(f"Seller ToS v{tos_version} accepted: org={organization_id}, user={user_id}")
        return acceptance

    def has_accepted_seller_tos(self, organization_id: str) -> bool:
        """Check if org has accepted the current Seller ToS version."""
        return (
            self.db.query(SellerToSAcceptance)
            .filter(SellerToSAcceptance.organization_id == organization_id)
            .first()
        ) is not None
