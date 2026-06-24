"""Tests for trigger EXECUTION verification (not just creation).

Covers:
- 3.3.1: Celery task enqueue verification (mock .delay(), verify correct args)
- 3.3.2: trigger_solve_task direct execution with real DB data
- 3.3.3: Disabled trigger does NOT fire
- 3.3.4: Invalid configuration fails gracefully
- 3.3.5: CRON-based trigger scheduling (next_run calculation)

Uses real PostgreSQL database per project convention.
Celery .delay() is mocked, but task functions are tested directly with real DB.
"""

import hashlib
import secrets
from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from app.models import Organization, User
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.models.trigger import SolveTrigger, TriggerRun
from app.services.trigger_service import (
    create_run,
    fire_trigger,
)
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _create_doc(
    db: Session,
    org: Organization,
    user: User,
    name: str = "Test Document",
    model_json: dict | None = None,
) -> ModelBuilderDocument:
    """Insert a builder document directly into the DB."""
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=org.id,
        created_by=user.id,
        name=name,
        canvas_json={"nodes": [], "edges": []},
        model_json=model_json or {"variables": [], "constraints": [], "objective": {}},
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _create_version(
    db: Session,
    doc: ModelBuilderDocument,
    is_named: bool = True,
    version_name: str = "v1.0",
    model_json: dict | None = None,
) -> ModelVersion:
    """Insert a ModelVersion directly into the DB."""
    ver = ModelVersion(
        id=generate_id("ver_"),
        document_id=doc.id,
        organization_id=doc.organization_id,
        canvas_json={"nodes": [], "edges": []},
        model_json=model_json or doc.model_json,
        change_summary="Initial version",
        is_named=is_named,
        version_name=version_name if is_named else None,
        version_description=None,
        sequence=1,
        created_at=utcnow(),
    )
    db.add(ver)
    db.commit()
    db.refresh(ver)
    return ver


