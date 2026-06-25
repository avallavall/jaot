"""Tests for seller earnings API endpoints (MKT-02)."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.models import (
    CreditTransaction,
    Organization,
    TransactionType,
    User,
)
from app.services.credits_service import CreditsService
from app.shared.utils.datetime_helpers import utcnow


@pytest.fixture(autouse=True)
def _enable_monetization(enable_monetization):
    """Seller earnings endpoints are paid-only; enable monetization for this module."""
    """Test earnings summary with no sales."""

    def test_earnings_summary_empty(
        self, db_session: Session, client, test_user, test_organization, mock_auth
    ):
        """New org with no sales returns all zeros."""
        mock_auth(test_user)

        response = client.get("/api/v2/seller/earnings/summary")
        assert response.status_code == 200

        data = response.json()
        assert data["total_sales"] == 0
        assert data["total_earned"] == 0
        assert data["total_commission"] == 0
        assert data["withdrawable_balance"] == 0
        assert data["pending_withdrawals"] == 0
        assert isinstance(data["commission_rate"], float)


class TestEarningsSummaryWithSales:
    """Test earnings summary after marketplace sales."""

    def test_earnings_summary_with_sales(self, db_session: Session, client, mock_auth):
        """Create 2 sales via record_marketplace_sale, verify summary totals."""
        # Create seller and buyer orgs
        seller = Organization(
            id="seller-summary",
            name="Seller Org",
            credits_balance=0,
            credits_earned=0,
        )
        buyer = Organization(
            id="buyer-summary",
            name="Buyer Org",
            credits_balance=500,
            credits_earned=0,
        )
        db_session.add_all([seller, buyer])
        db_session.flush()

        seller_user = User(
            id="seller-user-summary",
            email="seller-summary@test.com",
            name="Seller User",
            organization_id=seller.id,
            is_active=True,
        )
        db_session.add(seller_user)
        db_session.commit()

        # Record 2 marketplace sales
        service = CreditsService(db_session)
        service.record_marketplace_sale(
            seller_organization_id=seller.id,
            buyer_organization_id=buyer.id,
            model_id="model-a",
            credits_price=100,
            commission_rate=0.10,
        )
        service.record_marketplace_sale(
            seller_organization_id=seller.id,
            buyer_organization_id=buyer.id,
            model_id="model-b",
            credits_price=50,
            commission_rate=0.10,
        )

        # Mature the SALE_EARNING transactions so they pass the holding period check
        past = utcnow() - timedelta(days=1)
        db_session.query(CreditTransaction).filter(
            CreditTransaction.organization_id == seller.id,
            CreditTransaction.transaction_type == TransactionType.SALE_EARNING.value,
        ).update({"available_at": past})
        db_session.commit()

        mock_auth(seller_user)
        response = client.get("/api/v2/seller/earnings/summary")
        assert response.status_code == 200

        data = response.json()
        assert data["total_sales"] == 2
        # 100 * 0.9 + 50 * 0.9 = 90 + 45 = 135
        assert data["total_earned"] == 135
        # 100 * 0.1 + 50 * 0.1 = 10 + 5 = 15
        assert data["total_commission"] == 15
        # credits_earned on org should match total_earned
        assert data["withdrawable_balance"] == 135
        assert data["pending_withdrawals"] == 0
        assert data["commission_rate"] == 0.10


class TestSalesHistoryPagination:
    """Test sales history pagination."""

    def test_sales_history_pagination(self, db_session: Session, client, mock_auth):
        """Create 5 sales, request page 1 size 2, verify 2 items with total=5."""
        seller = Organization(
            id="seller-page",
            name="Seller Org",
            credits_balance=0,
            credits_earned=0,
        )
        buyer = Organization(
            id="buyer-page",
            name="Buyer Org",
            credits_balance=1000,
            credits_earned=0,
        )
        db_session.add_all([seller, buyer])
        db_session.flush()

        seller_user = User(
            id="seller-user-page",
            email="seller-page@test.com",
            name="Seller User",
            organization_id=seller.id,
            is_active=True,
        )
        db_session.add(seller_user)
        db_session.commit()

        service = CreditsService(db_session)
        for i in range(5):
            service.record_marketplace_sale(
                seller_organization_id=seller.id,
                buyer_organization_id=buyer.id,
                model_id=f"model-page-{i}",
                credits_price=20,
                commission_rate=0.10,
            )
        db_session.commit()

        mock_auth(seller_user)
        response = client.get("/api/v2/seller/earnings/sales?page=1&page_size=2")
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2


class TestSalesHistoryCommissionBreakdown:
    """Test that each sale record shows correct commission breakdown."""

    def test_sales_history_commission_breakdown(self, db_session: Session, client, mock_auth):
        """Verify each sale record shows correct commission_amount and seller_earning."""
        seller = Organization(
            id="seller-bd",
            name="Seller Org",
            credits_balance=0,
            credits_earned=0,
        )
        buyer = Organization(
            id="buyer-bd",
            name="Buyer BD",
            credits_balance=500,
            credits_earned=0,
        )
        db_session.add_all([seller, buyer])
        db_session.flush()

        seller_user = User(
            id="seller-user-bd",
            email="seller-bd@test.com",
            name="Seller User",
            organization_id=seller.id,
            is_active=True,
        )
        db_session.add(seller_user)
        db_session.commit()

        service = CreditsService(db_session)
        service.record_marketplace_sale(
            seller_organization_id=seller.id,
            buyer_organization_id=buyer.id,
            model_id="model-bd-1",
            credits_price=100,
            commission_rate=0.10,
        )
        db_session.commit()

        mock_auth(seller_user)
        response = client.get("/api/v2/seller/earnings/sales?page=1&page_size=20")
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) == 1

        sale = data["items"][0]
        assert sale["seller_earning"] == 90
        assert sale["commission_amount"] == 10
        assert sale["credits_price"] == 100
        assert sale["buyer_organization_name"] == "Buyer BD"
