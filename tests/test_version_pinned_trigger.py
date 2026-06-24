"""Tests for version-pinned trigger solving (SCHED-02).

Verifies that ModelVersion snapshots model_json at checkpoint time and that
trigger_solve_task uses version.model_json instead of querying the document.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.services import version_service
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


@pytest.fixture
def test_document(db_session, test_organization):
    """Create a builder document with both canvas_json and model_json."""
    doc = ModelBuilderDocument(
        id=generate_id("doc_"),
        organization_id=test_organization.id,
        name="Test Model",
        canvas_json={"nodes": [{"id": "n1", "data": {"label": "X"}}], "edges": []},
        model_json={
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
            "constraints": [],
            "objectives": [{"expression": "x", "sense": "minimize"}],
        },
    )
    db_session.add(doc)
    db_session.commit()
    db_session.refresh(doc)
    return doc


class TestModelVersionModelJson:
    """ModelVersion ORM model has model_json attribute."""

    def test_model_version_has_model_json_attribute(self):
        """ModelVersion should have a model_json column."""
        assert hasattr(ModelVersion, "model_json")

    def test_model_version_stores_and_retrieves_model_json(
        self, db_session, test_organization, test_document
    ):
        """Creating a ModelVersion with model_json stores and retrieves JSON correctly."""
        model_json_data = {
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0}],
            "constraints": [],
            "objectives": [{"expression": "x", "sense": "minimize"}],
        }
        version = ModelVersion(
            id=generate_id("ver_"),
            document_id=test_document.id,
            organization_id=test_organization.id,
            canvas_json={"nodes": [], "edges": []},
            change_summary="test",
            is_named=False,
            sequence=1,
            model_json=model_json_data,
            created_at=utcnow(),
        )
        db_session.add(version)
        db_session.commit()
        db_session.refresh(version)

        fetched = db_session.query(ModelVersion).filter(ModelVersion.id == version.id).first()
        assert fetched is not None
        assert fetched.model_json == model_json_data

    def test_model_json_defaults_to_none(self, db_session, test_organization, test_document):
        """model_json should default to None when not provided."""
        version = ModelVersion(
            id=generate_id("ver_"),
            document_id=test_document.id,
            organization_id=test_organization.id,
            canvas_json={"nodes": [], "edges": []},
            change_summary="test",
            is_named=False,
            sequence=1,
            created_at=utcnow(),
        )
        db_session.add(version)
        db_session.commit()
        db_session.refresh(version)

        assert version.model_json is None


class TestCheckpointStoresModelJson:
    """create_checkpoint() stores model_json when passed."""

    def test_create_checkpoint_stores_model_json(self, db_session, test_document):
        """create_checkpoint() should store model_json when passed."""
        model_json = {"variables": [{"name": "y"}]}
        version = version_service.create_checkpoint(
            db=db_session,
            document=test_document,
            canvas_json={"nodes": [{"id": "n2", "data": {"label": "Y"}}], "edges": []},
            prev_canvas_json=None,
            model_json=model_json,
        )
        assert version.model_json == model_json

    def test_create_checkpoint_model_json_none_when_not_passed(self, db_session, test_document):
        """create_checkpoint() stores model_json=None when not passed (backward compat)."""
        version = version_service.create_checkpoint(
            db=db_session,
            document=test_document,
            canvas_json={"nodes": [{"id": "n3", "data": {"label": "Z"}}], "edges": []},
            prev_canvas_json=None,
        )
        assert version.model_json is None

    def test_checkpoint_model_json_matches_document(self, db_session, test_document):
        """model_json value matches the document's model_json at checkpoint time."""
        doc_model_json = test_document.model_json
        version = version_service.create_checkpoint(
            db=db_session,
            document=test_document,
            canvas_json={"nodes": [{"id": "n4", "data": {"label": "W"}}], "edges": []},
            prev_canvas_json=None,
            model_json=doc_model_json,
        )
        assert version.model_json == doc_model_json


