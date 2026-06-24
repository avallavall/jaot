"""Tests for seller analytics endpoints and view event logging.

Covers:
- Seller analytics summary endpoint structure
- Analytics time series endpoint
- View/impression event creation via catalog endpoints
- Admin marketplace analytics
"""

import pytest

from app.models import ModelCatalog, Organization, User
from app.models.credit_transaction import CreditTransaction, TransactionType
from app.models.model_view_event import ModelViewEvent
from app.services.seller_analytics_service import SellerAnalyticsService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def seller_org(db_session):
    """Create a seller organization."""
    org = Organization(
        id="org_seller001",
        name="Seller Corp",
        credits_balance=5000,
        credits_earned=1000,
        is_active=True,
        is_verified=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def seller_user(db_session, seller_org):
    """Create a seller user."""
    user = User(
        id="user_seller001",
        email="seller@example.com",
        name="Seller User",
        organization_id=seller_org.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def catalog_model(db_session, seller_org):
    """Create a published catalog model for the seller."""
    model = ModelCatalog(
        id="cat_model001",
        name="test-model",
        display_name="Test Optimization Model",
        description="A test model for seller analytics",
        category="linear",
        generator_type="linear_programming",
        input_schema={"type": "object", "properties": {}},
        input_fields=[],
        example_input={},
        status="published",
        is_public=True,
        price_eur=10.0,
        author_organization_id=seller_org.id,
        total_activations=0,
        total_executions=0,
    )
    db_session.add(model)
    db_session.commit()
    db_session.refresh(model)
    return model


@pytest.fixture
def view_events(db_session, catalog_model):
    """Create sample view and impression events."""
    now = utcnow()
    events = [
        ModelViewEvent(
            id=generate_id("mve_"),
            catalog_model_id=catalog_model.id,
            event_type="impression",
            viewer_country="US",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            catalog_model_id=catalog_model.id,
            event_type="impression",
            viewer_country="DE",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            catalog_model_id=catalog_model.id,
            event_type="view",
            viewer_country="US",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            catalog_model_id=catalog_model.id,
            event_type="view",
            viewer_country="ES",
            created_at=now,
        ),
    ]
    db_session.add_all(events)
    db_session.commit()
    return events


@pytest.fixture
def sale_transaction(db_session, seller_org, catalog_model):
    """Create a SALE_EARNING transaction for the seller."""
    tx = CreditTransaction(
        id=generate_id("ctx_"),
        organization_id=seller_org.id,
        transaction_type=TransactionType.SALE_EARNING.value,
        credits_amount=85,
        balance_after=seller_org.credits_balance,
        earned_balance_after=seller_org.credits_earned + 85,
        amount_eur=8.5,
        description="Model sale",
        reference_type="model",
        reference_id=catalog_model.id,
        created_by="system",
        created_at=utcnow(),
    )
    db_session.add(tx)
    db_session.commit()
    return tx


class TestAnalyticsSummary:
    """Test seller analytics summary endpoint."""

    def test_summary_returns_correct_structure(
        self,
        authenticated_client,
        db_session,
        seller_org,
        catalog_model,
        view_events,
        sale_transaction,
        mock_auth,
        seller_user,
    ):
        """Summary endpoint returns all expected fields."""
        mock_auth(seller_user)
        response = authenticated_client.get(
            "/api/v2/seller/analytics/summary",
            params={"period": "30d"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_views" in data
        assert "total_impressions" in data
        assert "total_activations" in data
        assert "total_revenue" in data
        assert "conversion_rate" in data
        assert "period" in data
        assert data["period"] == "30d"

    def test_summary_counts_views_and_impressions(
        self,
        authenticated_client,
        db_session,
        seller_org,
        catalog_model,
        view_events,
        mock_auth,
        seller_user,
    ):
        """Summary correctly aggregates view and impression counts."""
        mock_auth(seller_user)
        response = authenticated_client.get(
            "/api/v2/seller/analytics/summary",
            params={"period": "all"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_views"] == 2
        assert data["total_impressions"] == 2

    def test_summary_period_filtering(
        self,
        authenticated_client,
        db_session,
        seller_org,
        catalog_model,
        view_events,
        mock_auth,
        seller_user,
    ):
        """Period filter parameter works correctly."""
        mock_auth(seller_user)
        for period in ["7d", "30d", "90d", "all"]:
            response = authenticated_client.get(
                "/api/v2/seller/analytics/summary",
                params={"period": period},
            )
            assert response.status_code == 200
            assert response.json()["period"] == period


class TestAnalyticsTimeSeries:
    """Test seller analytics time series endpoint."""

    def test_time_series_returns_data_array(
        self,
        authenticated_client,
        db_session,
        seller_org,
        catalog_model,
        view_events,
        mock_auth,
        seller_user,
    ):
        """Time series endpoint returns array of data points."""
        mock_auth(seller_user)
        response = authenticated_client.get(
            "/api/v2/seller/analytics/time-series",
            params={"period": "30d"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "period" in data
        assert isinstance(data["data"], list)
        if data["data"]:
            point = data["data"][0]
            assert "date" in point
            assert "views" in point
            assert "impressions" in point


class TestViewEventLogging:
    """Test that catalog endpoints create ModelViewEvent records."""

    def test_catalog_list_creates_impressions(
        self, client, db_session, catalog_model, override_db_dependency
    ):
        """Listing catalog models creates impression events for each returned model."""
        initial_count = (
            db_session.query(ModelViewEvent)
            .filter(ModelViewEvent.event_type == "impression")
            .count()
        )

        response = client.get("/api/v2/models/catalog")
        assert response.status_code == 200

        new_count = (
            db_session.query(ModelViewEvent)
            .filter(ModelViewEvent.event_type == "impression")
            .count()
        )
        # Should have created at least one impression for the published model
        assert new_count > initial_count

    def test_catalog_detail_creates_view(
        self, client, db_session, catalog_model, override_db_dependency
    ):
        """Viewing a model detail creates a view event."""
        initial_count = (
            db_session.query(ModelViewEvent).filter(ModelViewEvent.event_type == "view").count()
        )

        response = client.get(f"/api/v2/models/catalog/{catalog_model.id}")
        assert response.status_code == 200

        new_count = (
            db_session.query(ModelViewEvent).filter(ModelViewEvent.event_type == "view").count()
        )
        assert new_count == initial_count + 1

    def test_view_event_has_correct_model_id(
        self, client, db_session, catalog_model, override_db_dependency
    ):
        """View event references the correct catalog model."""
        client.get(f"/api/v2/models/catalog/{catalog_model.id}")

        event = (
            db_session.query(ModelViewEvent)
            .filter(
                ModelViewEvent.event_type == "view",
                ModelViewEvent.catalog_model_id == catalog_model.id,
            )
            .first()
        )
        assert event is not None
        assert event.catalog_model_id == catalog_model.id


class TestAnalyticsService:
    """Test SellerAnalyticsService directly."""

    def test_get_summary_platform_wide(
        self, db_session, seller_org, catalog_model, view_events, sale_transaction
    ):
        """Platform-wide summary (org_id=None) includes all events."""
        service = SellerAnalyticsService(db_session)
        summary = service.get_summary(org_id=None, period="all")
        assert summary.total_views >= 2
        assert summary.total_impressions >= 2
        assert summary.total_activations >= 1

    def test_get_geo_distribution(self, db_session, seller_org, catalog_model, view_events):
        """Geo distribution groups events by country."""
        service = SellerAnalyticsService(db_session)
        geo = service.get_geo_distribution(org_id=seller_org.id, period="all")
        countries = {e.country for e in geo.data}
        assert "US" in countries

    def test_get_conversion_funnel(
        self, db_session, seller_org, catalog_model, view_events, sale_transaction
    ):
        """Conversion funnel returns impressions, views, activations."""
        service = SellerAnalyticsService(db_session)
        funnel = service.get_conversion_funnel(org_id=seller_org.id, period="all")
        assert funnel.impressions >= 0
        assert funnel.views >= 0
        assert funnel.activations >= 0

    def test_get_seller_leaderboard(self, db_session, seller_org, catalog_model, sale_transaction):
        """Leaderboard returns seller entries sorted by revenue."""
        service = SellerAnalyticsService(db_session)
        leaderboard = service.get_seller_leaderboard(period="all")
        assert len(leaderboard) >= 1
        assert leaderboard[0].org_id == seller_org.id
        assert leaderboard[0].total_revenue > 0


class TestSellerAnalyticsCrossOrgIsolation:
    """Verify the seller analytics endpoints scope by organization_id.

    The seller endpoints (/api/v2/seller/analytics/...) MUST only return
    data for the authenticated user's own organization. A user from org A
    must never see counts/revenue belonging to org B's models, regardless
    of how many events org B has accumulated.
    """

    def test_seller_summary_filters_by_authenticated_org_id(
        self,
        authenticated_client,
        db_session,
        seller_org,
        catalog_model,
        view_events,
        sale_transaction,
        seller_user,
        mock_auth,
    ):
        """The seller summary endpoint must NOT leak another org's events.

        Plant a second seller org with its own catalog model + view events
        + sale, then assert that authenticating as org_a's user never
        returns counts that include org_b's events.
        """
        # Plant a foreign seller org with its own catalog model and events
        foreign_org = Organization(
            id="org_foreign_seller",
            name="Foreign Seller",
            credits_balance=5000,
            credits_earned=2000,
            is_active=True,
            is_verified=True,
        )
        db_session.add(foreign_org)
        db_session.flush()

        foreign_model = ModelCatalog(
            id="cat_foreign_001",
            name="foreign-model",
            display_name="Foreign Model",
            description="Foreign org's model",
            category="linear",
            generator_type="linear_programming",
            input_schema={"type": "object", "properties": {}},
            input_fields=[],
            example_input={},
            status="published",
            is_public=True,
            price_eur=20.0,
            author_organization_id=foreign_org.id,
        )
        db_session.add(foreign_model)
        db_session.flush()

        # 99 view events on the foreign model (large enough to be obvious if leaked)
        for _i in range(99):
            db_session.add(
                ModelViewEvent(
                    id=generate_id("mve_"),
                    catalog_model_id=foreign_model.id,
                    event_type="view",
                    viewer_country="JP",
                    created_at=utcnow(),
                )
            )

        # And a foreign sale to make sure revenue does not leak either
        db_session.add(
            CreditTransaction(
                id=generate_id("ctx_"),
                organization_id=foreign_org.id,
                transaction_type=TransactionType.SALE_EARNING.value,
                credits_amount=999,
                balance_after=foreign_org.credits_balance,
                earned_balance_after=foreign_org.credits_earned + 999,
                amount_eur=99.9,
                description="Foreign sale (must not leak to seller_org)",
                reference_type="model",
                reference_id=foreign_model.id,
                created_by="system",
                created_at=utcnow(),
            )
        )
        db_session.commit()

        # Authenticate as seller_org's user and pull the summary
        mock_auth(seller_user)
        response = authenticated_client.get(
            "/api/v2/seller/analytics/summary",
            params={"period": "all"},
        )
        assert response.status_code == 200
        data = response.json()

        # seller_org has 2 view events (from view_events fixture).
        # If foreign org's 99 leaked through, total_views would be 101.
        assert data["total_views"] == 2, (
            f"Cross-org view leak: expected 2 own views, got {data['total_views']}"
        )
        # seller_org's sale_transaction is 8.5 EUR (85 credits).
        # foreign_org's sale is 99.9 EUR. If it leaked, revenue would jump.
        assert data["total_revenue"] < 99.0, (
            f"Cross-org revenue leak: got {data['total_revenue']} (foreign sale was 99.9)"
        )

    def test_seller_service_filters_by_org_id_at_service_layer(
        self, db_session, seller_org, catalog_model, view_events
    ):
        """Direct service call: get_summary(org_id=other) returns zero own events.

        Pinpoints the contract at the service layer so a regression that
        removed the org_id WHERE clause would fail loudly.
        """
        from app.shared.utils.id_generator import generate_id as gid

        # Plant a sibling org with no models or events
        sibling = Organization(
            id=gid("org_"),
            name="Sibling Without Events",
            credits_balance=10,
            is_active=True,
        )
        db_session.add(sibling)
        db_session.commit()

        service = SellerAnalyticsService(db_session)
        own = service.get_summary(org_id=seller_org.id, period="all")
        sibling_summary = service.get_summary(org_id=sibling.id, period="all")

        assert own.total_views >= 2
        # Sibling has no models, so its summary must be all zeros
        assert sibling_summary.total_views == 0
        assert sibling_summary.total_impressions == 0
        assert sibling_summary.total_activations == 0
        assert sibling_summary.total_revenue == 0
