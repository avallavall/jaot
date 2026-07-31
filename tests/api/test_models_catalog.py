"""
Tests for Models Catalog API (Marketplace).

P1.5 fusion: the marketplace serves from the unified ``ModelProjectListing`` facet
(browse / detail / schema). The legacy activate flow is retired — using a model
means seeding a fork ModelProject via ``POST /projects/from-marketplace/{id}``.
"""

from fastapi.testclient import TestClient

from app.models import ModelCategory, ModelProject, ModelProjectListing
from app.models.model_view_event import ModelViewEvent
from app.services.author_analytics_service import AuthorAnalyticsService


def _make_listing(db, org, *, pid, **overrides) -> ModelProjectListing:
    """Create a published ModelProject + its marketplace listing facet."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    fields = {
        "model_project_id": pid,
        "name": pid,
        "display_name": "Model " + pid,
        "description": "A test listing for " + pid,
        "short_description": "short",
        "category": ModelCategory.GENERAL.value,
        "generator_type": "generic",
        "input_schema": {"type": "object"},
        "input_fields": [],
        "example_input": {},
        "version": "1.0.0",
        "status": "published",
        "is_official": False,
        "is_public": True,
    }
    fields.update(overrides)
    listing = ModelProjectListing(**fields)
    db.add(listing)
    db.commit()
    return listing


class TestCatalogList:
    """Tests for GET /api/v2/models/catalog"""

    def test_list_catalog_with_models(self, authenticated_client, db_session, test_organization):
        """Test listing catalog with published models."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_catalog_model_1",
            name="uniquelistingname",
            display_name="Unique Listing Name",
        )

        # Search-isolate from the seeded official listings (which crowd page 1).
        response = authenticated_client.get("/api/v2/models/catalog?search=uniquelistingname")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

        model_ids = [s["id"] for s in data["items"]]
        assert "test_catalog_model_1" in model_ids

    def test_list_catalog_filters_unpublished(
        self, authenticated_client, db_session, test_organization
    ):
        """Test that unpublished listings are not listed."""
        _make_listing(db_session, test_organization, pid="test_unpublished_model", status="draft")

        response = authenticated_client.get("/api/v2/models/catalog")
        assert response.status_code == 200
        data = response.json()

        model_ids = [s["id"] for s in data["items"]]
        assert "test_unpublished_model" not in model_ids

    def test_list_catalog_filter_by_category(
        self, authenticated_client, db_session, test_organization
    ):
        """Test filtering catalog by category."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_finance_model",
            category=ModelCategory.FINANCE.value,
        )
        _make_listing(
            db_session,
            test_organization,
            pid="test_logistics_model",
            category=ModelCategory.LOGISTICS.value,
        )

        response = authenticated_client.get("/api/v2/models/catalog?category=finance")
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["category"] == "finance"

    def test_list_catalog_filter_by_official(
        self, authenticated_client, db_session, test_organization
    ):
        """Test filtering catalog by official status."""
        _make_listing(db_session, test_organization, pid="test_official_model", is_official=True)

        response = authenticated_client.get("/api/v2/models/catalog?is_official=true")
        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["is_official"]

    def test_list_catalog_search(self, authenticated_client, db_session, test_organization):
        """Test searching catalog by name/description."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_searchable_model",
            name="unique_searchable_name",
            display_name="Unique Searchable Model",
        )

        response = authenticated_client.get("/api/v2/models/catalog?search=unique_searchable")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        model_ids = [s["id"] for s in data["items"]]
        assert "test_searchable_model" in model_ids

    def test_list_catalog_pagination(self, authenticated_client, db_session, test_organization):
        """Test catalog pagination."""
        for i in range(5):
            _make_listing(db_session, test_organization, pid=f"test_pagination_model_{i}")

        response = authenticated_client.get("/api/v2/models/catalog?page=1&page_size=2")
        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) <= 2