class TestTriggerSolveUsesVersionModelJson:
    """trigger_solve_task uses version.model_json when populated."""

    def test_uses_version_model_json_over_document(
        self, db_session, test_organization, test_document
    ):
        """When version.model_json is populated, trigger_solve_task uses it as base_model_json."""
        from app.models.trigger import SolveTrigger, TriggerRun

        version_model_json = {"variables": [{"name": "pinned_var"}]}
        version = ModelVersion(
            id=generate_id("ver_"),
            document_id=test_document.id,
            organization_id=test_organization.id,
            canvas_json={"nodes": [], "edges": []},
            change_summary="pinned",
            is_named=True,
            sequence=1,
            model_json=version_model_json,
            created_at=utcnow(),
        )
        db_session.add(version)
        db_session.flush()

        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=test_organization.id,
            created_by=None,
            name="Test Trigger",
            document_id=test_document.id,
            version_id=version.id,
            trigger_secret="fakehash",
            webhook_url="https://example.com/hook",
            is_enabled=True,
            total_runs=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db_session.add(trigger)
        db_session.flush()

        run = TriggerRun(
            id=generate_id("run_"),
            trigger_id=trigger.id,
            organization_id=test_organization.id,
            status="pending",
            created_at=utcnow(),
        )
        db_session.add(run)
        db_session.commit()

        # Capture what gets passed to apply_overrides
        captured_base = {}

        def capture_apply_overrides(base, overrides, schema):
            captured_base["value"] = base
            return base

        with (
            patch("app.tasks.trigger_tasks.SessionLocal", return_value=db_session),
            patch("app.tasks.trigger_tasks._deliver_webhook"),
            patch(
                "app.services.trigger_service.apply_overrides", side_effect=capture_apply_overrides
            ),
            patch("app.schemas.optimization.OptimizationProblem.model_validate") as mock_validate,
            patch("app.domains.solver.services.solver_service.SolverService.solve") as mock_solve,
        ):
            mock_problem = MagicMock()
            mock_validate.return_value = mock_problem

            mock_result = MagicMock()
            mock_result.model_dump.return_value = {
                "status": "optimal",
                "objective_value": 42.0,
                "credits_used": 1,
            }
            mock_solve.return_value = mock_result

            from app.tasks.trigger_tasks import trigger_solve_task

            trigger_solve_task(run.id, trigger.id, None)

            # The base_model_json passed to apply_overrides should be the VERSION's model_json
            assert captured_base["value"] == version_model_json


