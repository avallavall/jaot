"""P1.5 marketplace-fusion — parity CONTRACT-TESTs.

Pin the CURRENT marketplace / organization-model contracts (the canonical
``build_org_model_response`` resolver, response shapes, execute provenance and
tenant isolation) BEFORE the fusion touches any schema, so the SAME assertions
stay green with the ``MARKETPLACE_FUSION_ENABLED`` cutover both OFF and ON
(P1.5 F4). If a later slice changes one of these shapes, that is a contract
break to reckon with deliberately — not a test to weaken.

# CONTRACT-TEST: these must survive consolidation passes (see test_quality_proof §6).
"""

import pytest

from app.models import (
    ModelCatalog,
    ModelCategory,
    ModelExecution,
    OrganizationModel,
)
from app.shared.utils.model_helpers import build_org_model_response

pytestmark = pytest.mark.contract

# The frozen wire contracts. The frontend + API/MCP consumers depend on exactly
# these key sets; the fusion must keep producing them.
_ORG_MODEL_KEYS = {
    "id",
    "organization_id",
    "catalog_id",
    "custom_name",
    "display_name",
    "description",
    "category",
    "generator_type",
    "is_active",
    "is_favorite",
    "total_executions",
    "last_executed_at",
    "created_at",
    "is_official",
    "tags",
}

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


def _make_catalog(db, *, cid: str, **overrides) -> ModelCatalog:
    fields = {
        "id": cid,
        "name": cid,
        "display_name": "Catalog " + cid,
        "description": "A published catalog model",
        "short_description": "short",
        "category": ModelCategory.GENERAL,
        "generator_type": "generic",
        "input_schema": {},
        "input_fields": [],
        "example_input": {},
        "version": "1.0.0",
        "status": "published",
        "is_official": False,
        "is_public": True,
        "tags": ["alpha", "beta"],
    }
    fields.update(overrides)
    cat = ModelCatalog(**fields)
    db.add(cat)
    db.commit()
    return cat


class TestBuildOrgModelResponseParity:
    """The canonical resolver the fusion reroutes — all three branches."""

    # CONTRACT-TEST: a catalog-linked model resolves its display/description/
    # category/generator/is_official/tags FROM the catalog.
    def test_catalog_branch(self, db_session, test_organization):
        _make_catalog(
            db_session,
            cid="p15_cat_branch",
            display_name="Vehicle Routing",
            description="VRP",
            category=ModelCategory.LOGISTICS,
            generator_type="vrp",
            is_official=True,
            tags=["routing"],
        )
        om = OrganizationModel(
            id="p15_om_catalog",
            organization_id=test_organization.id,
            catalog_id="p15_cat_branch",
            custom_name=None,
            is_active=True,
            total_executions=3,
        )
        db_session.add(om)
        db_session.commit()

        resp = build_org_model_response(om)
        assert set(resp.model_dump().keys()) == _ORG_MODEL_KEYS
        assert resp.display_name == "Vehicle Routing"
        assert resp.description == "VRP"
        assert resp.category == ModelCategory.LOGISTICS.value
        assert resp.generator_type == "vrp"
        assert resp.is_official is True
        assert resp.catalog_id == "p15_cat_branch"
        assert resp.tags == ["routing"]

    # CONTRACT-TEST: custom_name overrides the catalog display_name.
    def test_catalog_branch_custom_name_wins(self, db_session, test_organization):
        _make_catalog(db_session, cid="p15_cat_named", display_name="Default Name")
        om = OrganizationModel(
            id="p15_om_named",
            organization_id=test_organization.id,
            catalog_id="p15_cat_named",
            custom_name="My Rename",
            is_active=True,
        )
        db_session.add(om)
        db_session.commit()
        resp = build_org_model_response(om)
        assert resp.display_name == "My Rename"

    # CONTRACT-TEST: a private model resolves from its private_definition JSON,
    # is_official=False, catalog_id=None.
    def test_private_branch(self, db_session, test_organization):
        om = OrganizationModel(
            id="p15_om_private",
            organization_id=test_organization.id,
            catalog_id=None,
            custom_name=None,
            private_definition={
                "name": "Private Blend",
                "description": "custom blend",
                "category": "manufacturing",
                "generator_type": "blend",
                "tags": ["priv"],
            },
            is_active=True,
        )
        db_session.add(om)
        db_session.commit()

        resp = build_org_model_response(om)
        assert set(resp.model_dump().keys()) == _ORG_MODEL_KEYS
        assert resp.display_name == "Private Blend"
        assert resp.description == "custom blend"
        assert resp.category == "manufacturing"
        assert resp.generator_type == "blend"
        assert resp.is_official is False
        assert resp.catalog_id is None
        assert resp.tags == ["priv"]

    # CONTRACT-TEST: neither catalog nor private_definition → the safe fallback.
    def test_fallback_branch(self, db_session, test_organization):
        om = OrganizationModel(
            id="p15_om_fallback",
            organization_id=test_organization.id,
            catalog_id=None,
            custom_name=None,
            is_active=True,
        )
        db_session.add(om)
        db_session.commit()

        resp = build_org_model_response(om)
        assert set(resp.model_dump().keys()) == _ORG_MODEL_KEYS
        assert resp.display_name == "Unknown Model"
        assert resp.category == "general"
        assert resp.is_official is False
        assert resp.generator_type is None