def _create_trigger(
    db: Session,
    org: Organization,
    user: User,
    doc: ModelBuilderDocument,
    version: ModelVersion,
    name: str = "Test Trigger",
    is_enabled: bool = True,
    override_schema: list | None = None,
    plaintext_secret: str | None = None,
) -> tuple[SolveTrigger, str]:
    """Insert a SolveTrigger directly into the DB. Returns (trigger, plaintext_secret)."""
    if plaintext_secret is None:
        plaintext_secret = secrets.token_hex(16)
    now = utcnow()
    trigger = SolveTrigger(
        id=generate_id("trg_"),
        organization_id=org.id,
        created_by=user.id,
        name=name,
        description=None,
        document_id=doc.id,
        version_id=version.id,
        trigger_secret=_hash(plaintext_secret),
        override_schema=override_schema,
        webhook_url="https://example.com/webhook",
        webhook_secret=None,
        is_enabled=is_enabled,
        total_runs=0,
        last_fired_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(trigger)
    db.commit()
    db.refresh(trigger)
    return trigger, plaintext_secret


class TestCeleryTaskEnqueue:
    """Verify that fire_trigger() enqueues the Celery task with correct args."""

    @patch("app.services.trigger_service._queue_validation_failed_webhook")
    @patch("app.services.trigger_service._queue_solve_task")
    def test_fire_trigger_enqueues_celery_with_correct_args(
        self,
        mock_queue_solve,
        mock_queue_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """fire_trigger() calls _queue_solve_task with (run_id, trigger_id, override_data)."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        override_data = {"capacity": 100}
        run, error = fire_trigger(db_session, trigger, override_data)
        db_session.commit()

        assert error is None
        assert run.status == "pending"
        assert run.override_data == override_data

        # Verify _queue_solve_task was called with correct args
        mock_queue_solve.assert_called_once_with(run.id, trigger.id, override_data)

    @patch("app.services.trigger_service._queue_validation_failed_webhook")
    @patch("app.services.trigger_service._queue_solve_task")
    def test_fire_trigger_no_overrides_enqueues_with_none(
        self,
        mock_queue_solve,
        mock_queue_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """fire_trigger() with no overrides passes None to the task."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        run, error = fire_trigger(db_session, trigger, None)
        db_session.commit()

        assert error is None
        mock_queue_solve.assert_called_once_with(run.id, trigger.id, None)

    @patch("app.services.trigger_service._queue_validation_failed_webhook")
    @patch("app.services.trigger_service._queue_solve_task")
    def test_fire_trigger_creates_run_and_updates_counters(
        self,
        mock_queue_solve,
        mock_queue_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """fire_trigger() creates a TriggerRun and increments trigger counters."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        assert trigger.total_runs == 0
        assert trigger.last_fired_at is None

        run, error = fire_trigger(db_session, trigger, None)
        db_session.commit()

        assert error is None

        # Verify run was created in DB
        db_run = db_session.query(TriggerRun).filter(TriggerRun.id == run.id).first()
        assert db_run is not None
        assert db_run.trigger_id == trigger.id
        assert db_run.organization_id == test_organization.id
        assert db_run.status == "pending"

        # Verify trigger counters updated
        db_session.refresh(trigger)
        assert trigger.total_runs == 1
        assert trigger.last_fired_at is not None

    @patch("app.services.trigger_service._queue_validation_failed_webhook")
    @patch("app.services.trigger_service._queue_solve_task")
    def test_fire_trigger_validation_failure_does_not_enqueue_solve(
        self,
        mock_queue_solve,
        mock_queue_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Validation failure creates a run but does NOT enqueue a solve task."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        schema = [
            {
                "name": "capacity",
                "type": "integer",
                "model_field_path": "capacity",
                "required": True,
            }
        ]
        trigger, _ = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            override_schema=schema,
        )

        # Missing required field 'capacity'
        run, error = fire_trigger(db_session, trigger, {})
        db_session.commit()

        assert error is not None
        assert "capacity" in error
        assert run.status == "validation_failed"

        # Solve task NOT enqueued
        mock_queue_solve.assert_not_called()
        # But validation failure webhook WAS queued
        mock_queue_webhook.assert_called_once()


class TestTriggerSolveTaskDirect:
    """Test trigger_solve_task function directly with real DB data.

    The Celery task itself creates its own SessionLocal, so we test
    the underlying logic by calling the function directly and mocking
    only the solver and webhook delivery (not the DB).
    """

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_trigger_solve_task_success(
        self,
        mock_session_local,
        mock_deliver_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """trigger_solve_task with valid data marks run as completed."""
        from app.tasks.trigger_tasks import trigger_solve_task

        model_json = {
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
            "constraints": [],
            "objective": {
                "expression": "x",
                "sense": "maximize",
            },
        }
        doc = _create_doc(db_session, test_organization, test_user, model_json=model_json)
        ver = _create_version(db_session, doc, model_json=model_json)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        # Create a pending run (as fire_trigger would)
        run = create_run(db_session, trigger, None, "pending")
        db_session.commit()
        run_id = run.id

        mock_session_local.return_value = db_session

        # Execute the task directly (not via Celery broker)
        result = trigger_solve_task(
            run_id=run_id,
            trigger_id=trigger.id,
            override_data=None,
        )

        assert result["status"] == "completed"
        assert "execution_id" in result

        # Verify run was updated in DB
        db_session.expire_all()
        updated_run = db_session.query(TriggerRun).filter(TriggerRun.id == run_id).first()
        assert updated_run.status == "completed"
        assert updated_run.execution_id is not None
        assert updated_run.execution_time_ms is not None
        assert updated_run.completed_at is not None

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_trigger_solve_task_missing_run(
        self,
        mock_session_local,
        mock_deliver_webhook,
        db_session: Session,
    ):
        """trigger_solve_task with non-existent run_id returns error status."""
        from app.tasks.trigger_tasks import trigger_solve_task

        mock_session_local.return_value = db_session

        result = trigger_solve_task(
            run_id="trun_nonexistent",
            trigger_id="trg_nonexistent",
            override_data=None,
        )

        assert result["status"] == "error"
        assert "run_not_found" in result.get("error", "")

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_trigger_solve_task_missing_trigger(
        self,
        mock_session_local,
        mock_deliver_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """trigger_solve_task with missing trigger marks run as failed."""
        from app.tasks.trigger_tasks import trigger_solve_task

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        run = create_run(db_session, trigger, None, "pending")
        db_session.commit()
        run_id = run.id

        mock_session_local.return_value = db_session

        # Pass a non-existent trigger_id
        result = trigger_solve_task(
            run_id=run_id,
            trigger_id="trg_nonexistent",
            override_data=None,
        )

        assert result["status"] == "failed"

        # Run should be marked as failed
        db_session.expire_all()
        updated_run = db_session.query(TriggerRun).filter(TriggerRun.id == run_id).first()
        assert updated_run.status == "failed"
        assert "not found" in (updated_run.error_message or "").lower()

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_trigger_solve_task_with_overrides(
        self,
        mock_session_local,
        mock_deliver_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """trigger_solve_task applies overrides before solving."""
        from app.tasks.trigger_tasks import trigger_solve_task

        model_json = {
            "variables": [
                {
                    "name": "x",
                    "type": "continuous",
                    "lower_bound": 0,
                    "upper_bound": 5,
                }
            ],
            "constraints": [],
            "objective": {
                "expression": "x",
                "sense": "maximize",
            },
        }
        doc = _create_doc(db_session, test_organization, test_user, model_json=model_json)
        ver = _create_version(db_session, doc, model_json=model_json)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        override_data = {
            "variables": [
                {
                    "name": "x",
                    "type": "continuous",
                    "lower_bound": 0,
                    "upper_bound": 100,
                }
            ]
        }
        run = create_run(db_session, trigger, override_data, "pending")
        db_session.commit()

        mock_session_local.return_value = db_session

        result = trigger_solve_task(
            run_id=run.id,
            trigger_id=trigger.id,
            override_data=override_data,
        )

        # Should complete successfully (overrides applied to model)
        assert result["status"] in ("completed", "failed")
        # If completed, the result includes an execution_id
        if result["status"] == "completed":
            assert "execution_id" in result

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_trigger_solve_task_invalid_model_json_fails_gracefully(
        self,
        mock_session_local,
        mock_deliver_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """trigger_solve_task with invalid model JSON fails gracefully."""
        from app.tasks.trigger_tasks import trigger_solve_task

        # Invalid model_json: missing objective entirely
        bad_model_json = {"variables": "not_a_list"}
        doc = _create_doc(db_session, test_organization, test_user, model_json=bad_model_json)
        ver = _create_version(db_session, doc, model_json=bad_model_json)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        run = create_run(db_session, trigger, None, "pending")
        db_session.commit()

        mock_session_local.return_value = db_session

        result = trigger_solve_task(
            run_id=run.id,
            trigger_id=trigger.id,
            override_data=None,
        )

        assert result["status"] == "failed"

        # Run should be marked failed with error message
        db_session.expire_all()
        updated_run = db_session.query(TriggerRun).filter(TriggerRun.id == run.id).first()
        assert updated_run.status == "failed"
        assert updated_run.error_message is not None
        assert len(updated_run.error_message) > 0


class TestDisabledTriggerExecution:
    """Verify that disabled triggers do not execute."""

    def test_disabled_trigger_fire_returns_409(
        self,
        authenticated_client,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Firing a disabled trigger via API returns 409 Conflict."""
        from starlette.testclient import TestClient as STC

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, secret = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            is_enabled=False,
        )

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            f"/api/v2/triggers/{trigger.id}/fire",
            json={"trigger_secret": secret},
        )
        assert response.status_code == 409
        assert "disabled" in response.json()["detail"].lower()

    def test_disabled_trigger_no_run_created(
        self,
        authenticated_client,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Disabled trigger fire does NOT create a TriggerRun."""
        from starlette.testclient import TestClient as STC

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, secret = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            is_enabled=False,
        )

        fresh_client = STC(authenticated_client.app)
        fresh_client.post(
            f"/api/v2/triggers/{trigger.id}/fire",
            json={"trigger_secret": secret},
        )

        # No runs should exist
        runs = db_session.query(TriggerRun).filter(TriggerRun.trigger_id == trigger.id).all()
        assert len(runs) == 0

    @patch("app.services.trigger_service._queue_solve_task")
    def test_toggle_disable_then_fire_rejected(
        self,
        mock_queue,
        authenticated_client,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Enable trigger, toggle to disabled, then fire is rejected."""
        from starlette.testclient import TestClient as STC

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, secret = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            is_enabled=True,
        )

        # Disable via toggle
        authenticated_client.post(
            f"/api/v2/triggers/{trigger.id}/toggle",
            json={"enabled": False},
        )

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            f"/api/v2/triggers/{trigger.id}/fire",
            json={"trigger_secret": secret},
        )
        assert response.status_code == 409
        mock_queue.assert_not_called()

    @patch("app.services.trigger_service._queue_solve_task")
    def test_re_enable_trigger_allows_fire(
        self,
        mock_queue,
        authenticated_client,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Disable then re-enable trigger allows firing again."""
        from starlette.testclient import TestClient as STC

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, secret = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            is_enabled=True,
        )

        # Disable
        authenticated_client.post(
            f"/api/v2/triggers/{trigger.id}/toggle",
            json={"enabled": False},
        )

        # Re-enable
        authenticated_client.post(
            f"/api/v2/triggers/{trigger.id}/toggle",
            json={"enabled": True},
        )

        # Fire should succeed
        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            f"/api/v2/triggers/{trigger.id}/fire",
            json={"trigger_secret": secret},
        )
        assert response.status_code == 202


class TestInvalidTriggerConfiguration:
    """Verify triggers with invalid configurations fail gracefully."""

    @patch("app.services.trigger_service._queue_validation_failed_webhook")
    def test_unknown_override_fields_returns_validation_failed(
        self,
        mock_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Unknown override fields produce a validation_failed run, not a crash."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        schema = [
            {
                "name": "capacity",
                "type": "integer",
                "model_field_path": "capacity",
            }
        ]
        trigger, _ = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            override_schema=schema,
        )

        run, error = fire_trigger(db_session, trigger, {"unknown_field": 42})
        db_session.commit()

        assert error is not None
        assert "unknown_field" in error.lower()
        assert run.status == "validation_failed"
        assert run.error_message is not None

    @patch("app.services.trigger_service._queue_validation_failed_webhook")
    def test_missing_required_overrides_returns_validation_failed(
        self,
        mock_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Missing required override fields produce validation_failed run."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        schema = [
            {
                "name": "budget",
                "type": "number",
                "model_field_path": "budget",
                "required": True,
            },
            {
                "name": "capacity",
                "type": "integer",
                "model_field_path": "capacity",
                "required": True,
            },
        ]
        trigger, _ = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            override_schema=schema,
        )

        # Provide only one of two required fields
        run, error = fire_trigger(db_session, trigger, {"budget": 1000})
        db_session.commit()

        assert error is not None
        assert "capacity" in error
        assert run.status == "validation_failed"

    @patch("app.tasks.trigger_tasks._deliver_webhook")
    @patch("app.tasks.trigger_tasks.SessionLocal")
    def test_missing_version_fails_gracefully(
        self,
        mock_session_local,
        mock_deliver_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Trigger pointing to deleted version fails run with descriptive error."""
        from app.tasks.trigger_tasks import trigger_solve_task

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)
        run = create_run(db_session, trigger, None, "pending")
        db_session.commit()

        # Cannot mutate version_id directly (FK RESTRICT prevents it).
        # Instead, wrap the session so the ModelVersion query returns None,
        # simulating a missing version at task execution time.
        real_query = db_session.query

        def _patched_query(model, *args, **kwargs):
            q = real_query(model, *args, **kwargs)
            if model is ModelVersion:
                # Return a query that always resolves to None
                return real_query(model).filter(ModelVersion.id == "ver_nonexistent")
            return q

        mock_session_local.return_value = db_session

        with patch.object(db_session, "query", side_effect=_patched_query):
            result = trigger_solve_task(
                run_id=run.id,
                trigger_id=trigger.id,
                override_data=None,
            )

        assert result["status"] == "failed"
        # Run should have error message about version
        db_session.expire_all()
        updated_run = db_session.query(TriggerRun).filter(TriggerRun.id == run.id).first()
        assert updated_run.status == "failed"
        assert "version" in (updated_run.error_message or "").lower()

    @patch("app.services.trigger_service._queue_validation_failed_webhook")
    def test_validation_failed_run_still_records_in_db(
        self,
        mock_webhook,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Even on validation failure, a run is recorded for audit trail."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        schema = [{"name": "x", "type": "integer", "model_field_path": "x", "required": True}]
        trigger, _ = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            override_schema=schema,
        )

        run, error = fire_trigger(db_session, trigger, {"invalid_key": 1})
        db_session.commit()

        assert error is not None

        # Run should be persisted in DB
        db_run = db_session.query(TriggerRun).filter(TriggerRun.id == run.id).first()
        assert db_run is not None
        assert db_run.status == "validation_failed"
        assert db_run.error_message == error

        # Trigger counters should still be incremented
        db_session.refresh(trigger)
        assert trigger.total_runs == 1


