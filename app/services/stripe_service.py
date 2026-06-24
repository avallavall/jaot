"""
Stripe payment service.

Handles subscription management, credit top-up purchases, and webhook processing.
All Stripe interactions are centralized here.

Configuration:
    Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET in .env
    Set STRIPE_PRICE_IDS for each plan/top-up in .env

Usage:
    service = StripeService(db)
    session = service.create_checkout_session(org, plan="pro")
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import CreditTransaction, Organization, TransactionType

logger = logging.getLogger(__name__)

# Lazy import stripe — only fails when actually called, not at module load
_stripe = None


def _get_stripe() -> Any:
    """Lazy-load stripe module. Raises clear error if not installed."""
    global _stripe
    if _stripe is None:
        try:
            import stripe

            _stripe = stripe
        except ImportError as e:
            raise RuntimeError("stripe package not installed. Run: pip install stripe") from e
    return _stripe


# Plan name -> Stripe Price ID mapping (set via env vars)
PLAN_PRICE_IDS: dict[str, str] = {}

# Credit top-up package -> Stripe Price ID mapping
TOPUP_PRICE_IDS: dict[int, str] = {}

# Credits granted per top-up package
TOPUP_CREDITS: dict[int, int] = {
    500: 500,
    2000: 2000,
    5000: 5000,
    20000: 20000,
}

# Plan -> monthly subscription credits. Used ONLY when a PAID plan is bought via
# Stripe checkout (free is not purchasable — webhook handlers skip it). Keep in
# sync with the plan_<tier>_credits registry defaults in settings_registry.py.
PLAN_CREDITS: dict[str, int] = {
    "free": 20000,
    "starter": 600,
    "pro": 2500,
    "business": 20000,
}


class StripeService:
    """Service for Stripe payment operations."""

    _webhook_secret: str = ""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def configure(
        secret_key: str,
        webhook_secret: str,
        plan_price_ids: dict[str, str] | None = None,
        topup_price_ids: dict[int, str] | None = None,
    ) -> None:
        """
        Configure Stripe with API keys. Call once at app startup.

        Args:
            secret_key: Stripe secret key (sk_test_... or sk_live_...)
            webhook_secret: Stripe webhook signing secret (whsec_...)
            plan_price_ids: Mapping of plan name -> Stripe Price ID
            topup_price_ids: Mapping of credit amount -> Stripe Price ID
        """
        global PLAN_PRICE_IDS, TOPUP_PRICE_IDS
        stripe = _get_stripe()
        stripe.api_key = secret_key
        StripeService._webhook_secret = webhook_secret

        if plan_price_ids:
            PLAN_PRICE_IDS.update(plan_price_ids)
        if topup_price_ids:
            TOPUP_PRICE_IDS.update(topup_price_ids)

        logger.info("Stripe configured successfully")

    @staticmethod
    def is_configured() -> bool:
        """Check if Stripe is configured with an API key."""
        try:
            stripe = _get_stripe()
            return bool(getattr(stripe, "api_key", None))
        except RuntimeError:
            return False

    def create_subscription_checkout(
        self,
        organization: Organization,
        plan: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        """
        Create a Stripe Checkout Session for a subscription plan.

        Returns:
            Dict with 'checkout_url' and 'session_id'
        """
        stripe = _get_stripe()
        price_id = PLAN_PRICE_IDS.get(plan.lower())
        if not price_id:
            raise ValueError(f"No Stripe Price ID configured for plan: {plan}")

        customer_id = self._get_or_create_customer(organization)

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "organization_id": organization.id,
                "plan": plan,
                "type": "subscription",
            },
            subscription_data={
                "metadata": {
                    "organization_id": organization.id,
                    "plan": plan,
                },
            },
        )

        return {
            "checkout_url": session.url,
            "session_id": session.id,
        }

    def create_topup_checkout(
        self,
        organization: Organization,
        credits: int,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        """
        Create a Stripe Checkout Session for a credit top-up.

        Args:
            credits: Number of credits to purchase (500, 2000, 5000, 20000)

        Returns:
            Dict with 'checkout_url' and 'session_id'
        """
        stripe = _get_stripe()
        price_id = TOPUP_PRICE_IDS.get(credits)
        if not price_id:
            raise ValueError(
                f"No Stripe Price ID configured for {credits} credits. "
                f"Available: {list(TOPUP_PRICE_IDS.keys())}"
            )

        customer_id = self._get_or_create_customer(organization)

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "organization_id": organization.id,
                "credits": str(credits),
                "type": "topup",
            },
        )

        return {
            "checkout_url": session.url,
            "session_id": session.id,
        }

    def _get_or_create_customer(self, organization: Organization) -> str:
        """Get existing Stripe customer ID or create a new one."""
        stripe = _get_stripe()

        stripe_customer_id = getattr(organization, "stripe_customer_id", None)
        if stripe_customer_id:
            return str(stripe_customer_id)

        customer = stripe.Customer.create(
            name=organization.name,
            metadata={
                "organization_id": organization.id,
                "plan": organization.plan if hasattr(organization, "plan") else "free",
            },
        )

        organization.stripe_customer_id = customer.id
        self.db.flush()

        return str(customer.id)

    def get_subscription(self, organization: Organization) -> dict[str, Any] | None:
        """Get the current subscription for an organization."""
        stripe = _get_stripe()
        sub_id = getattr(organization, "stripe_subscription_id", None)
        if not sub_id:
            return None

        try:
            sub = stripe.Subscription.retrieve(sub_id)
            return {
                "id": sub.id,
                "status": sub.status,
                "plan": getattr(sub.metadata, "plan", "unknown"),
                "current_period_start": datetime.fromtimestamp(
                    sub.current_period_start
                ).isoformat(),
                "current_period_end": datetime.fromtimestamp(sub.current_period_end).isoformat(),
                "cancel_at_period_end": sub.cancel_at_period_end,
            }
        except stripe.StripeError as e:
            logger.error(f"Failed to retrieve subscription {sub_id}: {e}")
            return None

    def cancel_subscription(self, organization: Organization) -> dict[str, Any]:
        """Cancel subscription at end of current period."""
        stripe = _get_stripe()
        sub_id = getattr(organization, "stripe_subscription_id", None)
        if not sub_id:
            raise ValueError("Organization has no active subscription")

        sub = stripe.Subscription.modify(
            sub_id,
            cancel_at_period_end=True,
        )

        return {
            "id": sub.id,
            "status": sub.status,
            "cancel_at_period_end": True,
        }

    def create_billing_portal_session(
        self,
        organization: Organization,
        return_url: str,
    ) -> dict[str, str]:
        """Create a Stripe Billing Portal session for self-service management."""
        stripe = _get_stripe()
        customer_id = self._get_or_create_customer(organization)

        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )

        return {"portal_url": session.url}

    def process_webhook(self, payload: bytes, sig_header: str) -> dict[str, Any]:
        """
        Process a Stripe webhook event.

        Args:
            payload: Raw request body
            sig_header: Stripe-Signature header value

        Returns:
            Dict with processing result
        """
        webhook_secret = getattr(StripeService, "_webhook_secret", None)

        if not webhook_secret:
            raise ValueError("Stripe webhook secret not configured")

        stripe = _get_stripe()

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except stripe.SignatureVerificationError as e:
            raise ValueError("Invalid webhook signature") from e

        event_type = event["type"]
        data = event["data"]["object"]

        handlers = {
            "checkout.session.completed": self._handle_checkout_completed,
            "customer.subscription.updated": self._handle_subscription_updated,
            "customer.subscription.deleted": self._handle_subscription_deleted,
            "invoice.payment_succeeded": self._handle_invoice_paid,
            "invoice.payment_failed": self._handle_invoice_failed,
            "charge.refunded": self._handle_charge_refunded,
            "charge.dispute.created": self._handle_charge_dispute_created,
            "charge.dispute.closed": self._handle_charge_dispute_closed,
            "account.updated": self._handle_account_updated,
        }

        handler = handlers.get(event_type)
        if handler:
            result = handler(data)
            return {"event_type": event_type, "processed": True, **result}

        return {"event_type": event_type, "processed": False, "reason": "unhandled"}

    def _handle_checkout_completed(self, session: dict[str, Any]) -> dict[str, Any]:
        """Handle successful checkout session."""
        metadata = session.get("metadata", {})
        org_id = metadata.get("organization_id")
        checkout_type = metadata.get("type")

        if not org_id:
            return {"error": "No organization_id in metadata"}

        org = self.db.query(Organization).filter(Organization.id == org_id).first()

        if not org:
            return {"error": f"Organization {org_id} not found"}

        if checkout_type == "subscription":
            plan = metadata.get("plan", "starter")
            sub_id = session.get("subscription")

            org.plan = plan
            if hasattr(org, "stripe_subscription_id"):
                org.stripe_subscription_id = sub_id

            # Grant monthly credits via CreditsService (handles balance update internally)
            credits = PLAN_CREDITS.get(plan, 0)
            if credits > 0:
                self._record_transaction(
                    org,
                    credits,
                    description=f"Subscription activated: {plan.upper()} plan",
                    reference=session.get("id"),
                )

            # Create Invoice record (D-23/FIN-07)
            try:
                from app.services.invoice_service import InvoiceService

                inv_service = InvoiceService(self.db)
                inv_service.create_subscription_invoice(
                    organization=org,
                    plan=plan,
                    stripe_payment_intent_id=session.get("payment_intent"),
                )
            except Exception as inv_err:
                logger.warning(f"Failed to create subscription invoice: {inv_err}")

            self.db.flush()
            logger.info(f"Subscription activated: org={org_id}, plan={plan}")
            return {"action": "subscription_activated", "plan": plan}

        elif checkout_type == "topup":
            credits = int(metadata.get("credits", 0))
            if credits > 0:
                self._record_transaction(
                    org,
                    credits,
                    description=f"Credit top-up: {credits} credits",
                    reference=session.get("id"),
                )

                # Create Invoice record (D-23/FIN-07)
                try:
                    from app.services.invoice_service import InvoiceService

                    inv_service = InvoiceService(self.db)
                    inv_service.create_topup_invoice(
                        organization=org,
                        credits=credits,
                        stripe_payment_intent_id=session.get("payment_intent"),
                    )
                except Exception as inv_err:
                    logger.warning(f"Failed to create top-up invoice: {inv_err}")

                self.db.flush()
                logger.info(f"Top-up completed: org={org_id}, credits={credits}")
                return {"action": "topup_completed", "credits": credits}

        return {"action": "none"}

    def _handle_subscription_updated(self, subscription: dict[str, Any]) -> dict[str, Any]:
        """Handle subscription update (plan change, renewal)."""
        metadata = subscription.get("metadata", {})
        org_id = metadata.get("organization_id")

        if not org_id:
            return {"error": "No organization_id in metadata"}

        org = self.db.query(Organization).filter(Organization.id == org_id).first()

        if not org:
            return {"error": f"Organization {org_id} not found"}

        plan = metadata.get("plan", org.plan if hasattr(org, "plan") else "free")
        org.plan = plan
        if hasattr(org, "stripe_subscription_id"):
            org.stripe_subscription_id = subscription.get("id")

        self.db.flush()
        return {"action": "subscription_updated", "plan": plan}

    def _handle_subscription_deleted(self, subscription: dict[str, Any]) -> dict[str, Any]:
        """Handle subscription cancellation."""
        metadata = subscription.get("metadata", {})
        org_id = metadata.get("organization_id")

        if not org_id:
            return {"error": "No organization_id in metadata"}

        org = self.db.query(Organization).filter(Organization.id == org_id).first()

        if not org:
            return {"error": f"Organization {org_id} not found"}

        # Downgrade to free
        org.plan = "free"
        if hasattr(org, "stripe_subscription_id"):
            org.stripe_subscription_id = None

        self.db.flush()
        logger.info(f"Subscription cancelled: org={org_id}")
        return {"action": "subscription_cancelled"}

    def _handle_invoice_paid(self, invoice: dict[str, Any]) -> dict[str, Any]:
        """Handle successful invoice payment (subscription renewal)."""
        sub_id = invoice.get("subscription")
        if not sub_id:
            return {"action": "none", "reason": "no subscription on invoice"}

        org = None
        if hasattr(Organization, "stripe_subscription_id"):
            org = (
                self.db.query(Organization)
                .filter(Organization.stripe_subscription_id == sub_id)
                .first()
            )

        if not org:
            return {"action": "none", "reason": "org not found for subscription"}

        # Refresh subscription credits using the three-pool model:
        #   credits_subscription: reset to plan_credits (use-it-or-lose-it)
        #   credits_purchased: untouched (top-ups never expire)
        #   credits_earned: untouched (marketplace earnings)
        #   credits_balance: recalculated from pools
        plan = org.plan if hasattr(org, "plan") else "free"
        plan_credits = PLAN_CREDITS.get(plan, 0)
        if plan_credits > 0:
            old_sub = getattr(org, "credits_subscription", 0) or 0
            old_pur = getattr(org, "credits_purchased", 0) or 0
            old_earned = getattr(org, "credits_earned", 0) or 0

            # Reset subscription pool to full plan amount
            org.credits_subscription = plan_credits
            # Recalculate total balance from pools
            org.credits_balance = plan_credits + max(0, old_pur) + max(0, old_earned)
            # Reset monthly usage counter
            org.credits_used_month = 0

            # Net-change audit transaction. Written directly here: pool balances were already
            # set above, so _record_transaction would double-count net_grant into credits_balance.
            net_grant = org.credits_balance - (old_sub + old_pur + old_earned)
            logger.info(
                "Subscription renewal: org=%s plan=%s sub=%d->%d purchased=%d earned=%d balance=%d",
                org.id,
                plan,
                old_sub,
                plan_credits,
                old_pur,
                old_earned,
                org.credits_balance,
            )
            if net_grant != 0:
                import uuid

                audit_tx = CreditTransaction(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    transaction_type=TransactionType.PURCHASE.value,
                    credits_amount=net_grant,
                    balance_after=org.credits_balance,
                    earned_balance_after=org.credits_earned,
                    description=f"Monthly renewal: {plan.upper()} plan (sub refreshed to {plan_credits})",
                    reference_type="stripe",
                    reference_id=invoice.get("id"),
                    created_by="system",
                )
                self.db.add(audit_tx)

            # Create Invoice record for renewal (D-23/FIN-07)
            try:
                from app.services.invoice_service import InvoiceService

                inv_service = InvoiceService(self.db)
                inv_service.create_subscription_invoice(
                    organization=org,
                    plan=plan,
                    stripe_invoice_id=invoice.get("id"),
                )
            except Exception as inv_err:
                logger.warning(f"Failed to create renewal invoice: {inv_err}")

            self.db.flush()

        return {
            "action": "renewal_credits_refreshed",
            "plan_credits": plan_credits,
            "granted": net_grant if plan_credits > 0 else 0,
        }

    def _handle_invoice_failed(self, invoice: dict[str, Any]) -> dict[str, Any]:
        """Handle failed invoice payment."""
        logger.warning(f"Invoice payment failed: {invoice.get('id')}")
        return {"action": "payment_failed", "invoice_id": invoice.get("id")}

    def _handle_charge_refunded(self, charge: dict[str, Any]) -> dict[str, Any]:
        """Handle charge.refunded -- deduct credits from buyer, allow negative balance (D-06).

        Platform-initiated or customer-requested refund. Deduct credits from buyer.
        If buyer has insufficient credits, balance goes negative (recorded as debt).
        Admin notification. Account NOT auto-frozen.
        """
        from app.services.credits_service import CreditsService

        metadata = charge.get("metadata", {})
        org_id = metadata.get("organization_id")
        if not org_id:
            # Try to find org by Stripe customer ID
            customer_id = charge.get("customer")
            if customer_id:
                org = (
                    self.db.query(Organization)
                    .filter(Organization.stripe_customer_id == customer_id)
                    .first()
                )
                if org:
                    org_id = org.id

        if not org_id:
            logger.warning(f"charge.refunded: cannot find org for charge {charge.get('id')}")
            return {"action": "skipped", "reason": "org not found"}

        refund_amount_cents = charge.get("amount_refunded", 0)
        refund_amount_eur = refund_amount_cents / 100.0
        from app.models import CREDITS_PER_EUR

        credits_to_claw = int(refund_amount_eur * CREDITS_PER_EUR)

        if credits_to_claw <= 0:
            return {"action": "skipped", "reason": "zero refund amount"}

        service = CreditsService(self.db)
        service.record_transaction(
            organization_id=org_id,
            transaction_type=TransactionType.REFUND_CLAWBACK,
            credits_amount=-credits_to_claw,
            description=(
                f"Refund clawback: {refund_amount_eur:.2f} EUR refunded ({credits_to_claw} credits)"
            ),
            reference_type="stripe_refund",
            reference_id=charge.get("id"),
            amount_eur=refund_amount_eur,
            created_by="system",
            allow_negative=True,  # D-06: balance can go negative for refunds
        )
        self.db.flush()

        # Admin notification
        logger.warning(f"Refund processed: org={org_id}, credits_clawed={credits_to_claw}")

        return {
            "action": "refund_clawback",
            "credits": credits_to_claw,
            "org_id": org_id,
        }

    def _handle_charge_dispute_created(self, dispute: dict[str, Any]) -> dict[str, Any]:
        """Handle charge.dispute.created -- freeze org, claw back credits (D-07/D-08).

        Chargeback: freeze org immediately, claw back full credit amount
        (balance goes negative if needed), notify admin.
        Only admin can unfreeze.
        D-07: After 3+ chargebacks, permanent ban (is_frozen stays True).
        """
        from app.models import CREDITS_PER_EUR
        from app.services.credits_service import CreditsService

        charge = dispute.get("charge", "")
        metadata = dispute.get("metadata", {})
        org_id = metadata.get("organization_id")

        if not org_id:
            # Try payment_intent -> metadata
            payment_intent = dispute.get("payment_intent")
            if isinstance(payment_intent, dict):
                org_id = payment_intent.get("metadata", {}).get("organization_id")

        if not org_id:
            logger.warning(
                f"charge.dispute.created: cannot find org for dispute {dispute.get('id')}"
            )
            return {"action": "skipped", "reason": "org not found"}

        org = (
            self.db.query(Organization).filter(Organization.id == org_id).with_for_update().first()
        )
        if not org:
            return {
                "action": "skipped",
                "reason": f"org {org_id} not found in DB",
            }

        # 1. Freeze org immediately (D-09)
        org.is_frozen = True
        org.chargeback_count = (org.chargeback_count or 0) + 1

        # 1b. D-07: Permanent ban after 3+ chargebacks
        permanent_ban = org.chargeback_count >= 3
        if permanent_ban:
            logger.error(
                f"PERMANENT BAN: org={org_id} has "
                f"{org.chargeback_count} chargebacks (>= 3). "
                f"Account is permanently frozen per D-07. "
                f"Admin must NOT unfreeze."
            )

        # 2. Claw back full disputed amount (D-07)
        disputed_amount_cents = dispute.get("amount", 0)
        disputed_amount_eur = disputed_amount_cents / 100.0
        credits_to_claw = int(disputed_amount_eur * CREDITS_PER_EUR)

        service = CreditsService(self.db)
        if credits_to_claw > 0:
            service.record_transaction(
                organization_id=org_id,
                transaction_type=TransactionType.CHARGEBACK_REVERSAL,
                credits_amount=-credits_to_claw,
                description=(
                    f"Chargeback: {disputed_amount_eur:.2f} EUR disputed "
                    f"({credits_to_claw} credits clawed back)"
                ),
                reference_type="stripe_dispute",
                reference_id=dispute.get("id"),
                amount_eur=disputed_amount_eur,
                created_by="system",
                allow_negative=True,  # D-07: balance can go negative
            )

        # 3. Reverse seller SALE_EARNING if marketplace purchase (D-08)
        charge_id = charge if isinstance(charge, str) else None
        if charge_id:
            original_txn = (
                self.db.query(CreditTransaction)
                .filter(
                    CreditTransaction.organization_id == org_id,
                    CreditTransaction.reference_type == "stripe",
                    CreditTransaction.reference_id == charge_id,
                )
                # Deterministic pick (earliest) so a dropped filter selects a
                # wrong row reproducibly instead of relying on .first() ordering.
                .order_by(CreditTransaction.created_at, CreditTransaction.id)
                .first()
            )
            if original_txn and original_txn.buyer_organization_id:
                # This was a marketplace purchase -- reverse seller earning
                seller_earning = (
                    self.db.query(CreditTransaction)
                    .filter(
                        CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
                        CreditTransaction.buyer_organization_id == org_id,
                        CreditTransaction.reference_id == original_txn.reference_id,
                    )
                    .order_by(CreditTransaction.created_at, CreditTransaction.id)
                    .first()
                )
                if seller_earning:
                    reversal_amount = seller_earning.credits_amount
                    service.record_transaction(
                        organization_id=seller_earning.organization_id,
                        transaction_type=TransactionType.CHARGEBACK_REVERSAL,
                        credits_amount=-reversal_amount,
                        description=(
                            f"Chargeback seller reversal: "
                            f"{reversal_amount} credits "
                            f"(dispute {dispute.get('id')})"
                        ),
                        reference_type="stripe_dispute",
                        reference_id=dispute.get("id"),
                        created_by="system",
                        allow_negative=True,  # D-13
                    )

        self.db.flush()

        logger.warning(
            f"Chargeback processed: org={org_id}, frozen=True, "
            f"chargeback_count={org.chargeback_count}, "
            f"credits_clawed={credits_to_claw}, "
            f"permanent_ban={permanent_ban}"
        )

        return {
            "action": "chargeback_freeze",
            "org_id": org_id,
            "credits_clawed": credits_to_claw,
            "chargeback_count": org.chargeback_count,
            "permanent_ban": permanent_ban,
        }

    def _handle_charge_dispute_closed(self, dispute: dict[str, Any]) -> dict[str, Any]:
        """Handle charge.dispute.closed -- if won, unfreeze org and restore.

        D-07: Do NOT unfreeze if chargeback_count >= 3 (permanent ban).
        """
        status = dispute.get("status", "")

        if status == "won":
            metadata = dispute.get("metadata", {})
            org_id = metadata.get("organization_id")
            if not org_id:
                return {"action": "skipped", "reason": "org not found"}

            org = (
                self.db.query(Organization)
                .filter(Organization.id == org_id)
                .with_for_update()
                .first()
            )
            if org and org.is_frozen:
                from app.services.credits_service import CreditsService

                reversal_txn = (
                    self.db.query(CreditTransaction)
                    .filter(
                        CreditTransaction.organization_id == org_id,
                        CreditTransaction.reference_type == "stripe_dispute",
                        CreditTransaction.reference_id == dispute.get("id"),
                        CreditTransaction.transaction_type
                        == TransactionType.CHARGEBACK_REVERSAL.value,
                    )
                    .order_by(CreditTransaction.created_at, CreditTransaction.id)
                    .first()
                )

                # D-07: Permanent ban check
                if org.chargeback_count >= 3:
                    logger.warning(
                        f"Dispute won for org={org_id} but NOT unfreezing: "
                        f"chargeback_count={org.chargeback_count} >= 3 "
                        f"(permanent ban per D-07)"
                    )
                    # Still restore credits even if permanently banned
                    if reversal_txn:
                        service = CreditsService(self.db)
                        service.record_transaction(
                            organization_id=org_id,
                            transaction_type=TransactionType.REFUND,
                            credits_amount=abs(reversal_txn.credits_amount),
                            description=(
                                f"Chargeback won -- credits restored, "
                                f"but org remains frozen (permanent ban) "
                                f"({dispute.get('id')})"
                            ),
                            reference_type="stripe_dispute_won",
                            reference_id=dispute.get("id"),
                            created_by="system",
                            allow_negative=True,
                        )
                    self.db.flush()
                    return {
                        "action": "dispute_won_still_banned",
                        "org_id": org_id,
                        "chargeback_count": org.chargeback_count,
                    }

                # Normal unfreeze (chargeback_count < 3)
                org.is_frozen = False
                if reversal_txn:
                    service = CreditsService(self.db)
                    service.record_transaction(
                        organization_id=org_id,
                        transaction_type=TransactionType.REFUND,
                        credits_amount=abs(reversal_txn.credits_amount),
                        description=(f"Chargeback won -- credits restored ({dispute.get('id')})"),
                        reference_type="stripe_dispute_won",
                        reference_id=dispute.get("id"),
                        created_by="system",
                    )
                self.db.flush()
                return {"action": "dispute_won_unfrozen", "org_id": org_id}

        # For "lost" status, the clawback stays -- nothing to do
        return {"action": f"dispute_closed_{status}"}

    def _handle_account_updated(self, account: dict[str, Any]) -> dict[str, Any]:
        """Handle account.updated -- update Connect onboarding status."""
        account_id = account.get("id")
        if not account_id:
            return {"action": "skipped", "reason": "no account ID"}

        org = (
            self.db.query(Organization)
            .filter(Organization.stripe_connect_account_id == account_id)
            .first()
        )
        if not org:
            return {
                "action": "skipped",
                "reason": f"no org for account {account_id}",
            }

        charges_enabled = getattr(account, "charges_enabled", False)
        payouts_enabled = getattr(account, "payouts_enabled", False)

        if charges_enabled and payouts_enabled:
            org.stripe_connect_onboarding_complete = True
            self.db.flush()
            logger.info(f"Connect onboarding complete: org={org.id}, account={account_id}")
            return {"action": "onboarding_complete", "org_id": org.id}

        return {
            "action": "account_updated",
            "charges_enabled": charges_enabled,
            "payouts_enabled": payouts_enabled,
        }

    def _record_transaction(
        self,
        org: Organization,
        credits: int,
        description: str,
        reference: str | None = None,
    ) -> None:
        """Record a credit transaction via CreditsService."""
        from app.services.credits_service import CreditsService

        service = CreditsService(self.db)
        service.record_transaction(
            organization_id=org.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=credits,
            description=description,
            reference_type="stripe",
            reference_id=reference,
            created_by="system",
        )
