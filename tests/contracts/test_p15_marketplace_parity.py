"""P1.5 marketplace-fusion — parity CONTRACT-TESTs (fused contract).

Pin the FUSED marketplace contracts: the marketplace serves from the
``ModelProjectListing`` facet with the frozen ``ModelCatalogResponse`` wire
shape; the legacy my-models CRUD and the activate flow are RETIRED (their
routes must stay gone); execute is project-native and stamps
``source_kind="model_project"`` provenance. If a later change breaks one of
these shapes, that is a contract break to reckon with deliberately — not a
test to weaken.

# CONTRACT-TEST: these must survive consolidation passes (see test_quality_proof §6).
"""

import pytest

from app.models import (
    ModelCategory,
    ModelExecution,
    ModelProject,
    ModelProjectListing,
)

pytestmark = pytest.mark.contract

# The frozen wire contract. The frontend + API/MCP consumers depend on exactly
# this key set; the fusion must keep producing it.
_CATALOG_KEYS = {
    "id",
    "name",
    "display_name",
    "description",
    "short_description",
    "scenario_description",
    "category",
    "tags",
    "version",
    "is_official",
    "is_featured",
    "total_activations",
    "total_executions",
    "avg_execution_time_ms",
    "success_rate",
    "avg_rating",
    "author_organization_id",
    "author_name",
    "author_verified",
    # Additive 2026-07-17: whether "Use in studio" can materialize the listing
    # (generator facet or pinned version) — the UI disables the CTA up front.
    "can_open_in_studio",
    "logo_url",
    "screenshot_urls",
    "section_overview",
    "section_features",
    "section_how_it_works",
    "section_example_io",
    "section_changelog",
    "created_at",
    "updated_at",
}


class TestMarketplaceResponseShapes:
    """The wire shapes served to the marketplace UI + API/MCP consumers."""

    # CONTRACT-TEST: catalog browse envelope + item shape (served from listings).
    def test_catalog_list_shape(self, authenticated_client, db_session, test_organization):
        _make_listing(
            db_session,
            test_organization,
            pid="p15_list_shape",
            name="p15listshapeuniq",
            display_name="p15listshapeuniq",
        )
        res = authenticated_client.get("/api/v2/models/catalog?search=p15listshapeuniq")
        assert res.status_code == 200, res.text
        body = res.json()
        # "categories" joined the envelope 2026-08-01: the sidebar filter used to
        # derive its options from the models on the current page, so it offered a
        # different list per page. The facet covers the whole visible catalogue.
        assert set(body.keys()) == {
            "items",
            "total",
            "page",
            "page_size",
            "total_pages",
            "categories",
        }
        item = next(i for i in body["items"] if i["id"] == "p15_list_shape")
        assert set(item.keys()) == _CATALOG_KEYS

    # CONTRACT-TEST: catalog detail shape (served from listings).
    def test_catalog_detail_shape(self, authenticated_client, db_session, test_organization):
        _make_listing(db_session, test_organization, pid="p15_detail_shape")
        res = authenticated_client.get("/api/v2/models/catalog/p15_detail_shape")
        assert res.status_code == 200, res.text
        assert set(res.json().keys()) == _CATALOG_KEYS

    # CONTRACT-TEST: the legacy my-models CRUD is RETIRED (P1.5 G6b) — the single
    # model entity is ModelProject, managed via /api/v2/projects. These routes
    # must stay gone; resurrecting them would reintroduce the second entity.
    def test_my_models_routes_retired(self, authenticated_client, db_session, test_organization):
        # This used to plant an OrganizationModel row first, to show the routes
        # stayed gone even with legacy data present. D-26 dropped that table, so
        # the entity no longer exists at all — the routes must still 404.
        assert authenticated_client.get("/api/v2/models").status_code == 404
        assert authenticated_client.get("/api/v2/models/p15_my_retired").status_code == 404
        assert authenticated_client.get("/api/v2/models/p15_my_retired/schema").status_code == 404
        assert authenticated_client.post("/api/v2/models", json={"name": "x"}).status_code == 404
        assert (
            authenticated_client.patch(
                "/api/v2/models/p15_my_retired", json={"custom_name": "y"}
            ).status_code
            == 404
        )
        assert authenticated_client.delete("/api/v2/models/p15_my_retired").status_code == 404
        # The project-native replacement answers on /api/v2/projects.
        assert authenticated_client.get("/api/v2/projects").status_code == 200

    # CONTRACT-TEST: the legacy activate flow is RETIRED (P1.5 G6c) — using a
    # marketplace model = seeding a fork ModelProject via from-marketplace.
    def test_activate_route_retired(self, authenticated_client, db_session, test_organization):
        _make_listing(db_session, test_organization, pid="p15_activate")
        res = authenticated_client.post("/api/v2/models/catalog/p15_activate/activate", json={})
        assert res.status_code == 404, res.text


class TestMarketplaceTenantIsolation:
    """Org-scoped surfaces must 404 across orgs (no cross-tenant leak)."""

    # CONTRACT-TEST: executing another org's model 404s.
    def test_execute_cross_org_404(self, authenticated_client, db_session, test_organization_2):
        other = ModelProject(
            id="p15_x_project",
            organization_id=test_organization_2.id,
            name="Their model",
            status="active",
            draft_model_json={
                "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
                "objective": {"sense": "minimize", "expression": "x"},
            },
        )
        db_session.add(other)
        db_session.commit()
        res = authenticated_client.post(
            "/api/v2/models/p15_x_project/execute", json={"input_data": {}}
        )
        assert res.status_code == 404, res.text