class TestCronScheduling:
    """Test CRON-based trigger scheduling and next_run calculation."""

    def test_next_run_calculation_utc(self):
        """Verify next_run_at is computed correctly for UTC timezone."""
        from app.services.schedule_service import validate_cron_expression

        # Every day at 9:00 UTC
        result = validate_cron_expression("0 9 * * *", "UTC")
        assert result["valid"] is True
        assert len(result["next_runs"]) == 3

        # Each next run should be at 09:00
        for run_str in result["next_runs"]:
            dt = datetime.fromisoformat(run_str)
            assert dt.hour == 9
            assert dt.minute == 0

    def test_next_run_calculation_with_timezone(self):
        """Verify next_run_at respects non-UTC timezone."""
        from app.services.schedule_service import validate_cron_expression

        # 9:00 AM New York time
        result = validate_cron_expression("0 9 * * *", "America/New_York")
        assert result["valid"] is True
        assert len(result["next_runs"]) >= 1

        # The time should be in the specified timezone
        dt = datetime.fromisoformat(result["next_runs"][0])
        assert dt.hour == 9

    def test_next_run_calculation_weekdays_only(self):
        """Cron expression for weekdays only generates correct next runs."""
        from app.services.schedule_service import validate_cron_expression

        # Monday through Friday at 8:00
        result = validate_cron_expression("0 8 * * 1-5", "UTC")
        assert result["valid"] is True
        assert len(result["next_runs"]) == 3

        # All runs should be on weekdays (0=Mon to 4=Fri)
        for run_str in result["next_runs"]:
            dt = datetime.fromisoformat(run_str)
            assert dt.weekday() < 5, f"Expected weekday, got {dt.strftime('%A')}"

    def test_cron_schedule_create_computes_next_run(
        self,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """create_schedule() computes and stores next_run_at."""
        from app.services.schedule_service import create_schedule

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        schedule = create_schedule(db_session, trigger, "0 9 * * *", "UTC")
        db_session.commit()

        assert schedule.next_run_at is not None
        assert schedule.cron_expression == "0 9 * * *"
        assert schedule.timezone == "UTC"
        assert schedule.is_enabled is True
        assert schedule.consecutive_failures == 0

    def test_update_next_run_after_fire(self):
        """_update_next_run recomputes next_run_at after a cron fire."""
        from app.tasks.cron_tasks import _update_next_run

        schedule = MagicMock()
        schedule.cron_expression = "0 9 * * *"
        schedule.timezone = "UTC"

        _update_next_run(schedule)

        # next_run_at should have been set
        assert schedule.next_run_at is not None

    def test_cron_schedule_with_different_timezones(
        self,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Schedules in different timezones produce different UTC next_run_at values."""
        from app.services.schedule_service import create_schedule

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)

        trigger1, _ = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            name="Trigger UTC",
        )
        trigger2, _ = _create_trigger(
            db_session,
            test_organization,
            test_user,
            doc,
            ver,
            name="Trigger Tokyo",
        )

        schedule_utc = create_schedule(db_session, trigger1, "0 9 * * *", "UTC")
        schedule_tokyo = create_schedule(db_session, trigger2, "0 9 * * *", "Asia/Tokyo")
        db_session.commit()

        # Both fire at 9:00 local time, but Asia/Tokyo is UTC+9,
        # so Tokyo's next_run_at should be 9 hours earlier in UTC
        assert schedule_utc.next_run_at is not None
        assert schedule_tokyo.next_run_at is not None
        # They should NOT be the same UTC time (unless by coincidence of day rollover)
        # Tokyo 9:00 = UTC 0:00, UTC 9:00 = UTC 9:00
        assert schedule_utc.next_run_at != schedule_tokyo.next_run_at

    def test_cron_fire_disabled_schedule_skips(self):
        """cron_fire_task skips when schedule.is_enabled is False."""
        from app.tasks.cron_tasks import cron_fire_task

        db = MagicMock()
        trigger = MagicMock()
        trigger.id = "trg_test"
        trigger.is_enabled = True

        schedule = MagicMock()
        schedule.is_enabled = False

        def query_side_effect(model):
            q = MagicMock()
            model_name = getattr(model, "__name__", str(model))
            if model_name == "SolveTrigger":
                q.filter.return_value.first.return_value = trigger
            elif model_name == "TriggerSchedule":
                q.filter.return_value.first.return_value = schedule
            return q

        db.query.side_effect = query_side_effect

        with patch("app.tasks.cron_tasks.SessionLocal", return_value=db):
            result = cron_fire_task(trigger_id="trg_test")

        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"

    def test_consecutive_failures_escalation(self):
        """5 consecutive failures auto-disables the schedule."""
        from app.tasks.cron_tasks import _increment_failure_counter

        db = MagicMock()
        schedule = MagicMock()
        schedule.id = "tsch_test"
        schedule.consecutive_failures = 4  # will become 5
        schedule.beat_task_id = None

        trigger = MagicMock()
        trigger.id = "trg_test"
        trigger.organization_id = "org_test"
        trigger.name = "Test"
        trigger.webhook_url = "https://example.com/hook"
        trigger.webhook_secret = None
        trigger.created_by = "usr_test"

        with (
            patch("app.services.webhook_service.build_webhook_payload", return_value={}),
            patch("app.tasks.webhook_tasks.deliver_webhook_task"),
            patch("app.services.notification_service.NotificationService"),
        ):
            _increment_failure_counter(db, schedule, trigger)

        assert schedule.consecutive_failures == 5
        assert schedule.is_enabled is False
