"""P2 centralization — seed a ModelProject from a template or a marketplace model.

Covers ``POST /api/v2/projects/from-template/{id}`` and ``/from-marketplace/{id}``:
the source is materialized through the SAME ``TemplateEngine`` the solve routes use,
the new project is born with source provenance + a v1 commit, and unknown / unpublished
ids return 404. These are the funnels that make "Use a template" / "Use a marketplace
model" drop the user straight into a versioned workspace.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.data.templates import load_all_templates
from app.models import ModelCatalog

# A real YAML template (first one) — guarantees its generator + example_input exist.
_TEMPLATE = load_all_templates()[0]


def _published_catalog(
    db: Session, *, status: str = "published", is_public: bool = True
) -> ModelCatalog:
    """A marketplace catalog row reusing a real generator + example input."""
    model = ModelCatalog(
        id="cat_p2_seed_test",
        name="p2_seed_test",
        display_name="P2 Seed Test Model",
        description="A catalog model used by the from-marketplace seeding test.",
        category="general",
        generator_type=_TEMPLATE.generator_type,
        input_schema={},
        input_fields=[],
        example_input=_TEMPLATE.example_input,
        status=status,
        is_public=is_public,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


class TestSeedFromTemplate:
    def test_happy_path_creates_committed_project(self, authenticated_client: TestClient):
        resp = authenticated_client.post(f"/api/v2/projects/from-template/{_TEMPLATE.id}")
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["id"].startswith("mp_")
        assert data["source_type"] == "template"
        assert data["source_ref"] == _TEMPLATE.id
        # Born with history: example_input materialized into the draft + v1 committed.
        assert data["committed_count"] == 1
        assert data["current_version_id"] is not None
        assert data["draft_model_json"]
        assert data["draft_model_json"].get("variables")

    def test_version_snapshot_holds_the_materialized_model(
        self, authenticated_client: TestClient
    ):
        pid = authenticated_client.post(
            f"/api/v2/projects/from-template/{_TEMPLATE.id}"
        ).json()["id"]
        versions = authenticated_client.get(f"/api/v2/projects/{pid}/versions").json()
        assert len(versions) == 1
        assert versions[0]["sequence"] == 1

    def test_unknown_template_404(self, authenticated_client: TestClient):
        resp = authenticated_client.post("/api/v2/projects/from-template/does_not_exist_xyz")
        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient):
        resp = client.post(f"/api/v2/projects/from-template/{_TEMPLATE.id}")
        assert resp.status_code in (401, 403)


class TestSeedFromMarketplace:
    def test_happy_path_from_published_catalog(
        self, authenticated_client: TestClient, db_session: Session
    ):
        model = _published_catalog(db_session)
        resp = authenticated_client.post(f"/api/v2/projects/from-marketplace/{model.id}")
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["id"].startswith("mp_")
        assert data["source_type"] == "marketplace"
        assert data["source_ref"] == model.id
        assert data["committed_count"] == 1
        assert data["draft_model_json"].get("variables")

    def test_unknown_model_404(self, authenticated_client: TestClient):
        resp = authenticated_client.post("/api/v2/projects/from-marketplace/nope_xyz")
        assert resp.status_code == 404

    def test_unpublished_catalog_not_resolved_404(
        self, authenticated_client: TestClient, db_session: Session
    ):
        # A draft (unpublished) catalog row must NOT be reachable as a seed source.
        model = _published_catalog(db_session, status="draft")
        resp = authenticated_client.post(f"/api/v2/projects/from-marketplace/{model.id}")
        assert resp.status_code == 404

    def test_hidden_catalog_not_resolved_404(
        self, authenticated_client: TestClient, db_session: Session
    ):
        # An admin-hidden model (is_public=False) — even if published — must NOT be
        # materializable by id, mirroring the public catalog listing filter.
        model = _published_catalog(db_session, is_public=False)
        resp = authenticated_client.post(f"/api/v2/projects/from-marketplace/{model.id}")
        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient):
        resp = client.post("/api/v2/projects/from-marketplace/cat_p2_seed_test")
        assert resp.status_code in (401, 403)
