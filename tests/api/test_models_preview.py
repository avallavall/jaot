"""
Tests for Model Preview API.

Tests the preview endpoint that renders a generator-backed model (a ModelProject
resolving a generator listing — P1.5 fusion) into an OptimizationProblem without
solving it.
"""

from app.models import (
    ModelProject,
    ModelProjectListing,
    Organization,
)
from app.shared.utils.datetime_helpers import utcnow

_BUDGET_FIELDS = [
    {"name": "total_budget", "type": "number", "label": "Budget"},
    {"name": "departments", "type": "array", "label": "Departments"},
]

_BUDGET_INPUT = {
    "total_budget": 100000,
    "departments": [
        {"name": "Engineering", "min_pct": 0.2, "max_pct": 0.5},
        {"name": "Marketing", "min_pct": 0.1, "max_pct": 0.3},
    ],
}


def _seed_budget_fork(db, org_id: str, suffix: str, *, fork_status: str = "active") -> str:
    """A fork ModelProject of a budget_allocation generator listing. Returns its id."""
    db.add(
        ModelProject(
            id=f"prevsrc_{suffix}",
            organization_id=org_id,
            name=f"prevsrc_{suffix}",
            status="active",
        )
    )
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=f"prevsrc_{suffix}",
            name=f"prevsrc_{suffix}",
            display_name="Preview Listing",
            description="For preview testing",
            generator_type="budget_allocation",
            input_schema={},
            input_fields=_BUDGET_FIELDS,
            example_input=_BUDGET_INPUT,
            status="published",
            is_public=True,
            author_organization_id=org_id,
        )
    )
    fork = ModelProject(
        id=f"prevfork_{suffix}",
        organization_id=org_id,
        name="Preview fork",
        status=fork_status,
        source_type="marketplace",
        source_ref=f"prevsrc_{suffix}",
    )
    db.add(fork)
    db.commit()
    return fork.id


class TestPreviewModel:
    """Tests for POST /api/v2/models/{model_id}/preview"""

    def test_preview_model_not_found(self, authenticated_client):
        """Test previewing non-existent model returns 404."""
        response = authenticated_client.post(
            "/api/v2/models/nonexistent_model/preview",
            json={"input_data": {}},
        )
        assert response.status_code == 404

    def test_preview_model_archived(self, authenticated_client, db_session, test_organization):
        """Test previewing an archived model returns 404."""
        model_id = _seed_budget_fork(
            db_session, test_organization.id, "inactive", fork_status="archived"
        )

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/preview",
            json={"input_data": {}},
        )
        assert response.status_code == 404

    def test_preview_other_org_returns_404(
        self, authenticated_client, db_session, test_organization
    ):
        """Test previewing a model from another org returns 404."""
        other_org = Organization(
            id="some_other_org_id",
            name="Other Org",
            plan="free",
            created_at=utcnow(),
        )
        db_session.add(other_org)
        db_session.flush()
        model_id = _seed_budget_fork(db_session, "some_other_org_id", "otherorg")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/preview",
            json={"input_data": {}},
        )
        assert response.status_code == 404

    def test_preview_static_project_rejected(
        self, authenticated_client, db_session, test_organization
    ):
        """A non-generator model has no input schema to preview → 422."""
        db_session.add(
            ModelProject(
                id="test_preview_static",
                organization_id=test_organization.id,
                name="Static model",
                status="active",
                draft_model_json={
                    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
                    "objective": {"sense": "minimize", "expression": "x"},
                },
            )
        )
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/models/test_preview_static/preview",
            json={"input_data": {}},
        )
        assert response.status_code == 422
        assert "not generator-backed" in response.json()["detail"]

    def test_preview_returns_optimization_problem(
        self, authenticated_client, db_session, test_organization
    ):
        """Test successful preview returns OptimizationProblem structure."""
        model_id = _seed_budget_fork(db_session, test_organization.id, "success")

        response = authenticated_client.post(
            f"/api/v2/models/{model_id}/preview",
            json={"input_data": _BUDGET_INPUT},
        )

        assert response.status_code == 200
        data = response.json()

        # Should return OptimizationProblem structure
        assert "variables" in data
        assert "objective" in data
        assert "constraints" in data
        assert isinstance(data["variables"], list)
        assert len(data["variables"]) > 0

        # Each variable should have name and type
        for var in data["variables"]:
            assert "name" in var
            assert "type" in var