class TestMarketplaceResponseShapes:
    """The wire shapes served to the marketplace UI + API/MCP consumers."""

    # CONTRACT-TEST: catalog browse envelope + item shape.
    def test_catalog_list_shape(self, authenticated_client, db_session):
        _make_catalog(db_session, cid="p15_list_shape")
        res = authenticated_client.get("/api/v2/models/catalog")
        assert res.status_code == 200, res.text
        body = res.json()
        assert set(body.keys()) == {"items", "total", "page", "page_size", "total_pages"}
        item = next(i for i in body["items"] if i["id"] == "p15_list_shape")
        assert set(item.keys()) == _CATALOG_KEYS

    # CONTRACT-TEST: catalog detail shape.
    def test_catalog_detail_shape(self, authenticated_client, db_session):
        _make_catalog(db_session, cid="p15_detail_shape")
        res = authenticated_client.get("/api/v2/models/catalog/p15_detail_shape")
        assert res.status_code == 200, res.text
        assert set(res.json().keys()) == _CATALOG_KEYS

    # CONTRACT-TEST: my-models list envelope + item = OrganizationModelResponse.
    def test_my_models_list_shape(self, authenticated_client, db_session, test_organization):
        om = OrganizationModel(
            id="p15_my_list",
            organization_id=test_organization.id,
            custom_name="Listed",
            is_active=True,
        )
        db_session.add(om)
        db_session.commit()
        res = authenticated_client.get("/api/v2/models")
        assert res.status_code == 200, res.text
        body = res.json()
        assert {"items", "total", "page", "page_size"} <= set(body.keys())
        item = next(i for i in body["items"] if i["id"] == "p15_my_list")
        assert set(item.keys()) == _ORG_MODEL_KEYS

    # CONTRACT-TEST: my-model detail shape.
    def test_my_model_detail_shape(self, authenticated_client, db_session, test_organization):
        om = OrganizationModel(
            id="p15_my_detail",
            organization_id=test_organization.id,
            custom_name="Detailed",
            is_active=True,
        )
        db_session.add(om)
        db_session.commit()
        res = authenticated_client.get("/api/v2/models/p15_my_detail")
        assert res.status_code == 200, res.text
        assert set(res.json().keys()) == _ORG_MODEL_KEYS

    # CONTRACT-TEST: activate creates an OrganizationModel and returns its response shape.
    def test_activate_creates_org_model(self, authenticated_client, db_session, test_organization):
        _make_catalog(db_session, cid="p15_activate")
        res = authenticated_client.post("/api/v2/models/catalog/p15_activate/activate", json={})
        assert res.status_code == 200, res.text
        body = res.json()
        assert set(body.keys()) == _ORG_MODEL_KEYS
        assert body["catalog_id"] == "p15_activate"
        row = (
            db_session.query(OrganizationModel)
            .filter(
                OrganizationModel.catalog_id == "p15_activate",
                OrganizationModel.organization_id == test_organization.id,
            )
            .first()
        )
        assert row is not None


class TestMarketplaceTenantIsolation:
    """Org-scoped surfaces must 404 across orgs (no cross-tenant leak)."""

    # CONTRACT-TEST: another org's activated model is invisible (404, not 403).
    def test_my_model_cross_org_404(self, authenticated_client, db_session, test_organization_2):
        other = OrganizationModel(
            id="p15_other_org_model",
            organization_id=test_organization_2.id,
            custom_name="Theirs",
            is_active=True,
        )
        db_session.add(other)
        db_session.commit()
        res = authenticated_client.get("/api/v2/models/p15_other_org_model")
        assert res.status_code == 404, res.text

    # CONTRACT-TEST: executing another org's model 404s.
    def test_execute_cross_org_404(self, authenticated_client, db_session, test_organization_2):
        _make_catalog(db_session, cid="p15_x_cat")
        other = OrganizationModel(
            id="p15_x_org_model",
            organization_id=test_organization_2.id,
            catalog_id="p15_x_cat",
            is_active=True,
        )
        db_session.add(other)
        db_session.commit()
        res = authenticated_client.post(
            "/api/v2/models/p15_x_org_model/execute", json={"input_data": {}}
        )
        assert res.status_code == 404, res.text


class TestExecuteProvenance:
    """Marketplace execution stamps the provenance the history/fusion rely on."""

    # CONTRACT-TEST: an execute persists origin=marketplace + source_kind=organization_model
    # + source_id=<model id> (the navigation + P1.5 backfill seam).
    def test_execute_stamps_marketplace_provenance(
        self, authenticated_client, db_session, test_organization
    ):
        _make_catalog(db_session, cid="p15_prov_cat")
        om = OrganizationModel(
            id="p15_prov_om",
            organization_id=test_organization.id,
            catalog_id="p15_prov_cat",
            is_active=True,
        )
        db_session.add(om)
        db_session.commit()

        res = authenticated_client.post(
            "/api/v2/models/p15_prov_om/execute",
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
        assert row.source_kind == "organization_model"
        assert row.source_id == "p15_prov_om"
        assert row.organization_model_id == "p15_prov_om"