def _make_listing(db, org, *, pid, **ov):
    """A published ModelProject + its marketplace listing facet (no catalog row)."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Proj " + pid, status="active"))
    db.flush()
    fields = {
        "model_project_id": pid,
        "name": pid,
        "display_name": "Disp " + pid,
        "description": "listing desc",
        "category": ModelCategory.LOGISTICS.value,
        "generator_type": "knapsack",
        "input_schema": {"type": "object"},
        "input_fields": [{"name": "cap"}],
        "example_input": {"cap": 10},
        "version": "1.0.0",
        "status": "published",
        "is_official": False,
        "is_public": True,
        "total_activations": 0,
        "total_executions": 0,
        "is_featured": False,
    }
    fields.update(ov)
    db.add(ModelProjectListing(**fields))
    db.commit()


class TestFusionReadCutover:
    """The marketplace serves browse/detail/schema from the ModelProjectListing facet
    (the model content lives on the project/version; no catalog row involved)."""

    # CONTRACT-TEST: browse returns the listing with the exact ModelCatalogResponse shape.
    def test_browse_serves_from_listings(self, authenticated_client, db_session, test_organization):
        _make_listing(
            db_session, test_organization, pid="p15_fus_browse", display_name="From Listing"
        )
        res = authenticated_client.get("/api/v2/models/catalog?category=logistics")
        assert res.status_code == 200, res.text
        item = next(i for i in res.json()["items"] if i["id"] == "p15_fus_browse")
        assert set(item.keys()) == _CATALOG_KEYS
        assert item["display_name"] == "From Listing"

    # CONTRACT-TEST: detail serves the listing (id = project id) with the same shape.
    def test_detail_serves_from_listings(self, authenticated_client, db_session, test_organization):
        _make_listing(
            db_session, test_organization, pid="p15_fus_detail", description="LISTING ONLY"
        )
        res = authenticated_client.get("/api/v2/models/catalog/p15_fus_detail")
        assert res.status_code == 200, res.text
        body = res.json()
        assert set(body.keys()) == _CATALOG_KEYS
        assert body["id"] == "p15_fus_detail"
        assert body["description"] == "LISTING ONLY"

    # CONTRACT-TEST: schema serves the listing's generator facet.
    def test_schema_serves_from_listings(self, authenticated_client, db_session, test_organization):
        _make_listing(db_session, test_organization, pid="p15_fus_schema", generator_type="vrp")
        res = authenticated_client.get("/api/v2/models/catalog/p15_fus_schema/schema")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["id"] == "p15_fus_schema"
        assert body["generator_type"] == "vrp"

    # CONTRACT-TEST: an unpublished listing 404s (same as an unpublished catalog row).
    def test_unpublished_listing_404(self, authenticated_client, db_session, test_organization):
        _make_listing(db_session, test_organization, pid="p15_fus_draft", status="draft")
        assert authenticated_client.get("/api/v2/models/catalog/p15_fus_draft").status_code == 404


class TestExecuteProvenance:
    """Model execution stamps the provenance the history/navigation rely on."""

    # CONTRACT-TEST: an execute persists origin=marketplace + source_kind=model_project
    # + source_id/model_project_id=<project id> (the navigation seam, fused contract).
    def test_execute_stamps_model_project_provenance(
        self, authenticated_client, db_session, test_organization
    ):
        # A fork of a generator-backed listing (the fused "activated model"):
        # the generic generator renders input_data as the problem itself.
        _make_listing(
            db_session,
            test_organization,
            pid="p15_prov_listing",
            generator_type="generic",
            input_fields=[],
            example_input={},
        )
        fork = ModelProject(
            id="p15_prov_fork",
            organization_id=test_organization.id,
            name="Prov fork",
            status="active",
            source_type="marketplace",
            source_ref="p15_prov_listing",
        )
        db_session.add(fork)
        db_session.commit()

        res = authenticated_client.post(
            "/api/v2/models/p15_prov_fork/execute",
            json={
                "input_data": {
                    "variables": [
                        {"name": "x", "type": "integer", "lower_bound": 0, "upper_bound": 10}
                    ],
                    "objective": {"sense": "maximize", "expression": "x"},
                }
            },
        )
        assert res.status_code == 200, res.text
        exe_id = res.json()["id"]
        row = db_session.query(ModelExecution).filter(ModelExecution.id == exe_id).first()
        assert row is not None
        assert row.origin == "marketplace"
        assert row.source_kind == "model_project"
        assert row.source_id == "p15_prov_fork"
        assert row.model_project_id == "p15_prov_fork"
        assert row.organization_model_id is None

    # CONTRACT-TEST: executing a fork rolls the count onto its SOURCE listing.
    def test_execute_bumps_source_listing_counter(
        self, authenticated_client, db_session, test_organization
    ):
        _make_listing(
            db_session,
            test_organization,
            pid="p15_bump_listing",
            generator_type="generic",
            input_fields=[],
            example_input={},
        )
        fork = ModelProject(
            id="p15_bump_fork",
            organization_id=test_organization.id,
            name="Bump fork",
            status="active",
            source_type="marketplace",
            source_ref="p15_bump_listing",
        )
        db_session.add(fork)
        db_session.commit()

        res = authenticated_client.post(
            "/api/v2/models/p15_bump_fork/execute",
            json={
                "input_data": {
                    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
                    "objective": {"sense": "minimize", "expression": "x"},
                }
            },
        )
        assert res.status_code == 200, res.text
        db_session.expire_all()
        listing = (
            db_session.query(ModelProjectListing)
            .filter(ModelProjectListing.model_project_id == "p15_bump_listing")
            .first()
        )
        assert listing.total_executions == 1
