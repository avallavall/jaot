"""P2 centralization — seed a ModelProject from a template or a marketplace model.

Covers ``POST /api/v2/projects/from-template/{id}`` and ``/from-marketplace/{id}``:
the source is materialized through the SAME ``TemplateEngine`` the solve routes use
(generator-backed listings) or by copying a static listing's pinned committed version;
the new project is born with source provenance + a v1 commit, and unknown / unpublished
ids return 404. These are the funnels that make "Use a template" / "Use a marketplace
model" drop the user straight into a versioned workspace (P1.5 fusion: the marketplace
source is a ``ModelProjectListing``, not a catalog row).
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.data.templates import load_all_templates
from app.models import ModelProject, ModelProjectListing, ModelProjectVersion

# A real YAML template (first one) — guarantees its generator + example_input exist.
_TEMPLATE = load_all_templates()[0]


def _generator_listing(
    db: Session, org, *, pid="lst_gen_seed", status="published", is_public=True
) -> str:
    """A generator-backed (official-style) published listing reusing a real generator."""
    db.add(ModelProject(id=pid, organization_id=org.id, name="Gen " + pid, status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Generator Listing",
            description="A generator-backed listing for the from-marketplace seeding test.",
            category="general",
            generator_type=_TEMPLATE.generator_type,
            input_schema={},
            input_fields=[],
            example_input=_TEMPLATE.example_input,
            version="1.0.0",
            status=status,
            is_public=is_public,
        )
    )
    db.commit()
    return pid


def _static_listing(db: Session, org, *, pid="lst_static_seed", model_json) -> str:
    """A static (no generator) published listing whose model is the pinned version."""
    db.add(
        ModelProject(
            id=pid, organization_id=org.id, name="Static " + pid, status="active", committed_count=1
        )
    )
    db.flush()
    version = ModelProjectVersion(
        id=pid + "_v1",
        model_project_id=pid,
        organization_id=org.id,
        sequence=1,
        model_json=model_json,
        content_hash="h_" + pid,
        commit_summary="v1",
    )
    db.add(version)
    db.flush()
    db.get(ModelProject, pid).current_version_id = version.id
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name="Static Listing",
            description="A static published listing for the from-marketplace seeding test.",
            category="general",
            generator_type=None,
            version="1.0.0",
            status="published",
            is_public=True,
            pinned_version_id=version.id,
        )
    )
    db.commit()
    return pid


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

    def test_version_snapshot_holds_the_materialized_model(self, authenticated_client: TestClient):
        pid = authenticated_client.post(f"/api/v2/projects/from-template/{_TEMPLATE.id}").json()[
            "id"
        ]
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
    def test_happy_path_from_generator_listing(
        self, authenticated_client: TestClient, db_session: Session, test_organization
    ):
        pid = _generator_listing(db_session, test_organization)
        resp = authenticated_client.post(f"/api/v2/projects/from-marketplace/{pid}")
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["id"].startswith("mp_")
        assert data["source_type"] == "marketplace"
        assert data["source_ref"] == pid
        assert data["committed_count"] == 1
        # Rendered from the generator facet's example_input.
        assert data["draft_model_json"].get("variables")

    def test_generator_listing_with_user_input(
        self, authenticated_client: TestClient, db_session: Session, test_organization
    ):
        pid = _generator_listing(db_session, test_organization, pid="lst_gen_input")
        # user_input is rendered through the generator instead of example_input.
        body = {"user_input": _TEMPLATE.example_input}
        resp = authenticated_client.post(f"/api/v2/projects/from-marketplace/{pid}", json=body)
        assert resp.status_code == 201, resp.text
        assert resp.json()["draft_model_json"].get("variables")

    def test_static_listing_copies_pinned_version(
        self, authenticated_client: TestClient, db_session: Session, test_organization
    ):
        model_json = {
            "variables": [{"name": "staticvar", "type": "continuous", "lower_bound": 0}],
            "objective": {"sense": "maximize", "expression": "staticvar"},
        }
        pid = _static_listing(db_session, test_organization, model_json=model_json)
        resp = authenticated_client.post(f"/api/v2/projects/from-marketplace/{pid}")
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["source_type"] == "marketplace"
        assert data["committed_count"] == 1
        # The pinned version's model_json was copied verbatim (no generator render).
        names = [v["name"] for v in data["draft_model_json"]["variables"]]
        assert "staticvar" in names

    def test_unknown_model_404(self, authenticated_client: TestClient):
        resp = authenticated_client.post("/api/v2/projects/from-marketplace/nope_xyz")
        assert resp.status_code == 404

    def test_unpublished_listing_not_resolved_404(
        self, authenticated_client: TestClient, db_session: Session, test_organization
    ):
        pid = _generator_listing(db_session, test_organization, pid="lst_draft", status="draft")
        resp = authenticated_client.post(f"/api/v2/projects/from-marketplace/{pid}")
        assert resp.status_code == 404

    def test_hidden_listing_not_resolved_404(
        self, authenticated_client: TestClient, db_session: Session, test_organization
    ):
        pid = _generator_listing(db_session, test_organization, pid="lst_hidden", is_public=False)
        resp = authenticated_client.post(f"/api/v2/projects/from-marketplace/{pid}")
        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient):
        resp = client.post("/api/v2/projects/from-marketplace/lst_gen_seed")
        assert resp.status_code in (401, 403)
