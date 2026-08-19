"""Tests for author analytics endpoints and view event logging.

Covers:
- Author analytics summary endpoint structure
- Analytics time series endpoint
- View/impression event creation via catalog endpoints
- Admin marketplace analytics
"""

import pytest

from app.models import (
    ModelProject,
    ModelProjectListing,
    Organization,
    User,
)
from app.models.model_view_event import ModelViewEvent
from app.services.author_analytics_service import AuthorAnalyticsService
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _add_listing(db, *, pid, author_org_id) -> ModelProjectListing:
    """Add a ModelProject anchor + its marketplace listing (view-side of analytics)."""
    db.add(ModelProject(id=pid, organization_id=author_org_id, name="Proj " + pid, status="active"))
    db.flush()
    listing = ModelProjectListing(
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
    db.add(listing)
    return listing


def _add_authorless_listing(db, *, owner_org_id: str) -> str:
    """A listing whose ``author_organization_id`` is NULL, and its anchor project.

    Real rows look like this — 3 of 112 on the development database. The anchor
    project still needs an owner because ``model_projects.organization_id`` is
    NOT NULL; it is the LISTING that names no author.
    """
    pid = generate_id("mp_")
    db.add(ModelProject(id=pid, organization_id=owner_org_id, name="Proj " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Author-less " + pid,
            description="A listing with no author organization",
            category="linear",
            generator_type="linear_programming",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_public=True,
            author_organization_id=None,
        )
    )
    db.flush()
    return pid


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
    """A published model of the author's, as the analytics read it.

    D-26 removed the pre-fusion ``ModelCatalog`` row this used to plant beside
    the listing; author analytics have always been served from the listing.
    """
    listing = _add_listing(db_session, pid="cat_model001", author_org_id=author_org.id)
    db_session.commit()
    db_session.refresh(listing)
    return listing


@pytest.fixture
def view_events(db_session, catalog_model):
    """Create sample view and impression events."""
    now = utcnow()
    events = [
        ModelViewEvent(
            id=generate_id("mve_"),
            model_project_id=catalog_model.model_project_id,
            event_type="impression",
            viewer_country="US",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            model_project_id=catalog_model.model_project_id,
            event_type="impression",
            viewer_country="DE",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            model_project_id=catalog_model.model_project_id,
            event_type="view",
            viewer_country="US",
            created_at=now,
        ),
        ModelViewEvent(
            id=generate_id("mve_"),
            model_project_id=catalog_model.model_project_id,
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
        source_ref=catalog_model.model_project_id,
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

        response = client.get(f"/api/v2/models/catalog/{catalog_model.model_project_id}")
        assert response.status_code == 200

        new_count = (
            db_session.query(ModelViewEvent).filter(ModelViewEvent.event_type == "view").count()
        )
        assert new_count == initial_count + 1

    def test_view_event_has_correct_model_id(
        self, client, db_session, catalog_model, override_db_dependency
    ):
        """View event references the correct model (by model_project_id)."""
        client.get(f"/api/v2/models/catalog/{catalog_model.model_project_id}")

        event = (
            db_session.query(ModelViewEvent)
            .filter(
                ModelViewEvent.event_type == "view",
                ModelViewEvent.model_project_id == catalog_model.model_project_id,
            )
            .first()
        )
        assert event is not None
        assert event.model_project_id == catalog_model.model_project_id


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

        foreign_model = _add_listing(
            db_session, pid="cat_foreign_001", author_org_id=foreign_org.id
        )
        db_session.flush()

        # 99 view events on the foreign model (large enough to be obvious if leaked)
        for _i in range(99):
            db_session.add(
                ModelViewEvent(
                    id=generate_id("mve_"),
                    model_project_id=foreign_model.model_project_id,
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
                source_ref=foreign_model.model_project_id,
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


class TestAdoptionIsCountedOnce:
    """# CONTRACT-TEST: every surface that says "adoption" counts the same thing.

    Three places used to count it independently and none agreed. On the
    development database an admin was shown 112 on the dashboard, 2 on the
    author-analytics page and a stored 66 on the listings, all under that one
    word. ``adoption_query`` is the single definition now; these tests pin what
    it counts and what it leaves out.
    """

    @staticmethod
    def _org(db, name: str) -> Organization:
        org = Organization(id=generate_id("org_"), name=name, is_active=True)
        db.add(org)
        db.flush()
        return org

    @staticmethod
    def _fork(db, *, org_id: str, source_ref: str | None) -> ModelProject:
        fork = ModelProject(
            id=generate_id("mp_"),
            organization_id=org_id,
            name="Fork " + generate_id("x_")[2:8],
            status="active",
            source_type="marketplace",
            source_ref=source_ref,
        )
        db.add(fork)
        db.flush()
        return fork

    def test_an_adoption_of_a_listing_with_no_author_org_is_counted(self, db_session, author_org):
        """The bug that hid two thirds of them.

        ``author_organization_id`` is nullable and the self-adoption exclusion
        was a plain ``!=``. In SQL ``x != NULL`` is NULL, never true, so every
        adoption of an author-less listing was dropped. Measured on the
        development database: 3 listings of 112 had a NULL author org and
        carried 4 of the 6 adoptions on the platform. The page said 2.
        """
        from app.services.author_analytics_service import adoption_query

        orphan_pid = _add_authorless_listing(db_session, owner_org_id=author_org.id)
        adopter = self._org(db_session, "Adopter of an author-less listing")
        self._fork(db_session, org_id=adopter.id, source_ref=orphan_pid)
        db_session.flush()

        adoptions = adoption_query(db_session).all()

        assert any(a.source_ref == orphan_pid for a in adoptions)

    def test_a_project_that_records_no_source_is_not_an_adoption(self, db_session):
        """A project with ``source_ref = NULL`` adopted nothing.

        105 of the dashboard 112 looked exactly like this: seeded official
        models tagged as coming from the marketplace, naming no listing.
        """
        from app.services.author_analytics_service import adoption_query

        org = self._org(db_session, "Owner of a sourceless project")
        sourceless = self._fork(db_session, org_id=org.id, source_ref=None)
        db_session.flush()

        assert sourceless.id not in {a.id for a in adoption_query(db_session).all()}

    def test_the_author_forking_its_own_listing_is_not_an_adoption(self, db_session):
        """Still excluded. That is what makes the word mean "somebody else"."""
        from app.services.author_analytics_service import adoption_query

        author = self._org(db_session, "Self Adopter")
        pid = generate_id("mp_")
        _add_listing(db_session, pid=pid, author_org_id=author.id)
        own = self._fork(db_session, org_id=author.id, source_ref=pid)
        db_session.flush()

        assert own.id not in {a.id for a in adoption_query(db_session).all()}

    def test_the_admin_dashboard_and_the_analytics_page_report_the_same_number(
        self, admin_client, db_session
    ):
        """The disagreement an admin could see on two pages of the same panel."""
        author = self._org(db_session, "Author With One Adopter")
        adopter = self._org(db_session, "The Adopter")
        pid = generate_id("mp_")
        _add_listing(db_session, pid=pid, author_org_id=author.id)
        self._fork(db_session, org_id=adopter.id, source_ref=pid)
        # A sourceless project: the dashboard used to count it, the analytics
        # page never did.
        self._fork(db_session, org_id=adopter.id, source_ref=None)
        db_session.commit()

        stats = admin_client.get("/api/v2/admin/stats")
        analytics = admin_client.get("/api/v2/admin/marketplace/author-analytics?period=all")
        assert stats.status_code == 200, stats.text
        assert analytics.status_code == 200, analytics.text

        assert (
            stats.json()["models"]["activated_total"]
            == analytics.json()["platform_totals"]["total_activations"]
        )


class TestAuthorLeaderboardShowsEveryAuthor:
    """# CONTRACT-TEST: publishing puts an author on the leaderboard, adoption ranks them.

    The panel was built from its own ranking metric, so it could only ever show
    authors somebody had already forked. On a platform with 112 listings by 2
    organizations it read "No author data available" for the 30-day period it
    opens on, because nobody had adopted anything in that window.
    """

    def test_an_author_with_no_adoptions_still_appears(self, db_session, author_org):
        pid = generate_id("mp_")
        _add_listing(db_session, pid=pid, author_org_id=author_org.id)
        db_session.commit()

        rows = AuthorAnalyticsService(db_session).get_author_leaderboard("all")

        entry = next((r for r in rows if r.org_id == author_org.id), None)
        assert entry is not None, "an author who published is missing from the leaderboard"
        assert entry.total_activations == 0
        assert entry.models_published == 1

    def test_the_period_with_no_adoptions_still_lists_the_authors(self, db_session, author_org):
        """An author adopted long ago still shows on a recent period, on zero.

        This is the shape that made the 30-day default read as "nobody publishes
        here": the adoptions existed, they were just older than the window.
        """
        from datetime import timedelta

        pid = generate_id("mp_")
        _add_listing(db_session, pid=pid, author_org_id=author_org.id)
        adopter = Organization(id=generate_id("org_"), name="Old Adopter", is_active=True)
        db_session.add(adopter)
        db_session.flush()
        db_session.add(
            ModelProject(
                id=generate_id("mp_"),
                organization_id=adopter.id,
                name="Adopted a year ago",
                status="active",
                source_type="marketplace",
                source_ref=pid,
                created_at=utcnow() - timedelta(days=365),
            )
        )
        db_session.commit()

        service = AuthorAnalyticsService(db_session)
        recent = service.get_author_leaderboard("7d")
        all_time = service.get_author_leaderboard("all")

        assert recent, "the leaderboard is empty on a period with no adoptions"
        recent_entry = next(r for r in recent if r.org_id == author_org.id)
        assert recent_entry.total_activations == 0
        assert recent_entry.models_published == 1
        # The same author, ranked, once the window includes the adoption.
        assert next(r for r in all_time if r.org_id == author_org.id).total_activations == 1

    def test_an_adoption_nobody_wrote_creates_no_author_row(self, db_session, author_org):
        """A listing with no author org has adoptions that belong to nobody.

        They count in the platform total. A leaderboard row for them would be an
        author who does not exist.
        """
        orphan_pid = _add_authorless_listing(db_session, owner_org_id=author_org.id)
        adopter = Organization(id=generate_id("org_"), name="Adopter", is_active=True)
        db_session.add(adopter)
        db_session.flush()
        db_session.add(
            ModelProject(
                id=generate_id("mp_"),
                organization_id=adopter.id,
                name="Fork of an author-less listing",
                status="active",
                source_type="marketplace",
                source_ref=orphan_pid,
            )
        )
        db_session.commit()

        rows = AuthorAnalyticsService(db_session).get_author_leaderboard("all")

        assert all(r.org_id is not None for r in rows)
        assert all(r.org_name != "Unknown" for r in rows)

    def test_the_order_is_adoption_then_output_then_name(self, db_session):
        """Two authors on zero adoptions come back in the same order every time."""
        service = AuthorAnalyticsService(db_session)
        for name, listings in (("Zed Publishes Two", 2), ("Alice Publishes One", 1)):
            org = Organization(id=generate_id("org_"), name=name, is_active=True)
            db_session.add(org)
            db_session.flush()
            for _ in range(listings):
                _add_listing(db_session, pid=generate_id("mp_"), author_org_id=org.id)
        db_session.commit()

        rows = service.get_author_leaderboard("all")
        names = [r.org_name for r in rows if r.total_activations == 0]

        assert names.index("Zed Publishes Two") < names.index("Alice Publishes One")