class TestCatalogDetail:
    """Tests for GET /api/v2/models/catalog/{model_id}"""

    def test_get_catalog_model_detail(self, authenticated_client, db_session, test_organization):
        """Test getting details of a catalog model."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_detail_model",
            display_name="Detail Model",
            category=ModelCategory.FINANCE.value,
            tags=["test", "detail"],
            is_official=True,
            is_featured=True,
        )

        response = authenticated_client.get("/api/v2/models/catalog/test_detail_model")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "test_detail_model"
        assert data["display_name"] == "Detail Model"
        assert data["is_official"]

    def test_get_catalog_model_not_found(self, authenticated_client):
        """Test getting non-existent model returns 404."""
        response = authenticated_client.get("/api/v2/models/catalog/nonexistent_model")
        assert response.status_code == 404


class TestCatalogSchema:
    """Tests for GET /api/v2/models/catalog/{model_id}/schema"""

    def test_get_catalog_model_schema(self, authenticated_client, db_session, test_organization):
        """Test getting schema of a catalog model."""
        _make_listing(
            db_session,
            test_organization,
            pid="test_schema_model",
            generator_type="budget_allocation",
            input_schema={"type": "object", "properties": {"budget": {"type": "number"}}},
            input_fields=[
                {"name": "budget", "type": "number", "label": "Total Budget", "required": True}
            ],
            example_input={"budget": 10000},
        )

        response = authenticated_client.get("/api/v2/models/catalog/test_schema_model/schema")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "test_schema_model"
        assert "input_fields" in data
        assert "example_input" in data
        assert data["generator_type"] == "budget_allocation"


class TestActivateModel:
    """The legacy activate flow is RETIRED (P1.5 G6c).

    Using a marketplace model = seeding a fork ModelProject via
    ``POST /projects/from-marketplace/{id}`` (covered by test_project_seeding).
    """

    def test_activate_route_retired(self, authenticated_client, db_session, test_organization):
        """POST /catalog/{id}/activate must stay gone — even for a real listing."""
        _make_listing(db_session, test_organization, pid="test_activate_retired")

        response = authenticated_client.post(
            "/api/v2/models/catalog/test_activate_retired/activate", json={}
        )
        assert response.status_code == 404


class TestVisitTelemetryIsStored:
    """The view and impression events must outlive the request that logged them.

    They did not. Both were written with ``add()`` + ``flush()`` and nothing
    committed — ``get_db`` only closes the session — so every event was rolled
    back on the way out and the author analytics dashboard read an empty table
    on every install. A 200 from these endpoints proves nothing about that,
    which is why these tests count rows instead.
    """

    # CONTRACT-TEST: marketplace visit telemetry is committed, not just flushed
    def test_a_detail_page_stores_its_view_event(
        self, authenticated_client, db_session, test_organization
    ):
        _make_listing(db_session, test_organization, pid="test_view_persisted")

        assert (
            authenticated_client.get("/api/v2/models/catalog/test_view_persisted").status_code
            == 200
        )

        events = (
            db_session.query(ModelViewEvent)
            .filter(
                ModelViewEvent.model_project_id == "test_view_persisted",
                ModelViewEvent.event_type == "view",
            )
            .all()
        )
        assert len(events) == 1

    # CONTRACT-TEST: marketplace visit telemetry is committed, not just flushed
    def test_a_listing_page_stores_its_impressions(
        self, authenticated_client, db_session, test_organization
    ):
        _make_listing(
            db_session,
            test_organization,
            pid="test_impression_persisted",
            name="impressionprobe",
            display_name="Impression Probe",
        )

        assert (
            authenticated_client.get("/api/v2/models/catalog?search=impressionprobe").status_code
            == 200
        )

        events = (
            db_session.query(ModelViewEvent)
            .filter(
                ModelViewEvent.model_project_id == "test_impression_persisted",
                ModelViewEvent.event_type == "impression",
            )
            .all()
        )
        assert len(events) == 1

    # CONTRACT-TEST: our own server-side fetches are never counted as readers
    def test_the_sitemap_walk_records_no_impressions(
        self, authenticated_client, db_session, test_organization
    ):
        """A listing page fetched by the sitemap walk stores nothing.

        `sitemap.ts` pages this endpoint every hour to build the SEO sitemap, and
        each page used to bank one impression per listing it returned: 103 an
        hour on the reference install, 97.8% of every impression ever stored. An
        author read those as an audience.

        The caller says so with the header its own fetch sets
        (`SSR_REQUEST_HEADERS` in frontend/src/lib/seo/ssrFetch.ts) — the API does
        not guess. See `_is_own_traffic` for why guessing was wrong.
        """
        _make_listing(
            db_session,
            test_organization,
            pid="test_ssr_impression",
            name="ssrprobe",
            display_name="SSR Probe",
        )

        assert (
            authenticated_client.get(
                "/api/v2/models/catalog?search=ssrprobe", headers={"X-JAOT-SSR": "1"}
            ).status_code
            == 200
        )

        assert (
            db_session.query(ModelViewEvent)
            .filter(ModelViewEvent.model_project_id == "test_ssr_impression")
            .count()
            == 0
        )

    # CONTRACT-TEST: our own server-side fetches are never counted as readers
    def test_the_ssr_metadata_fetch_records_no_view(
        self, authenticated_client, db_session, test_organization
    ):
        """The detail page fetches this endpoint server-side for its metadata and
        JSON-LD, so every visit was counted twice — once as a phantom view with
        no country and no organisation, once for real from the browser. Only the
        browser's own fetch is a view."""
        _make_listing(db_session, test_organization, pid="test_ssr_view")

        assert (
            authenticated_client.get(
                "/api/v2/models/catalog/test_ssr_view", headers={"X-JAOT-SSR": "1"}
            ).status_code
            == 200
        )

        assert (
            db_session.query(ModelViewEvent)
            .filter(ModelViewEvent.model_project_id == "test_ssr_view")
            .count()
            == 0
        )

    # CONTRACT-TEST: a reader whose call arrives with no forwarding header still counts
    def test_a_reader_proxied_by_next_is_still_counted(self, app, db_session, test_organization):
        """A browser call that reaches the API *through* Next's `/api/*` rewrite.

        That proxy forwards only `x-forwarded-host` — never `X-Forwarded-For` — so
        the request arrives from the frontend container's private address with no
        forwarding header at all. Identifying our own traffic by *inferring* it
        from that shape (the first attempt at this fix) therefore discarded every
        genuine view and impression on the default compose, along with the
        "recently opened" row. This test is that regression.
        """
        _make_listing(db_session, test_organization, pid="test_next_proxied_view")

        with TestClient(app, client=("172.18.0.5", 51002)) as via_next:
            assert (
                via_next.get(
                    "/api/v2/models/catalog/test_next_proxied_view",
                    headers={"X-Forwarded-Host": "localhost:3000"},
                ).status_code
                == 200
            )

        events = (
            db_session.query(ModelViewEvent)
            .filter(
                ModelViewEvent.model_project_id == "test_next_proxied_view",
                ModelViewEvent.event_type == "view",
            )
            .all()
        )
        assert len(events) == 1

    def test_a_failed_view_log_still_serves_the_page(
        self, authenticated_client, db_session, test_organization, monkeypatch
    ):
        """Telemetry is not worth a reader's page: if the write blows up, the
        detail response must still arrive intact."""
        _make_listing(db_session, test_organization, pid="test_view_failure")

        def _explode(*args, **kwargs):
            raise RuntimeError("analytics is down")

        monkeypatch.setattr(AuthorAnalyticsService, "log_view", _explode)

        response = authenticated_client.get("/api/v2/models/catalog/test_view_failure")
        assert response.status_code == 200
        assert response.json()["id"] == "test_view_failure"
