"""Real Stripe webhook processing tests (Task 3.2).

Tests exercise the ACTUAL webhook processing flow through StripeService.process_webhook
and handler methods, verifying real DB state changes. Only the Stripe signature
verification is mocked (since we cannot generate real Stripe signatures in tests).

Covers:
- checkout.session.completed for subscription (DB subscription created)
- checkout.session.completed for top-up (credits actually added)
- customer.subscription.updated (plan change reflected in DB)
- customer.subscription.deleted (subscription deactivated in DB)
- Webhook signature validation (invalid signatures rejected)
- Idempotency (same event ID processed twice does not double-apply)
- Unknown event types (handled gracefully, no crash)
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models import CreditTransaction, Organization, TransactionType
from app.services.stripe_service import PLAN_CREDITS, StripeService
from app.shared.utils.id_generator import generate_id


def _make_org(db_session, *, balance=1000, plan="free", **kwargs):
    """Create and persist a test organization with sensible defaults."""
    defaults = dict(
        id=generate_id("org_"),
        name="Webhook Test Org",
        plan=plan,
        credits_balance=balance,
        credits_earned=0,
        monthly_quota=100,
        currency="EUR",
        is_active=True,
    )
    defaults.update(kwargs)
    org = Organization(**defaults)
    db_session.add(org)
    db_session.flush()
    return org


def _build_stripe_event(event_type, data_object):
    """Build a dict that mimics a Stripe Event from construct_event."""
    return {
        "id": generate_id("evt_"),
        "type": event_type,
        "data": {"object": data_object},
    }


def _process_webhook_bypassing_signature(service, event_type, data_object):
    """Call process_webhook with mocked signature verification.

    Mocks stripe.Webhook.construct_event to return a synthetic event dict,
    so we exercise the full handler dispatch + DB mutations without needing
    a real Stripe signing secret.
    """
    event = _build_stripe_event(event_type, data_object)

    mock_stripe = MagicMock()
    mock_stripe.Webhook.construct_event.return_value = event
    mock_stripe.SignatureVerificationError = type("SignatureVerificationError", (Exception,), {})

    with patch("app.services.stripe_service._get_stripe", return_value=mock_stripe):
        StripeService._webhook_secret = "whsec_test"
        result = service.process_webhook(
            payload=b'{"mock": true}',
            sig_header="t=1,v1=abc",
        )
    return result


# 1. checkout.session.completed -- subscription


class TestCheckoutSubscriptionWebhook:
    """Verify subscription is ACTUALLY created in DB after webhook processing."""

    def test_subscription_created_in_db(self, db_session):
        """Subscription checkout creates subscription in DB, updates plan, grants credits."""
        org = _make_org(db_session, balance=0, plan="free")
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            {
                "id": "cs_sub_001",
                "subscription": "sub_test_001",
                "payment_intent": "pi_test_001",
                "metadata": {
                    "organization_id": org.id,
                    "type": "subscription",
                    "plan": "pro",
                },
            },
        )
        db_session.flush()

        assert result["processed"] is True
        assert result["action"] == "subscription_activated"
        assert result["plan"] == "pro"

        # Verify actual DB state
        db_session.refresh(org)
        assert org.plan == "pro"
        assert org.stripe_subscription_id == "sub_test_001"
        assert org.credits_balance == PLAN_CREDITS["pro"]

    def test_subscription_credits_recorded_as_transaction(self, db_session):
        """Subscription activation creates a PURCHASE credit transaction."""
        org = _make_org(db_session, balance=0)
        service = StripeService(db_session)

        _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            {
                "id": "cs_sub_txn_001",
                "subscription": "sub_txn_001",
                "metadata": {
                    "organization_id": org.id,
                    "type": "subscription",
                    "plan": "starter",
                },
            },
        )
        db_session.flush()

        txns = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.organization_id == org.id)
            .all()
        )
        assert len(txns) == 1
        assert txns[0].transaction_type == TransactionType.PURCHASE.value
        assert txns[0].credits_amount == PLAN_CREDITS["starter"]
        assert txns[0].reference_id == "cs_sub_txn_001"

    def test_all_plan_tiers_grant_correct_credits(self, db_session):
        """Each plan tier grants the expected credits from PLAN_CREDITS."""
        for plan_name, expected_credits in PLAN_CREDITS.items():
            if plan_name == "free":
                continue  # free plan is not purchasable

            org = _make_org(db_session, balance=0)
            service = StripeService(db_session)

            session_id = f"cs_plan_{plan_name}"
            _process_webhook_bypassing_signature(
                service,
                "checkout.session.completed",
                {
                    "id": session_id,
                    "subscription": f"sub_{plan_name}",
                    "metadata": {
                        "organization_id": org.id,
                        "type": "subscription",
                        "plan": plan_name,
                    },
                },
            )
            db_session.flush()

            db_session.refresh(org)
            assert org.credits_balance == expected_credits, (
                f"Plan {plan_name}: expected {expected_credits}, got {org.credits_balance}"
            )


# 2. checkout.session.completed -- top-up


class TestCheckoutTopupWebhook:
    """Verify credits are ACTUALLY added after top-up webhook."""

    def test_topup_credits_added_to_db(self, db_session):
        """Top-up checkout adds credits to organization balance."""
        org = _make_org(db_session, balance=100)
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            {
                "id": "cs_topup_001",
                "metadata": {
                    "organization_id": org.id,
                    "type": "topup",
                    "credits": "2000",
                },
            },
        )
        db_session.flush()

        assert result["processed"] is True
        assert result["action"] == "topup_completed"
        assert result["credits"] == 2000

        db_session.refresh(org)
        assert org.credits_balance == 2100  # 100 + 2000

    def test_topup_creates_purchase_transaction(self, db_session):
        """Top-up creates a PURCHASE transaction with correct amount."""
        org = _make_org(db_session, balance=50)
        service = StripeService(db_session)

        _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            {
                "id": "cs_topup_txn_001",
                "metadata": {
                    "organization_id": org.id,
                    "type": "topup",
                    "credits": "5000",
                },
            },
        )
        db_session.flush()

        txn = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org.id,
                CreditTransaction.reference_id == "cs_topup_txn_001",
            )
            .one()
        )
        assert txn.transaction_type == TransactionType.PURCHASE.value
        assert txn.credits_amount == 5000
        assert txn.balance_after == 5050  # 50 + 5000

    def test_topup_zero_credits_no_change(self, db_session):
        """Top-up with 0 credits does not modify balance."""
        org = _make_org(db_session, balance=200)
        service = StripeService(db_session)

        _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            {
                "id": "cs_topup_zero",
                "metadata": {
                    "organization_id": org.id,
                    "type": "topup",
                    "credits": "0",
                },
            },
        )
        db_session.flush()

        db_session.refresh(org)
        assert org.credits_balance == 200


# 3. customer.subscription.updated -- plan change


class TestSubscriptionUpdatedWebhook:
    """Verify plan change is reflected in DB."""

    def test_plan_change_reflected_in_db(self, db_session):
        """Subscription update changes the org plan and stores sub ID."""
        org = _make_org(db_session, plan="starter")
        org.stripe_subscription_id = "sub_old_001"
        db_session.flush()

        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "customer.subscription.updated",
            {
                "id": "sub_new_001",
                "metadata": {
                    "organization_id": org.id,
                    "plan": "business",
                },
            },
        )
        db_session.flush()

        assert result["processed"] is True
        assert result["action"] == "subscription_updated"
        assert result["plan"] == "business"

        db_session.refresh(org)
        assert org.plan == "business"
        assert org.stripe_subscription_id == "sub_new_001"

    def test_subscription_updated_missing_plan_keeps_current(self, db_session):
        """If metadata has no plan key, org keeps its current plan."""
        org = _make_org(db_session, plan="pro")
        service = StripeService(db_session)

        _process_webhook_bypassing_signature(
            service,
            "customer.subscription.updated",
            {
                "id": "sub_noplan_001",
                "metadata": {
                    "organization_id": org.id,
                    # no "plan" key
                },
            },
        )
        db_session.flush()

        db_session.refresh(org)
        assert org.plan == "pro"  # unchanged

    def test_subscription_updated_nonexistent_org(self, db_session):
        """Subscription update for non-existent org returns a specific not-found error."""
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "customer.subscription.updated",
            {
                "id": "sub_ghost_001",
                "metadata": {
                    "organization_id": "org_nonexistent_999",
                    "plan": "pro",
                },
            },
        )

        assert result["processed"] is True
        assert result["error"] == "Organization org_nonexistent_999 not found"


# 4. customer.subscription.deleted -- deactivation


class TestSubscriptionDeletedWebhook:
    """Verify subscription is deactivated in DB."""

    def test_subscription_deactivated(self, db_session):
        """Subscription deletion downgrades to free and clears sub ID."""
        org = _make_org(db_session, plan="pro")
        org.stripe_subscription_id = "sub_del_001"
        db_session.flush()

        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "customer.subscription.deleted",
            {
                "id": "sub_del_001",
                "metadata": {"organization_id": org.id},
            },
        )
        db_session.flush()

        assert result["processed"] is True
        assert result["action"] == "subscription_cancelled"

        db_session.refresh(org)
        assert org.plan == "free"
        assert org.stripe_subscription_id is None

    def test_subscription_deleted_from_business(self, db_session):
        """Business plan cancellation also downgrades to free."""
        org = _make_org(db_session, plan="business")
        org.stripe_subscription_id = "sub_biz_del"
        db_session.flush()

        service = StripeService(db_session)

        _process_webhook_bypassing_signature(
            service,
            "customer.subscription.deleted",
            {
                "id": "sub_biz_del",
                "metadata": {"organization_id": org.id},
            },
        )
        db_session.flush()

        db_session.refresh(org)
        assert org.plan == "free"
        assert org.stripe_subscription_id is None

    def test_subscription_deleted_nonexistent_org(self, db_session):
        """Deletion for non-existent org returns a specific not-found error."""
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "customer.subscription.deleted",
            {
                "id": "sub_ghost_del",
                "metadata": {"organization_id": "org_does_not_exist"},
            },
        )

        assert result["processed"] is True
        assert result["error"] == "Organization org_does_not_exist not found"


class TestWebhookSignatureValidation:
    """Verify invalid signatures are rejected."""

    def test_invalid_signature_rejected(self, db_session):
        """Invalid Stripe webhook signature raises ValueError."""
        service = StripeService(db_session)

        mock_stripe = MagicMock()
        sig_error = type("SignatureVerificationError", (Exception,), {})
        mock_stripe.SignatureVerificationError = sig_error
        mock_stripe.Webhook.construct_event.side_effect = sig_error("Invalid signature")

        original_secret = StripeService._webhook_secret
        StripeService._webhook_secret = "whsec_test_secret"

        try:
            with patch(
                "app.services.stripe_service._get_stripe",
                return_value=mock_stripe,
            ):
                with pytest.raises(ValueError, match="Invalid webhook signature"):
                    service.process_webhook(
                        payload=b'{"type":"test"}',
                        sig_header="t=1,v1=invalid",
                    )
        finally:
            StripeService._webhook_secret = original_secret

    def test_missing_webhook_secret_rejected(self, db_session):
        """Missing webhook secret raises ValueError."""
        service = StripeService(db_session)

        original_secret = StripeService._webhook_secret
        StripeService._webhook_secret = ""

        try:
            with pytest.raises(ValueError, match="webhook secret not configured"):
                service.process_webhook(
                    payload=b'{"type":"test"}',
                    sig_header="t=1,v1=test",
                )
        finally:
            StripeService._webhook_secret = original_secret

    def test_empty_signature_header_rejected(self, db_session):
        """Empty signature header is rejected by Stripe construct_event."""
        service = StripeService(db_session)

        mock_stripe = MagicMock()
        sig_error = type("SignatureVerificationError", (Exception,), {})
        mock_stripe.SignatureVerificationError = sig_error
        mock_stripe.Webhook.construct_event.side_effect = sig_error("No signatures found")

        original_secret = StripeService._webhook_secret
        StripeService._webhook_secret = "whsec_test"

        try:
            with patch(
                "app.services.stripe_service._get_stripe",
                return_value=mock_stripe,
            ):
                with pytest.raises(ValueError, match="Invalid webhook signature"):
                    service.process_webhook(
                        payload=b"{}",
                        sig_header="",
                    )
        finally:
            StripeService._webhook_secret = original_secret


class TestWebhookIdempotency:
    """Same event ID processed twice should not double-apply."""

    def test_duplicate_subscription_checkout_idempotent(self, db_session):
        """Processing same subscription checkout twice grants credits only once."""
        org = _make_org(db_session, balance=0)
        service = StripeService(db_session)

        session_data = {
            "id": "cs_idem_sub_001",
            "subscription": "sub_idem_001",
            "metadata": {
                "organization_id": org.id,
                "type": "subscription",
                "plan": "pro",
            },
        }

        # First processing
        _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            session_data,
        )
        db_session.flush()
        db_session.commit()

        db_session.expire_all()
        org_after_1 = db_session.get(Organization, org.id)
        balance_after_1 = org_after_1.credits_balance

        # Second processing (duplicate event)
        _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            session_data,
        )
        db_session.flush()
        db_session.commit()

        db_session.expire_all()
        org_after_2 = db_session.get(Organization, org.id)

        # Balance must not double
        assert org_after_2.credits_balance == balance_after_1
        assert org_after_2.credits_balance == PLAN_CREDITS["pro"]

        # Only one transaction record
        txn_count = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org.id,
                CreditTransaction.reference_id == "cs_idem_sub_001",
            )
            .count()
        )
        assert txn_count == 1

    def test_duplicate_topup_checkout_idempotent(self, db_session):
        """Processing same top-up checkout twice adds credits only once."""
        org = _make_org(db_session, balance=100)
        service = StripeService(db_session)

        session_data = {
            "id": "cs_idem_topup_001",
            "metadata": {
                "organization_id": org.id,
                "type": "topup",
                "credits": "500",
            },
        }

        # First
        _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            session_data,
        )
        db_session.flush()
        db_session.commit()

        db_session.expire_all()
        balance_after_1 = db_session.get(Organization, org.id).credits_balance
        assert balance_after_1 == 600  # 100 + 500

        # Second (duplicate)
        _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            session_data,
        )
        db_session.flush()
        db_session.commit()

        db_session.expire_all()
        balance_after_2 = db_session.get(Organization, org.id).credits_balance
        assert balance_after_2 == 600  # unchanged

    def test_different_session_ids_are_not_idempotent(self, db_session):
        """Different checkout session IDs should both be processed."""
        org = _make_org(db_session, balance=0)
        service = StripeService(db_session)

        for session_id in ("cs_diff_001", "cs_diff_002"):
            _process_webhook_bypassing_signature(
                service,
                "checkout.session.completed",
                {
                    "id": session_id,
                    "metadata": {
                        "organization_id": org.id,
                        "type": "topup",
                        "credits": "500",
                    },
                },
            )
            db_session.flush()

        db_session.refresh(org)
        assert org.credits_balance == 1000  # 500 + 500

    def test_http_webhook_replay_does_not_double_credit(self, client, db_session):
        """POSTing the same Stripe event to /webhook twice must not double-credit.

        This is the Stripe replay scenario: Stripe retries events until it
        gets a 2xx. The endpoint MUST be idempotent against the evt_*/cs_*
        reference_id so a retry after a network blip doesn't double the
        customer's balance.

        Gap filled per audit missing-test #2 ("Stripe webhook idempotency at
        the HTTP layer with replay attacks").
        """
        org = _make_org(db_session, balance=0)
        db_session.commit()
        org_id = org.id

        session_data = {
            "id": "cs_http_replay_001",
            "metadata": {
                "organization_id": org_id,
                "type": "topup",
                "credits": "2000",
            },
        }
        event_id = generate_id("evt_")
        event = {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {"object": session_data},
        }

        mock_stripe = MagicMock()
        mock_stripe.Webhook.construct_event.return_value = event
        mock_stripe.SignatureVerificationError = type(
            "SignatureVerificationError", (Exception,), {}
        )

        original_secret = StripeService._webhook_secret
        StripeService._webhook_secret = "whsec_test"
        try:
            with (
                patch.object(StripeService, "is_configured", return_value=True),
                patch("app.services.stripe_service._get_stripe", return_value=mock_stripe),
            ):
                # First POST — Stripe delivers the event.
                r1 = client.post(
                    "/api/v2/billing/webhook",
                    content=b'{"mock": true}',
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": "t=1,v1=abc",
                    },
                )
                assert r1.status_code == 200, r1.json()

                # Second POST — Stripe replay after imagined network blip.
                r2 = client.post(
                    "/api/v2/billing/webhook",
                    content=b'{"mock": true}',
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": "t=2,v1=def",
                    },
                )
                assert r2.status_code == 200, r2.json()
        finally:
            StripeService._webhook_secret = original_secret

        # Balance credited exactly once despite two HTTP deliveries.
        db_session.expire_all()
        fresh_org = db_session.get(Organization, org_id)
        assert fresh_org.credits_balance == 2000, (
            f"Replay caused double-credit: expected 2000, got {fresh_org.credits_balance}"
        )

        # Only one CreditTransaction for the shared reference_id.
        tx_count = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org_id,
                CreditTransaction.reference_id == "cs_http_replay_001",
            )
            .count()
        )
        assert tx_count == 1, f"Expected exactly 1 transaction for replayed event, got {tx_count}"


class TestUnknownEventTypes:
    """Unknown event types should be handled gracefully."""

    def test_unknown_event_not_processed(self, db_session):
        """Unknown event type returns processed=False without crashing."""
        org = _make_org(db_session, balance=500)
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "some.unknown.event",
            {"id": "obj_unknown_001"},
        )

        assert result["processed"] is False
        assert result["reason"] == "unhandled"
        assert result["event_type"] == "some.unknown.event"

        # Balance unchanged
        db_session.refresh(org)
        assert org.credits_balance == 500

    def test_payment_intent_succeeded_not_processed(self, db_session):
        """payment_intent.succeeded is not in our handler list -- handled gracefully."""
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "payment_intent.succeeded",
            {"id": "pi_test_001"},
        )

        assert result["processed"] is False
        assert result["event_type"] == "payment_intent.succeeded"

    def test_empty_event_type_not_processed(self, db_session):
        """Event with empty type string returns 'unhandled' and makes no DB changes."""
        # Seed an org so we can verify it's untouched.
        org = _make_org(db_session, balance=500, plan="free")
        initial_balance = org.credits_balance
        initial_plan = org.plan
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "",
            {"id": "obj_empty"},
        )

        assert result["processed"] is False
        assert result["reason"] == "unhandled"
        assert result["event_type"] == ""

        db_session.refresh(org)
        assert org.credits_balance == initial_balance
        assert org.plan == initial_plan


class TestWebhookEdgeCases:
    """Edge cases for webhook processing."""

    def test_checkout_without_metadata_organization_id(self, db_session):
        """Checkout with empty metadata returns the specific missing-metadata error."""
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            {
                "id": "cs_no_meta",
                "metadata": {},
            },
        )

        assert result["processed"] is True
        assert result["error"] == "No organization_id in metadata"

    def test_checkout_nonexistent_org(self, db_session):
        """Checkout referencing nonexistent org returns the specific not-found error."""
        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "checkout.session.completed",
            {
                "id": "cs_ghost_org",
                "metadata": {
                    "organization_id": "org_does_not_exist_xyz",
                    "type": "subscription",
                    "plan": "pro",
                },
            },
        )

        assert result["processed"] is True
        assert result["error"] == "Organization org_does_not_exist_xyz not found"

    def test_invoice_paid_grants_renewal_credits(self, db_session):
        """invoice.payment_succeeded grants monthly credits for renewal."""
        org = _make_org(db_session, balance=100, plan="pro")
        org.stripe_subscription_id = "sub_renewal_001"
        db_session.flush()

        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "invoice.payment_succeeded",
            {
                "id": "inv_renewal_001",
                "subscription": "sub_renewal_001",
            },
        )
        db_session.flush()

        assert result["processed"] is True
        assert result["action"] == "renewal_credits_refreshed"
        assert result["plan_credits"] == PLAN_CREDITS["pro"]

        db_session.refresh(org)
        # Subscription credits are refreshed (not added): balance = plan_credits + purchased + earned
        assert org.credits_balance == PLAN_CREDITS["pro"]

    def test_invoice_paid_preserves_purchased_and_earned_pools(self, db_session):
        """Renewal recomputes balance as plan_credits + purchased + earned (three-pool model).

        Kill-test for mutmut survivors in _handle_invoice_paid (Plan 04, AUDIT §16.3):
        the existing renewal test seeds an org with ZERO purchased/earned credits, so the
        `+ max(0, old_pur) + max(0, old_earned)` pool-arithmetic is unobservable (`+0 == -0`,
        a wrong default of 1 is masked). This test seeds NON-zero purchased + earned pools and
        asserts the exact recomputed balance + the net_grant audit transaction, so a sign flip
        (`plan_credits - max(0, old_pur)`), a wrong getattr default, or a dropped pool term is
        caught. Top-ups never expire and marketplace earnings are untouched on renewal.
        """
        org = _make_org(db_session, balance=0, plan="pro")
        org.stripe_subscription_id = "sub_renewal_pools"
        # Three-pool seed: stale subscription pool + live purchased + live earned.
        org.credits_subscription = 7  # stale; must be reset to PLAN_CREDITS["pro"]
        org.credits_purchased = 300  # top-up credits — must survive the renewal
        org.credits_earned = 150  # marketplace earnings — must survive the renewal
        org.credits_balance = 7 + 300 + 150
        db_session.flush()

        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "invoice.payment_succeeded",
            {
                "id": "inv_renewal_pools",
                "subscription": "sub_renewal_pools",
            },
        )
        db_session.flush()

        assert result["processed"] is True
        assert result["action"] == "renewal_credits_refreshed"
        assert result["plan_credits"] == PLAN_CREDITS["pro"]

        # Subscription pool reset to full plan; purchased + earned pools preserved.
        expected_balance = PLAN_CREDITS["pro"] + 300 + 150
        # net_grant = new_balance - (old_sub + old_pur + old_earned) = expected - (7+300+150)
        expected_net_grant = expected_balance - (7 + 300 + 150)
        assert result["granted"] == expected_net_grant

        db_session.refresh(org)
        assert org.credits_subscription == PLAN_CREDITS["pro"]
        assert org.credits_purchased == 300
        assert org.credits_earned == 150
        assert org.credits_balance == expected_balance

        # The audit transaction records exactly net_grant against the renewal invoice.
        audit_tx = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == org.id,
                CreditTransaction.reference_type == "stripe",
                CreditTransaction.reference_id == "inv_renewal_pools",
            )
            .one()
        )
        assert audit_tx.transaction_type == TransactionType.PURCHASE.value
        assert audit_tx.credits_amount == expected_net_grant
        assert audit_tx.balance_after == expected_balance
        assert audit_tx.created_by == "system"

    def test_invoice_failed_logged_gracefully(self, db_session):
        """invoice.payment_failed is a log-only event: no balance/plan/sub-id changes."""
        # Seed an org with a subscription so we can verify no side effects.
        org = _make_org(db_session, balance=500, plan="pro")
        org.stripe_subscription_id = "sub_active_123"
        db_session.flush()

        initial_balance = org.credits_balance
        initial_plan = org.plan
        initial_sub_id = org.stripe_subscription_id

        service = StripeService(db_session)

        result = _process_webhook_bypassing_signature(
            service,
            "invoice.payment_failed",
            {"id": "inv_fail_001"},
        )

        assert result["processed"] is True
        assert result["action"] == "payment_failed"
        assert result["invoice_id"] == "inv_fail_001"

        db_session.refresh(org)
        assert org.credits_balance == initial_balance
        assert org.plan == initial_plan
        assert org.stripe_subscription_id == initial_sub_id

    def test_dispute_events_dispatch_through_process_webhook(self, db_session):
        """charge.dispute.* events route through the process_webhook handler dict.

        Kill-test for process_webhook survivors (Plan 04, AUDIT §16.3): the existing
        dispute tests call _handle_charge_dispute_created / _handle_charge_dispute_closed
        DIRECTLY, bypassing the handler-dispatch dict in process_webhook. That left the
        dict-key routing for these two event types untested end-to-end, so mutating the
        keys (`"charge.dispute.created"` -> `"CHARGE.DISPUTE.CREATED"`,
        `"charge.dispute.closed"` -> `"XXcharge.dispute.closedXX"`) and the handled-branch
        return key (`"event_type"` -> `"EVENT_TYPE"`) survived. This drives both events
        through process_webhook and asserts the correct branch fires + the event_type key
        is present on the handled-event return.
        """
        org = _make_org(db_session, balance=1000, plan="free")
        org.chargeback_count = 0
        org.is_frozen = False
        db_session.flush()

        service = StripeService(db_session)

        # 1. charge.dispute.created must reach _handle_charge_dispute_created via dispatch.
        created = _process_webhook_bypassing_signature(
            service,
            "charge.dispute.created",
            {
                "id": "dp_dispatch_001",
                "amount": 5000,  # 50 EUR -> 500 credits
                "charge": "ch_dispatch_001",
                "metadata": {"organization_id": org.id},
            },
        )
        db_session.flush()

        assert created["processed"] is True
        assert created["event_type"] == "charge.dispute.created"
        assert created["action"] == "chargeback_freeze"
        db_session.refresh(org)
        assert org.is_frozen is True  # dispatch actually invoked the handler

        # 2. charge.dispute.closed (won) must reach _handle_charge_dispute_closed via dispatch.
        closed = _process_webhook_bypassing_signature(
            service,
            "charge.dispute.closed",
            {
                "id": "dp_dispatch_001",
                "status": "won",
                "metadata": {"organization_id": org.id},
            },
        )
        db_session.flush()

        assert closed["processed"] is True
        assert closed["event_type"] == "charge.dispute.closed"
        # chargeback_count < 3 -> won dispute unfreezes the org
        assert closed["action"] == "dispute_won_unfrozen"
        db_session.refresh(org)
        assert org.is_frozen is False
