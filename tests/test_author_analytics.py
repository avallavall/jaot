"""Tests for author analytics endpoints and view event logging.

Covers:
- Author analytics summary endpoint structure
- Analytics time series endpoint
- View/impression event creation via catalog endpoints
- Admin marketplace analytics
"""

import pytest

from app.models import (
    ModelCatalog,
    ModelProject,
    ModelProjectListing,
    Organization,
    User,
)
from app.models.model_view_event import ModelViewEvent
from app.services.author_analytics_service import AuthorAnalyticsService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _add_listing(db, *, pid, author_org_id) -> None:
    """Add a ModelProject anchor + its marketplace listing (view-side of analytics)."""
    db.add(ModelProject(id=pid, organization_id=author_org_id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Model " + pid,
            description="A listing for analytics",
            category="linear",
            generator_type="linear_programming",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_public=True,
            author_organization_id=author_org_id,
        )
    )


@pytest.fixture
def author_org(db_session):
    """Create a author organization."""
    org = Organization(
        id="org_author001",
        name="Author Corp",
        is_active=True,
        is_verified=True,
    )
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def author_user(db_session, author_org):
    """Create a author user."""
    user = User(
        id="user_author001",
        email="author@example.com",
        name="Author User",
        organization_id=author_org.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def catalog_model(db_session, author_org):
    """Create a published catalog model for the author."""
    model = ModelCatalog(
        id="cat_model001",
        name="test-model",
        display_name="Test Optimization Model",
        description="A test model for author analytics",
        category="linear",
        generator_type="linear_programming",
        input_schema={"type": "object", "properties": {}},
        input_fields=[],
        example_input={},
        status="published",
        is_public=True,
        author_organization_id=author_org.id,
        total_activations=0,
        total_executions=0,
    )
    db_session.add(model)
    # The marketplace facet (view-side of analytics) + the bridge catalog row
    # (activation-side) share the id and author org.
    _add_listing(db_session, pid=model.id, author_org_id=author_org.id)
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
            model_project_id=catalog_model.id,
            event_type="impression",
            viewer_country="US",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            model_project_id=catalog_model.id,
            event_type="impression",
            viewer_country="DE",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            model_project_id=catalog_model.id,
            event_type="view",
            viewer_country="US",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            model_project_id=catalog_model.id,
            event_type="view",
            viewer_country="ES",
            created_at=now,
        ),
    ]
    db_session.add_all(events)
    db_session.commit()
    return events


@pytest.fixture
def activation(db_session, author_org, catalog_model):
    """Another org adopts the author's model (a fork ModelProject seeded
    from-marketplace — the post-fusion analytics event)."""
    buyer_org = Organization(
        id=generate_id("org_"),
        name="Buyer Org",
        slug=f"buyer-{generate_id('x_')[2:10]}",
        is_active=True,
    )
    db_session.add(buyer_org)
    db_session.flush()
    fork = ModelProject(
        id=generate_id("mp_"),
        organization_id=buyer_org.id,
        name="Forked Test Model",
        status="active",
        source_type="marketplace",
        source_ref=catalog_model.id,
    )
    db_session.add(fork)
    db_session.commit()
    return fork


