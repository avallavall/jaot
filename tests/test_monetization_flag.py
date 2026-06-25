"""Behaviour of the ``MONETIZATION_ENABLED`` flag (free collaborative mode).

The platform ships with ``MONETIZATION_ENABLED=false``: the marketplace is a
place to publish and use optimization models freely — no prices, commissions, or
payouts. Paid-marketplace endpoints (seller earnings, payouts, Stripe Connect,
featured-placement purchases, billing checkout, public pricing) are dormant and
respond ``404`` so the monetization surface stays invisible. A self-hosted
deployment can flip the flag on ("bring-your-own Stripe") to restore the paid
marketplace.

These tests pin the desmonetization contract from both sides:
- free mode (default): paid-only endpoints 404, neutral ones stay available,
  activation is free, publishing forces price to 0, the onboarding checklist
  drops the payouts step, and the scheduled-withdrawals task is a no-op;
- paid mode (``enable_monetization`` fixture): the same surfaces light back up.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models import (
    CreditTransaction,
    ModelCatalog,
    Organization,
    OrganizationModel,
    TransactionType,
)
from app.shared.utils.id_generator import generate_id


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_org(db: Session, *, credits: int = 0, subscription: int = 0) -> Organization:
    """Create and flush a fresh organization."""
    org = Organization(
        id=generate_id("org_"),
        name="Seller Org",
        credits_balance=credits,
        credits_subscription=subscription,
        is_active=True,
        rate_limit_per_minute=999_999,
        rate_limit_per_day=999_999,
    )
    db.add(org)
    db.flush()
    return org


def _make_priced_model(
    db: Session, *, author_organization_id: str | None, price_eur: float = 10.0
) -> ModelCatalog:
    """Create and flush a published catalog model with a non-zero price."""
    model_id = generate_id("cat_")
    model = ModelCatalog(
        id=model_id,
        name=f"priced_model_{model_id}",
        display_name="Priced Model",
        description="A priced catalog model for monetization-flag tests.",
        generator_type="knapsack",
        input_schema={},
        input_fields=[],
        example_input={},
        price_eur=price_eur,
        status="published",
        is_public=True,
        is_official=False,
        author_organization_id=author_organization_id,
        total_activations=0,
        total_executions=0,
    )
    db.add(model)
    db.flush()
    return model


def _make_private_model(db: Session, *, organization_id: str) -> OrganizationModel:
    """Create and flush a private (publishable) organization model."""
    model = OrganizationModel(
        id=generate_id("om_"),
        organization_id=organization_id,
        catalog_id=None,
        private_definition={
            "generator_type": "knapsack",
            "input_schema": {},
            "input_fields": [],
            "example_input": {},
        },
        is_active=True,
    )
    db.add(model)
    db.flush()
    return model


# --------------------------------------------------------------------------- #
# Free mode (default): gated endpoints are hidden
# --------------------------------------------------------------------------- #
class TestGatedEndpointsReturn404:
    """Paid-only endpoints respond 404 when monetization is disabled (default)."""

    GATED_GET = [
        "/api/v2/seller/earnings/summary",
        "/api/v2/seller/earnings/sales",
        "/api/v2/seller/placements/pricing",
        "/api/v2/seller/placements/active",
        "/api/v2/seller/connect/status",
        "/api/v2/seller/tos/status",
        "/api/v2/credits/withdrawals",
        "/api/v2/credits/schedules",
        "/api/v2/billing/subscription",
        "/api/v2/pricing",
    ]

    @pytest.mark.parametrize("path", GATED_GET)
    def test_gated_get_returns_404(self, authenticated_client, path):
        response = authenticated_client.get(path)
        assert response.status_code == 404, (
            f"{path} must 404 in free mode, got {response.status_code}: {response.text}"
        )

    GATED_POST = [
        (
            "/api/v2/seller/placements/purchase",
            {"catalog_model_id": "x", "placement_type": "homepage_carousel", "duration_days": 7},
        ),
        ("/api/v2/seller/connect/onboard", {}),
        ("/api/v2/seller/tos/accept", {}),
        ("/api/v2/credits/withdrawals", {"credits_amount": 500}),
        (
            "/api/v2/credits/schedules",
            {"frequency": "weekly", "amount_type": "all", "amount_value": 0, "min_threshold": 100},
        ),
        ("/api/v2/billing/checkout/subscription", {"plan": "pro"}),
        ("/api/v2/billing/checkout/topup", {"credits": 500}),
        ("/api/v2/billing/portal", {}),
    ]

    @pytest.mark.parametrize("path,body", GATED_POST)
    def test_gated_post_returns_404(self, authenticated_client, path, body):
        # The monetization gate is a route dependency and runs before body
        # validation, so a 404 is returned regardless of the (valid) body.
        response = authenticated_client.post(path, json=body)
        assert response.status_code == 404, (
            f"{path} must 404 in free mode, got {response.status_code}: {response.text}"
        )

    def test_admin_withdrawals_list_returns_404(self, admin_client):
        response = admin_client.get("/api/v2/admin/withdrawals")
        assert response.status_code == 404

    def test_admin_withdrawal_approve_returns_404(self, admin_client):
        response = admin_client.post("/api/v2/admin/withdrawals/wd_any/approve")
        assert response.status_code == 404

    def test_admin_withdrawal_reject_returns_404(self, admin_client):
        response = admin_client.post(
            "/api/v2/admin/withdrawals/wd_any/reject", json={"reason": "x"}
        )
        assert response.status_code == 404

    def test_admin_seller_analytics_returns_404(self, admin_client):
        response = admin_client.get("/api/v2/admin/marketplace/seller-analytics")
        assert response.status_code == 404

    def test_admin_promotions_returns_404(self, admin_client):
        response = admin_client.get("/api/v2/admin/marketplace/promotions")
        assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Free mode: neutral endpoints stay available
# --------------------------------------------------------------------------- #
class TestNeutralEndpointsStayAvailable:
    """Collaborative features keep working when monetization is disabled."""

    def test_seller_analytics_summary_available(self, authenticated_client):
        response = authenticated_client.get("/api/v2/seller/analytics/summary")
        assert response.status_code == 200

    def test_seller_verification_status_available(self, authenticated_client):
        response = authenticated_client.get("/api/v2/seller/verification/status")
        assert response.status_code == 200

    def test_seller_onboarding_status_available(self, authenticated_client):
        response = authenticated_client.get("/api/v2/seller/onboarding/status")
        assert response.status_code == 200

    def test_credits_balance_available(self, authenticated_client):
        response = authenticated_client.get("/api/v2/credits/balance")
        assert response.status_code == 200
        assert "credits_balance" in response.json()

    def test_credits_transactions_available(self, authenticated_client):
        response = authenticated_client.get("/api/v2/credits/transactions")
        assert response.status_code == 200

    def test_catalog_list_available(self, authenticated_client):
        response = authenticated_client.get("/api/v2/models/catalog")
        assert response.status_code == 200
        assert "items" in response.json()

    def test_billing_status_available(self, authenticated_client):
        response = authenticated_client.get("/api/v2/billing/status")
        assert response.status_code == 200

    def test_admin_feature_analytics_available(self, admin_client):
        response = admin_client.get("/api/v2/admin/marketplace/feature-analytics")
        assert response.status_code == 200

    def test_admin_reconciliation_stays_available(self, admin_client):
        # Reconciliation guards credit-balance integrity; credits remain a usage
        # quota in free mode, so the manual trigger must stay reachable.
        response = admin_client.post("/api/v2/admin/reconciliation/run")
        assert response.status_code == 200


# --------------------------------------------------------------------------- #
# Free mode: activation is free
# --------------------------------------------------------------------------- #
class TestFreeActivation:
    """Activating a priced model is free and records no sale when disabled."""

    def test_activating_priced_model_does_not_charge(
        self, authenticated_client, db_session, test_organization
    ):
        seller = _make_org(db_session)
        model = _make_priced_model(db_session, author_organization_id=seller.id, price_eur=10.0)
        db_session.commit()

        balance_before = test_organization.credits_balance

        response = authenticated_client.post(f"/api/v2/models/catalog/{model.id}/activate", json={})
        assert response.status_code == 200, response.text

        buyer = db_session.query(Organization).filter_by(id=test_organization.id).one()
        assert buyer.credits_balance == balance_before, "buyer must not be charged in free mode"

        sale_earnings = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == seller.id,
                CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
            )
            .count()
        )
        assert sale_earnings == 0, "no marketplace sale should be recorded in free mode"

        org_model = (
            db_session.query(OrganizationModel)
            .filter_by(organization_id=test_organization.id, catalog_id=model.id)
            .one()
        )
        assert org_model.purchase_price_eur is None
        assert org_model.purchased_at is None

    def test_activating_own_priced_model_allowed(
        self, authenticated_client, db_session, test_organization
    ):
        # The self-purchase 403 block only fires on paid models; in free mode
        # you may activate (use) your own published model.
        model = _make_priced_model(
            db_session, author_organization_id=test_organization.id, price_eur=10.0
        )
        db_session.commit()

        response = authenticated_client.post(f"/api/v2/models/catalog/{model.id}/activate", json={})
        assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# Publishing forces price to zero in free mode, persists it when enabled
# --------------------------------------------------------------------------- #
class TestPublishPrice:
    """Publishing strips the price unless monetization is enabled."""

    _BODY = {
        "display_name": "Published Test Model",
        "description": "A genuinely useful optimization model for publish tests.",
        "price_eur": 50.0,
    }

    def test_publish_forces_price_zero_when_disabled(
        self, authenticated_client, db_session, test_organization
    ):
        model = _make_private_model(db_session, organization_id=test_organization.id)
        db_session.commit()

        response = authenticated_client.post(f"/api/v2/models/{model.id}/publish", json=self._BODY)
        assert response.status_code == 200, response.text
        assert response.json()["price_eur"] == 0.0, "free mode must publish at price 0"

    def test_publish_persists_price_when_enabled(
        self, authenticated_client, db_session, test_organization, enable_monetization
    ):
        model = _make_private_model(db_session, organization_id=test_organization.id)
        db_session.commit()

        response = authenticated_client.post(f"/api/v2/models/{model.id}/publish", json=self._BODY)
        assert response.status_code == 200, response.text
        assert response.json()["price_eur"] == 50.0


# --------------------------------------------------------------------------- #
# Onboarding checklist
# --------------------------------------------------------------------------- #
class TestOnboardingSteps:
    """The seller onboarding checklist drops the payouts step in free mode."""

    def test_payouts_step_absent_when_disabled(self, authenticated_client):
        response = authenticated_client.get("/api/v2/seller/onboarding/status")
        assert response.status_code == 200
        keys = [step["key"] for step in response.json()["steps"]]
        assert "setup_payouts" not in keys
        assert keys == ["complete_profile", "publish_model", "add_rich_media"]

    def test_payouts_step_present_when_enabled(self, authenticated_client, enable_monetization):
        response = authenticated_client.get("/api/v2/seller/onboarding/status")
        assert response.status_code == 200
        keys = [step["key"] for step in response.json()["steps"]]
        assert "setup_payouts" in keys
        assert len(keys) == 4


# --------------------------------------------------------------------------- #
# Scheduled-withdrawals Celery task
# --------------------------------------------------------------------------- #
class TestScheduledWithdrawalsTask:
    """The scheduled-withdrawals task is a no-op when monetization is disabled."""

    def _run_task(self, db_session):
        from app.tasks import financial_tasks

        def _session_factory():
            return Session(bind=db_session.bind, expire_on_commit=False)

        with patch.object(financial_tasks, "SessionLocal", _session_factory):
            return financial_tasks.process_scheduled_withdrawals_task.apply().get()

    def test_task_skips_when_disabled(self, db_session):
        result = self._run_task(db_session)
        assert result["processed"] == 0
        assert result.get("skipped") == "monetization_disabled"

    def test_task_runs_when_enabled(self, db_session, enable_monetization):
        result = self._run_task(db_session)
        # No due schedules exist, so it processes zero — but it does NOT skip.
        assert "skipped" not in result
        assert result["processed"] == 0


# --------------------------------------------------------------------------- #
# Paid mode restores the marketplace
# --------------------------------------------------------------------------- #
class TestMonetizationEnabledRestoresPaidPath:
    """Flipping the flag on lights the dormant paid surfaces back up."""

    def test_pricing_endpoint_available(self, authenticated_client, enable_monetization):
        response = authenticated_client.get("/api/v2/pricing")
        assert response.status_code == 200
        assert "tiers" in response.json()

    def test_earnings_summary_available(self, authenticated_client, enable_monetization):
        response = authenticated_client.get("/api/v2/seller/earnings/summary")
        assert response.status_code == 200
        assert "withdrawable_balance" in response.json()

    def test_activating_priced_model_charges_and_records_sale(
        self, authenticated_client, db_session, test_organization, enable_monetization
    ):
        # Give the buyer a clean subscription pool to drain.
        buyer = db_session.query(Organization).filter_by(id=test_organization.id).one()
        buyer.credits_balance = 1000
        buyer.credits_subscription = 1000
        seller = _make_org(db_session)
        model = _make_priced_model(db_session, author_organization_id=seller.id, price_eur=10.0)
        db_session.commit()

        response = authenticated_client.post(f"/api/v2/models/catalog/{model.id}/activate", json={})
        assert response.status_code == 200, response.text

        buyer = db_session.query(Organization).filter_by(id=test_organization.id).one()
        assert buyer.credits_balance == 900, "buyer charged 100 credits (10 EUR x 10)"

        seller_earning = (
            db_session.query(CreditTransaction)
            .filter(
                CreditTransaction.organization_id == seller.id,
                CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
            )
            .one()
        )
        # 100 credits price minus the default 10% commission = 90 credits earned.
        assert seller_earning.credits_amount == 90
