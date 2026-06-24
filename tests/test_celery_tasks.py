"""Celery task edge case tests (mock-based).

Covers Redis unavailability and progress tracking edge cases that
cannot be tested end-to-end via the real Celery worker pipeline.

For core failure/timeout tests, see tests/integration/test_celery_integration.py.

Requires: docker-compose --profile test up -d (for PostgreSQL)
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from app.domains.solver.tasks.solve_tasks import (
    _get_redis_client,
    _publish_ws_event,
    update_task_progress,
)
from app.models import ModelExecution
from app.shared.utils.datetime_helpers import utcnow


class TestRedisEdgeCases:
    """Tests for Redis unavailability handling in Celery tasks."""

    def test_redis_unavailable_publish_ws_event_no_crash(self):
        """_publish_ws_event returns silently when _get_redis_client returns None."""
        with patch("app.domains.solver.tasks.solve_tasks._get_redis_client", return_value=None):
            # Should not raise any exception
            _publish_ws_event("exe_test123", {"type": "progress", "progress": 0.5})

    def test_redis_connection_error_handled(self):
        """_publish_ws_event handles Redis publish raising ConnectionError."""
        mock_client = MagicMock()
        mock_client.publish.side_effect = ConnectionError("Connection refused")

        with patch(
            "app.domains.solver.tasks.solve_tasks._get_redis_client", return_value=mock_client
        ):
            # Should not propagate the exception
            _publish_ws_event("exe_test456", {"type": "progress", "progress": 0.8})

    def test_redis_unavailable_get_client_returns_none(self):
        """_get_redis_client returns None when Redis connection fails."""
        import app.domains.solver.tasks.solve_tasks as st

        # Reset the global singleton so _get_redis_client attempts a fresh connection
        original = st._redis_client
        st._redis_client = None

        try:
            with patch("redis.Redis.from_url", side_effect=ConnectionError("Connection refused")):
                result = _get_redis_client()
                assert result is None
        finally:
            # Restore original state
            st._redis_client = original


class TestProgressTracking:
    """Tests for task progress update mechanism."""

    def test_progress_update_via_update_state(self):
        """update_task_progress calls current_task.update_state with correct args."""
        mock_task = MagicMock()

        with patch("app.domains.solver.tasks.solve_tasks.current_task", mock_task):
            update_task_progress(
                progress=0.5,
                status="solving",
                message="Iteration 10",
                iteration=10,
                objective_value=42.0,
                gap=0.01,
            )

            mock_task.update_state.assert_called_once()
            call_kwargs = mock_task.update_state.call_args
            assert call_kwargs[1]["state"] == "PROGRESS"
            meta = call_kwargs[1]["meta"]
            assert meta["progress"] == 0.5
            assert meta["status"] == "solving"
            assert meta["message"] == "Iteration 10"
            assert meta["iteration"] == 10
            assert meta["objective_value"] == 42.0
            assert meta["gap"] == 0.01
            assert "timestamp" in meta


class TestPermanentRunningDetection:
    """Tests for detecting stuck executions in permanent RUNNING state."""

    def test_permanent_running_state_detection(self, db_session):
        """Executions stuck in 'running' for >2 hours are detectable by query."""
        two_hours_ago = utcnow() - timedelta(hours=2, minutes=1)

        stuck_execution = ModelExecution(
            id="exe_stuck001",
            organization_id="org_test_detect",
            input_data={"test": True},
            status="running",
            started_at=two_hours_ago,
        )
        # Need an org for the FK
        from app.models import Organization

        org = Organization(
            id="org_test_detect",
            name="Detection Test Org",
            credits_balance=100,
            is_active=True,
        )
        db_session.add(org)
        db_session.flush()
        db_session.add(stuck_execution)
        db_session.commit()

        # Query for stuck executions: running and started more than 2 hours ago
        threshold = utcnow() - timedelta(hours=2)
        stuck = (
            db_session.query(ModelExecution)
            .filter(
                ModelExecution.status == "running",
                ModelExecution.started_at < threshold,
            )
            .all()
        )

        assert len(stuck) >= 1
        stuck_ids = [e.id for e in stuck]
        assert "exe_stuck001" in stuck_ids