class TestTriggerSolveFallback:
    """trigger_solve_task falls back correctly when version.model_json is None."""

    def test_fallback_to_doc_model_json(self, db_session, test_organization, test_document):
        """When version.model_json is None, falls back to doc.model_json."""
        from app.models.trigger import SolveTrigger, TriggerRun

        version = ModelVersion(
            id=generate_id("ver_"),
            document_id=test_document.id,
            organization_id=test_organization.id,
            canvas_json={"nodes": [], "edges": []},
            change_summary="no model json",
            is_named=True,
            sequence=1,
            model_json=None,
            created_at=utcnow(),
        )
        db_session.add(version)
        db_session.flush()

        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=test_organization.id,
            created_by=None,
            name="Fallback Trigger",
            document_id=test_document.id,
            version_id=version.id,
            trigger_secret="fakehash",
            webhook_url="https://example.com/hook",
            is_enabled=True,
            total_runs=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db_session.add(trigger)
        db_session.flush()

        run = TriggerRun(
            id=generate_id("run_"),
            trigger_id=trigger.id,
            organization_id=test_organization.id,
            status="pending",
            created_at=utcnow(),
        )
        db_session.add(run)
        db_session.commit()

        # Capture doc model_json before task runs (avoids detached instance issues)
        expected_model_json = dict(test_document.model_json)

        captured_base = {}

        def capture_apply_overrides(base, overrides, schema):
            captured_base["value"] = base
            return base

        with (
            patch("app.tasks.trigger_tasks.SessionLocal", return_value=db_session),
            patch("app.tasks.trigger_tasks._deliver_webhook"),
            patch(
                "app.services.trigger_service.apply_overrides", side_effect=capture_apply_overrides
            ),
            patch("app.schemas.optimization.OptimizationProblem.model_validate") as mock_validate,
            patch("app.domains.solver.services.solver_service.SolverService.solve") as mock_solve,
        ):
            mock_problem = MagicMock()
            mock_validate.return_value = mock_problem

            mock_result = MagicMock()
            mock_result.model_dump.return_value = {
                "status": "optimal",
                "objective_value": 10.0,
                "credits_used": 1,
            }
            mock_solve.return_value = mock_result

            from app.tasks.trigger_tasks import trigger_solve_task

            trigger_solve_task(run.id, trigger.id, None)

            # Should be the document's model_json (fallback)
            assert captured_base["value"] == expected_model_json

    def test_fallback_to_canvas_json_when_both_none(self, db_session, test_organization):
        """When both version.model_json and doc.model_json are None, falls back to canvas_json."""
        doc = ModelBuilderDocument(
            id=generate_id("doc_"),
            organization_id=test_organization.id,
            name="Canvas Only",
            canvas_json={"nodes": [{"id": "c1"}], "edges": []},
            model_json=None,
        )
        db_session.add(doc)
        db_session.flush()

        from app.models.trigger import SolveTrigger, TriggerRun

        version = ModelVersion(
            id=generate_id("ver_"),
            document_id=doc.id,
            organization_id=test_organization.id,
            canvas_json={"nodes": [{"id": "c1"}], "edges": []},
            change_summary="canvas only",
            is_named=True,
            sequence=1,
            model_json=None,
            created_at=utcnow(),
        )
        db_session.add(version)
        db_session.flush()

        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=test_organization.id,
            created_by=None,
            name="Canvas Trigger",
            document_id=doc.id,
            version_id=version.id,
            trigger_secret="fakehash",
            webhook_url="https://example.com/hook",
            is_enabled=True,
            total_runs=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db_session.add(trigger)
        db_session.flush()

        run = TriggerRun(
            id=generate_id("run_"),
            trigger_id=trigger.id,
            organization_id=test_organization.id,
            status="pending",
            created_at=utcnow(),
        )
        db_session.add(run)
        db_session.commit()

        captured_base = {}

        def capture_apply_overrides(base, overrides, schema):
            captured_base["value"] = base
            return base

        with (
            patch("app.tasks.trigger_tasks.SessionLocal", return_value=db_session),
            patch("app.tasks.trigger_tasks._deliver_webhook"),
            patch(
                "app.services.trigger_service.apply_overrides", side_effect=capture_apply_overrides
            ),
            patch("app.schemas.optimization.OptimizationProblem.model_validate") as mock_validate,
            patch("app.domains.solver.services.solver_service.SolverService.solve") as mock_solve,
        ):
            mock_problem = MagicMock()
            mock_validate.return_value = mock_problem

            mock_result = MagicMock()
            mock_result.model_dump.return_value = {
                "status": "optimal",
                "objective_value": 0.0,
                "credits_used": 1,
            }
            mock_solve.return_value = mock_result

            from app.tasks.trigger_tasks import trigger_solve_task

            trigger_solve_task(run.id, trigger.id, None)

            # Should contain canvas data as fallback
            assert "canvas" in captured_base["value"]


class TestVersionResponseIncludesModelJson:
    """Version API response includes model_json field."""

    def test_get_version_includes_model_json(
        self, authenticated_client, db_session, test_organization, test_document
    ):
        """GET /api/v2/builder/{doc_id}/versions/{ver_id} response includes model_json."""
        version = ModelVersion(
            id=generate_id("ver_"),
            document_id=test_document.id,
            organization_id=test_organization.id,
            canvas_json={"nodes": [], "edges": []},
            change_summary="with model_json",
            is_named=False,
            sequence=1,
            model_json={"variables": [{"name": "x"}]},
            created_at=utcnow(),
        )
        db_session.add(version)
        db_session.commit()

        resp = authenticated_client.get(f"/api/v2/builder/{test_document.id}/versions/{version.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "model_json" in data
        assert data["model_json"] == {"variables": [{"name": "x"}]}

    def test_get_version_model_json_null_when_absent(
        self, authenticated_client, db_session, test_organization, test_document
    ):
        """model_json is null in response when version has no model_json."""
        version = ModelVersion(
            id=generate_id("ver_"),
            document_id=test_document.id,
            organization_id=test_organization.id,
            canvas_json={"nodes": [], "edges": []},
            change_summary="no model_json",
            is_named=False,
            sequence=2,
            created_at=utcnow(),
        )
        db_session.add(version)
        db_session.commit()

        resp = authenticated_client.get(f"/api/v2/builder/{test_document.id}/versions/{version.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "model_json" in data
        assert data["model_json"] is None
