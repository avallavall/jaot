"""Import/Export functional tests (Task 3.8).

Tests model import/export through the builder document API:
- Export a document to JSON (GET returns full canvas_json and model_json)
- Import a valid JSON model (PUT updates canvas_json and model_json)
- Import invalid JSON (should fail with clear error)
- Verify exported format contains all necessary data
- Version snapshot and restore as export/import mechanism

Note: JAOT does not have dedicated /import or /export endpoints.
The builder document CRUD API serves as the import/export mechanism:
  - GET /builder/{id}     = export (returns full JSON state)
  - PUT /builder/{id}     = import (accepts canvas_json and model_json)
  - POST /builder/        = import new (creates document with initial state)
  - POST /builder/{id}/versions/  = snapshot (version checkpoint)
  - POST /builder/{id}/versions/{ver_id}/restore = restore (revert)

These tests use the real PostgreSQL test database (not mocks).
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.models.builder_document import ModelBuilderDocument
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _create_doc(
    db: Session,
    org: Organization,
    user: User,
    name: str = "Export Test Document",
    canvas_json: dict | None = None,
    model_json: dict | None = None,
) -> ModelBuilderDocument:
    """Insert a builder document directly into the DB for test setup."""
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=org.id,
        created_by=user.id,
        name=name,
        canvas_json=canvas_json or {},
        model_json=model_json,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


# Sample canvas_json representing a visual model graph
SAMPLE_CANVAS = {
    "nodes": [
        {
            "id": "obj_1",
            "type": "objectiveNode",
            "position": {"x": 100, "y": 100},
            "data": {"label": "Maximize Profit", "sense": "maximize"},
        },
        {
            "id": "var_1",
            "type": "variableNode",
            "position": {"x": 300, "y": 100},
            "data": {"label": "x", "varType": "continuous", "lowerBound": 0},
        },
        {
            "id": "var_2",
            "type": "variableNode",
            "position": {"x": 300, "y": 200},
            "data": {"label": "y", "varType": "continuous", "lowerBound": 0},
        },
        {
            "id": "con_1",
            "type": "constraintNode",
            "position": {"x": 500, "y": 150},
            "data": {"label": "Capacity", "expression": "x + y <= 10"},
        },
    ],
    "edges": [
        {"id": "e1", "source": "var_1", "target": "obj_1"},
        {"id": "e2", "source": "var_2", "target": "obj_1"},
        {"id": "e3", "source": "var_1", "target": "con_1"},
        {"id": "e4", "source": "var_2", "target": "con_1"},
    ],
    "viewport": {"x": 0, "y": 0, "zoom": 1},
}

# Sample model_json representing a serialized OptimizationProblem
SAMPLE_MODEL_JSON = {
    "name": "simple_linear",
    "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
    "variables": [
        {"name": "x", "type": "continuous", "lower_bound": 0},
        {"name": "y", "type": "continuous", "lower_bound": 0},
    ],
    "constraints": [
        {"name": "capacity", "expression": "x + y <= 10"},
        {"name": "resource", "expression": "2*x + y <= 14"},
    ],
}


class TestExportDocument:
    """Tests for exporting builder documents (GET returns full JSON state)."""

    def test_export_returns_full_canvas_json(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /builder/{id} returns the full canvas_json."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json=SAMPLE_CANVAS)
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["canvas_json"] == SAMPLE_CANVAS

    def test_export_returns_model_json(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /builder/{id} returns the model_json (serialized optimization problem)."""
        doc = _create_doc(
            db_session,
            test_organization,
            test_user,
            canvas_json=SAMPLE_CANVAS,
            model_json=SAMPLE_MODEL_JSON,
        )
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["model_json"] == SAMPLE_MODEL_JSON

    def test_export_contains_all_required_fields(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Exported document contains all fields needed for a complete re-import."""
        doc = _create_doc(
            db_session,
            test_organization,
            test_user,
            name="Complete Document",
            canvas_json=SAMPLE_CANVAS,
            model_json=SAMPLE_MODEL_JSON,
        )
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 200

        data = response.json()
        required_fields = {
            "id",
            "organization_id",
            "created_by",
            "name",
            "canvas_json",
            "model_json",
            "is_active",
            "created_at",
            "updated_at",
        }
        missing = required_fields - set(data.keys())
        assert not missing, f"Export missing required fields: {missing}"

    def test_export_preserves_complex_canvas_structure(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Export preserves nested node data, edge connections, and viewport."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json=SAMPLE_CANVAS)
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        data = response.json()

        canvas = data["canvas_json"]
        assert len(canvas["nodes"]) == 4
        assert len(canvas["edges"]) == 4
        assert "viewport" in canvas
        assert canvas["viewport"]["zoom"] == 1

        # Verify node data is preserved
        obj_node = next(n for n in canvas["nodes"] if n["id"] == "obj_1")
        assert obj_node["data"]["sense"] == "maximize"


class TestImportDocument:
    """Tests for importing model data via builder document API."""

    def test_import_canvas_via_update(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PUT /builder/{id} with canvas_json imports a visual model."""
        doc = _create_doc(db_session, test_organization, test_user)

        response = authenticated_client.put(
            f"/api/v2/builder/{doc.id}",
            json={"canvas_json": SAMPLE_CANVAS},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["canvas_json"] == SAMPLE_CANVAS

    def test_import_model_json_via_update(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PUT /builder/{id} with model_json imports an optimization problem."""
        doc = _create_doc(db_session, test_organization, test_user)

        response = authenticated_client.put(
            f"/api/v2/builder/{doc.id}",
            json={"model_json": SAMPLE_MODEL_JSON},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["model_json"] == SAMPLE_MODEL_JSON
        assert data["model_json"]["name"] == "simple_linear"
        assert len(data["model_json"]["variables"]) == 2
        assert len(data["model_json"]["constraints"]) == 2

    def test_import_both_canvas_and_model(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PUT with both canvas_json and model_json imports complete state."""
        doc = _create_doc(db_session, test_organization, test_user)

        response = authenticated_client.put(
            f"/api/v2/builder/{doc.id}",
            json={
                "name": "Imported Model",
                "canvas_json": SAMPLE_CANVAS,
                "model_json": SAMPLE_MODEL_JSON,
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Imported Model"
        assert data["canvas_json"] == SAMPLE_CANVAS
        assert data["model_json"] == SAMPLE_MODEL_JSON

    def test_import_new_document_via_create(
        self,
        authenticated_client: TestClient,
    ):
        """POST /builder/ creates a new document (import as new)."""
        response = authenticated_client.post(
            "/api/v2/builder/",
            json={"name": "Newly Imported Model"},
        )
        assert response.status_code == 201

        data = response.json()
        assert data["name"] == "Newly Imported Model"
        assert data["id"].startswith("bld_")
        assert data["canvas_json"] == {}
        assert data["model_json"] is None

    def test_import_preserves_existing_data_on_partial_update(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Partial import (name only) does not overwrite canvas_json."""
        doc = _create_doc(
            db_session,
            test_organization,
            test_user,
            canvas_json=SAMPLE_CANVAS,
            model_json=SAMPLE_MODEL_JSON,
        )

        response = authenticated_client.put(
            f"/api/v2/builder/{doc.id}",
            json={"name": "Renamed Only"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Renamed Only"
        assert data["canvas_json"] == SAMPLE_CANVAS
        assert data["model_json"] == SAMPLE_MODEL_JSON

    def test_roundtrip_export_then_import(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Full roundtrip: export document, create new, import exported data."""
        # Create and populate source document
        source = _create_doc(
            db_session,
            test_organization,
            test_user,
            name="Source Model",
            canvas_json=SAMPLE_CANVAS,
            model_json=SAMPLE_MODEL_JSON,
        )

        # Export (GET)
        export_resp = authenticated_client.get(f"/api/v2/builder/{source.id}")
        assert export_resp.status_code == 200
        exported = export_resp.json()

        create_resp = authenticated_client.post(
            "/api/v2/builder/",
            json={"name": "Imported Copy"},
        )
        assert create_resp.status_code == 201
        new_doc_id = create_resp.json()["id"]

        # Import (PUT) the exported data into the new document
        import_resp = authenticated_client.put(
            f"/api/v2/builder/{new_doc_id}",
            json={
                "name": "Imported Copy",
                "canvas_json": exported["canvas_json"],
                "model_json": exported["model_json"],
            },
        )
        assert import_resp.status_code == 200

        imported = import_resp.json()
        assert imported["canvas_json"] == exported["canvas_json"]
        assert imported["model_json"] == exported["model_json"]


class TestImportInvalidData:
    """Tests for invalid import attempts."""

    def test_import_to_nonexistent_document(
        self,
        authenticated_client: TestClient,
    ):
        """PUT to a non-existent document ID returns 404."""
        response = authenticated_client.put(
            "/api/v2/builder/bld_does_not_exist",
            json={"canvas_json": SAMPLE_CANVAS},
        )
        assert response.status_code == 404

    def test_import_to_other_orgs_document(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """Cannot import into a document belonging to another organization."""
        other_doc = _create_doc(db_session, test_organization_2, test_user_2)
        response = authenticated_client.put(
            f"/api/v2/builder/{other_doc.id}",
            json={"canvas_json": SAMPLE_CANVAS},
        )
        assert response.status_code == 404

    def test_import_to_deleted_document(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Cannot import into a soft-deleted document."""
        doc = _create_doc(db_session, test_organization, test_user)
        doc.is_active = False
        db_session.commit()

        response = authenticated_client.put(
            f"/api/v2/builder/{doc.id}",
            json={"canvas_json": SAMPLE_CANVAS},
        )
        assert response.status_code == 404

    def test_import_name_exceeds_max_length(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Name exceeding 255 characters should be rejected with 422."""
        doc = _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.put(
            f"/api/v2/builder/{doc.id}",
            json={"name": "x" * 300},
        )
        assert response.status_code == 422


class TestExportFormatCompleteness:
    """Tests that exported documents contain all data needed for re-import."""

    def test_export_preserves_all_node_types(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Exported canvas preserves all node types (objective, variable, constraint)."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json=SAMPLE_CANVAS)
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        data = response.json()

        node_types = {n["type"] for n in data["canvas_json"]["nodes"]}
        assert "objectiveNode" in node_types
        assert "variableNode" in node_types
        assert "constraintNode" in node_types

    def test_export_preserves_edge_connectivity(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Exported canvas preserves edge source/target references."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json=SAMPLE_CANVAS)
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        data = response.json()

        edges = data["canvas_json"]["edges"]
        assert len(edges) == 4

        node_ids = {n["id"] for n in data["canvas_json"]["nodes"]}
        for edge in edges:
            assert edge["source"] in node_ids, (
                f"Edge {edge['id']} references unknown source: {edge['source']}"
            )
            assert edge["target"] in node_ids, (
                f"Edge {edge['id']} references unknown target: {edge['target']}"
            )

    def test_export_model_json_has_optimization_structure(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Exported model_json contains optimization problem structure."""
        doc = _create_doc(
            db_session,
            test_organization,
            test_user,
            model_json=SAMPLE_MODEL_JSON,
        )
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        data = response.json()

        model = data["model_json"]
        assert "name" in model
        assert "objective" in model
        assert "variables" in model
        assert "constraints" in model
        assert model["objective"]["sense"] in ("maximize", "minimize")

    def test_export_null_model_json_when_not_serialized(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """model_json is null for documents that haven't been exported to solver yet."""
        doc = _create_doc(
            db_session,
            test_organization,
            test_user,
            canvas_json=SAMPLE_CANVAS,
            model_json=None,
        )
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        data = response.json()

        assert data["model_json"] is None

    def test_export_empty_canvas_is_valid(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """A document with an empty canvas exports cleanly."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json={})
        response = authenticated_client.get(f"/api/v2/builder/{doc.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["canvas_json"] == {}


class TestVersionSnapshotExport:
    """Tests for version checkpoint creation and retrieval as snapshots."""

    def test_create_version_checkpoint(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """POST /builder/{id}/versions/ creates a snapshot of current canvas state."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json=SAMPLE_CANVAS)

        response = authenticated_client.post(
            f"/api/v2/builder/{doc.id}/versions/",
            json={"canvas_json": SAMPLE_CANVAS},
        )
        assert response.status_code == 201

        data = response.json()
        assert data["canvas_json"] == SAMPLE_CANVAS
        # IDs generated via generate_id("ver_") — must have the prefix.
        assert data["id"].startswith("ver_")

    def test_list_version_history(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /builder/{id}/versions/ lists version snapshots."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json=SAMPLE_CANVAS)

        authenticated_client.post(
            f"/api/v2/builder/{doc.id}/versions/",
            json={"canvas_json": SAMPLE_CANVAS},
        )

        response = authenticated_client.get(f"/api/v2/builder/{doc.id}/versions/")
        assert response.status_code == 200

        data = response.json()
        assert len(data) >= 1

    def test_get_specific_version_snapshot(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /builder/{id}/versions/{ver_id} returns full canvas snapshot."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json=SAMPLE_CANVAS)

        # Create checkpoint
        create_resp = authenticated_client.post(
            f"/api/v2/builder/{doc.id}/versions/",
            json={"canvas_json": SAMPLE_CANVAS},
        )
        assert create_resp.status_code == 201
        version_id = create_resp.json()["id"]

        # Retrieve it
        get_resp = authenticated_client.get(f"/api/v2/builder/{doc.id}/versions/{version_id}")
        assert get_resp.status_code == 200

        data = get_resp.json()
        assert data["canvas_json"] == SAMPLE_CANVAS

    def test_multiple_versions_preserve_history(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Multiple checkpoints create separate version entries."""
        doc = _create_doc(db_session, test_organization, test_user, canvas_json={})

        canvas_v1 = {"nodes": [{"id": "n1", "type": "test"}], "edges": []}
        canvas_v2 = {
            "nodes": [{"id": "n1", "type": "test"}, {"id": "n2", "type": "test"}],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        }

        # Create first checkpoint
        r1 = authenticated_client.post(
            f"/api/v2/builder/{doc.id}/versions/",
            json={"canvas_json": canvas_v1},
        )
        assert r1.status_code == 201

        # Create second checkpoint (different canvas)
        r2 = authenticated_client.post(
            f"/api/v2/builder/{doc.id}/versions/",
            json={"canvas_json": canvas_v2},
        )
        assert r2.status_code == 201

        # List versions — should have at least 2
        list_resp = authenticated_client.get(f"/api/v2/builder/{doc.id}/versions/")
        assert list_resp.status_code == 200
        versions = list_resp.json()
        assert len(versions) >= 2


class TestMultiTenancyIsolation:
    """Verify that import/export respects org boundaries."""

    def test_cannot_export_other_orgs_document(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """User from org1 cannot read (export) org2's documents."""
        other_doc = _create_doc(
            db_session,
            test_organization_2,
            test_user_2,
            canvas_json=SAMPLE_CANVAS,
            model_json=SAMPLE_MODEL_JSON,
        )
        response = authenticated_client.get(f"/api/v2/builder/{other_doc.id}")
        assert response.status_code == 404

    def test_cannot_import_into_other_orgs_document(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """User from org1 cannot write (import) into org2's documents."""
        other_doc = _create_doc(db_session, test_organization_2, test_user_2)
        response = authenticated_client.put(
            f"/api/v2/builder/{other_doc.id}",
            json={"canvas_json": SAMPLE_CANVAS, "model_json": SAMPLE_MODEL_JSON},
        )
        assert response.status_code == 404