class TestAnalyticsSummary:
    """Test author analytics summary endpoint."""

    def test_summary_returns_correct_structure(
        self,
        authenticated_client,
        db_session,
        author_org,
        catalog_model,
        view_events,
        activation,
        mock_auth,
        author_user,
    ):
        """Summary endpoint returns all expected fields."""
        mock_auth(author_user)
        response = authenticated_client.get(
            "/api/v2/author/analytics/summary",
            params={"period": "30d"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_views" in data
        assert "total_impressions" in data
        assert "total_activations" in data
        assert "conversion_rate" in data
        assert "period" in data
        assert data["period"] == "30d"

    def test_summary_counts_views_and_impressions(
        self,
        authenticated_client,
        db_session,
        author_org,
        catalog_model,
        view_events,
        mock_auth,
        author_user,
    ):
        """Summary correctly aggregates view and impression counts."""
        mock_auth(author_user)
        response = authenticated_client.get(
            "/api/v2/author/analytics/summary",
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
        author_org,
        catalog_model,
        view_events,
        mock_auth,
        author_user,
    ):
        """Period filter parameter works correctly."""
        mock_auth(author_user)
        for period in ["7d", "30d", "90d", "all"]:
            response = authenticated_client.get(
                "/api/v2/author/analytics/summary",
                params={"period": period},
            )
            assert response.status_code == 200
            assert response.json()["period"] == period


class TestAnalyticsTimeSeries:
    """Test author analytics time series endpoint."""

    def test_time_series_returns_data_array(
        self,
        authenticated_client,
        db_session,
        author_org,
        catalog_model,
        view_events,
        mock_auth,
        author_user,
    ):
        """Time series endpoint returns array of data points."""
        mock_auth(author_user)
        response = authenticated_client.get(
            "/api/v2/author/analytics/time-series",
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
        """View event references the correct model (by model_project_id)."""
        client.get(f"/api/v2/models/catalog/{catalog_model.id}")

        event = (
            db_session.query(ModelViewEvent)
            .filter(
                ModelViewEvent.event_type == "view",
                ModelViewEvent.model_project_id == catalog_model.id,
            )
            .first()
        )
        assert event is not None
        assert event.model_project_id == catalog_model.id


class TestAnalyticsService:
    """Test AuthorAnalyticsService directly."""

    def test_get_summary_platform_wide(
        self, db_session, author_org, catalog_model, view_events, activation
    ):
        """Platform-wide summary (org_id=None) includes all events."""
        service = AuthorAnalyticsService(db_session)
        summary = service.get_summary(org_id=None, period="all")
        assert summary.total_views >= 2
        assert summary.total_impressions >= 2
        assert summary.total_activations >= 1

    def test_get_geo_distribution(self, db_session, author_org, catalog_model, view_events):
        """Geo distribution groups events by country."""
        service = AuthorAnalyticsService(db_session)
        geo = service.get_geo_distribution(org_id=author_org.id, period="all")
        countries = {e.country for e in geo.data}
        assert "US" in countries

    def test_get_conversion_funnel(
        self, db_session, author_org, catalog_model, view_events, activation
    ):
        """Conversion funnel returns impressions, views, activations."""
        service = AuthorAnalyticsService(db_session)
        funnel = service.get_conversion_funnel(org_id=author_org.id, period="all")
        assert funnel.impressions >= 0
        assert funnel.views >= 0
        assert funnel.activations >= 0

    def test_get_author_leaderboard(self, db_session, author_org, catalog_model, activation):
        """Leaderboard returns author entries sorted by activations."""
        service = AuthorAnalyticsService(db_session)
        leaderboard = service.get_author_leaderboard(period="all")
        assert len(leaderboard) >= 1
        assert leaderboard[0].org_id == author_org.id
        assert leaderboard[0].total_activations > 0


class TestAuthorAnalyticsCrossOrgIsolation:
    """Verify the author analytics endpoints scope by organization_id.

    The author endpoints (/api/v2/author/analytics/...) MUST only return
    data for the authenticated user's own organization. A user from org A
    must never see counts belonging to org B's models, regardless
    of how many events org B has accumulated.
    """

    def test_author_summary_filters_by_authenticated_org_id(
        self,
        authenticated_client,
        db_session,
        author_org,
        catalog_model,
        view_events,
        activation,
        author_user,
        mock_auth,
    ):
        """The author summary endpoint must NOT leak another org's events.

        Plant a second author org with its own catalog model + view events
        + sale, then assert that authenticating as org_a's user never
        returns counts that include org_b's events.
        """
        # Plant a foreign author org with its own catalog model and events
        foreign_org = Organization(
            id="org_foreign_author",
            name="Foreign Author",
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
            author_organization_id=foreign_org.id,
        )
        db_session.add(foreign_model)
        _add_listing(db_session, pid=foreign_model.id, author_org_id=foreign_org.id)
        db_session.flush()

        # 99 view events on the foreign model (large enough to be obvious if leaked)
        for _i in range(99):
            db_session.add(
                ModelViewEvent(
                    id=generate_id("mve_"),
                    model_project_id=foreign_model.id,
                    event_type="view",
                    viewer_country="JP",
                    created_at=utcnow(),
                )
            )

        # And a foreign self-activation (the author org forking its OWN listing)
        # to make sure counts do not leak either
        db_session.add(
            ModelProject(
                id=generate_id("mp_"),
                organization_id=foreign_org.id,
                name="Foreign Self Fork",
                status="active",
                source_type="marketplace",
                source_ref=foreign_model.id,
            )
        )
        db_session.commit()

        # Authenticate as author_org's user and pull the summary
        mock_auth(author_user)
        response = authenticated_client.get(
            "/api/v2/author/analytics/summary",
            params={"period": "all"},
        )
        assert response.status_code == 200
        data = response.json()

        # author_org has 2 view events (from view_events fixture).
        # If foreign org's 99 leaked through, total_views would be 101.
        assert data["total_views"] == 2, (
            f"Cross-org view leak: expected 2 own views, got {data['total_views']}"
        )
        # author_org's own model has exactly ONE activation (the `activation`
        # fixture: a buyer org activating cat_model001). foreign_org's
        # activation of its own model must NOT leak in — a leak reads 2.
        assert data["total_activations"] == 1, (
            f"Cross-org activation leak: expected 1 own-model activation, "
            f"got {data['total_activations']}"
        )

    def test_author_service_filters_by_org_id_at_service_layer(
        self, db_session, author_org, catalog_model, view_events
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
            is_active=True,
        )
        db_session.add(sibling)
        db_session.commit()

        service = AuthorAnalyticsService(db_session)
        own = service.get_summary(org_id=author_org.id, period="all")
        sibling_summary = service.get_summary(org_id=sibling.id, period="all")

        assert own.total_views >= 2
        # Sibling has no models, so its summary must be all zeros
        assert sibling_summary.total_views == 0
        assert sibling_summary.total_impressions == 0
        assert sibling_summary.total_activations == 0
