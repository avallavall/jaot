"""Comprehensive tests for cron scheduling (CRON-06, CRON-07, CRON-08).

Covers:
- Cron validation: valid, invalid, too-frequent expressions
- Credit pre-check: skip on insufficient balance, estimate from last run, default estimate
- Overlap detection: active cron run causes skip, manual runs not affected
- Failure escalation: auto-disable after 5 consecutive failures, success resets
- Tier limits: FREE cannot create, STARTER limited to 3
- Schedule CRUD: create, read, update, delete via service
- Disabled trigger skip

Mock-driven tests have been converted to real db_session integration tests
following the pattern in tests/test_trigger_execution.py.
"""

import hashlib
import secrets
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.models import Organization, User
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.models.trigger import SolveTrigger, TriggerRun, TriggerSchedule
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

# Real-DB helpers (mirror tests/test_trigger_execution.py)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _make_real_doc(db, org: Organization, user: User) -> ModelBuilderDocument:
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=org.id,
        created_by=user.id,
        name="Cron Test Doc",
        canvas_json={"nodes": [], "edges": []},
        model_json={
            "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
            "constraints": [],
            "objective": {"expression": "x", "sense": "maximize"},
        },
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    db.flush()
    return doc


def _make_real_version(db, doc: ModelBuilderDocument) -> ModelVersion:
    ver = ModelVersion(
        id=generate_id("ver_"),
        document_id=doc.id,
        organization_id=doc.organization_id,
        canvas_json=doc.canvas_json,
        model_json=doc.model_json,
        change_summary="Initial version",
        is_named=True,
        version_name="v1.0",
        version_description=None,
        sequence=1,
        created_at=utcnow(),
    )
    db.add(ver)
    db.flush()
    return ver


def _make_real_trigger(
    db,
    org: Organization,
    user: User,
    doc: ModelBuilderDocument,
    ver: ModelVersion,
    *,
    is_enabled: bool = True,
) -> SolveTrigger:
    now = utcnow()
    trigger = SolveTrigger(
        id=generate_id("trg_"),
        organization_id=org.id,
        created_by=user.id,
        name="Cron Test Trigger",
        description=None,
        document_id=doc.id,
        version_id=ver.id,
        trigger_secret=_hash(secrets.token_hex(16)),
        override_schema=None,
        webhook_url="https://example.com/cron-hook",
        webhook_secret=None,
        is_enabled=is_enabled,
        total_runs=0,
        last_fired_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(trigger)
    db.flush()
    return trigger


def _make_real_schedule(
    db,
    trigger: SolveTrigger,
    *,
    is_enabled: bool = True,
    consecutive_failures: int = 0,
) -> TriggerSchedule:
    schedule = TriggerSchedule(
        id=generate_id("tsch_"),
        trigger_id=trigger.id,
        organization_id=trigger.organization_id,
        cron_expression="0 9 * * *",
        timezone="UTC",
        is_enabled=is_enabled,
        consecutive_failures=consecutive_failures,
        beat_task_id=None,
    )
    db.add(schedule)
    db.flush()
    return schedule


# TestCronValidation -- validate_cron_expression (pure logic, no mocking)


class TestCronValidation:
    """Test cron expression validation using cronsim."""

    def test_cron_validation_valid(self):
        """Valid cron expression returns next_runs list."""
        from app.services.schedule_service import validate_cron_expression

        result = validate_cron_expression("0 9 * * 1-5", "UTC")
        assert result["valid"] is True
        assert len(result["next_runs"]) == 3
        # Each next_run should be a valid ISO string
        for run_str in result["next_runs"]:
            dt = datetime.fromisoformat(run_str)
            assert dt is not None

    def test_cron_validation_invalid(self):
        """Invalid cron expression raises ValueError."""
        from app.services.schedule_service import validate_cron_expression

        with pytest.raises(ValueError, match="Invalid cron expression"):
            validate_cron_expression("not a cron", "UTC")

    def test_cron_validation_too_frequent(self):
        """Expression firing more than once per hour is rejected."""
        from app.services.schedule_service import validate_cron_expression

        # Every minute -- way too frequent
        with pytest.raises(ValueError, match="too frequently"):
            validate_cron_expression("* * * * *", "UTC")

    def test_cron_validation_invalid_timezone(self):
        """Invalid timezone raises ValueError."""
        from app.services.schedule_service import validate_cron_expression

        with pytest.raises(ValueError, match="Invalid timezone"):
            validate_cron_expression("0 9 * * *", "Fake/Timezone")

    def test_cron_validation_hourly_ok(self):
        """Once per hour (exactly at the limit) is accepted."""
        from app.services.schedule_service import validate_cron_expression

        result = validate_cron_expression("0 * * * *", "UTC")
        assert result["valid"] is True

    def test_min_interval_is_the_operator_s_to_set(self, db_session):
        """The hourly floor is a setting, not a constant baked into the code.

        A half-hourly job is ordinary on hardware that can take it; it used to
        be unreachable because 60 minutes was hardcoded.
        """
        from app.services.platform_settings_service import PlatformSettingsService as PSS
        from app.services.schedule_service import (
            resolve_min_interval_minutes,
            validate_cron_expression,
        )

        # Shipped default still rejects a half-hourly schedule.
        with pytest.raises(ValueError, match="too frequently"):
            validate_cron_expression(
                "*/30 * * * *", "UTC", resolve_min_interval_minutes(db_session)
            )

        PSS.set(db_session, "instance_min_cron_interval_minutes", "15")
        db_session.commit()
        assert (
            validate_cron_expression(
                "*/30 * * * *", "UTC", resolve_min_interval_minutes(db_session)
            )["valid"]
            is True
        )

        # 0 removes the floor entirely, like every other capacity limit.
        PSS.set(db_session, "instance_min_cron_interval_minutes", "0")
        db_session.commit()
        assert (
            validate_cron_expression("* * * * *", "UTC", resolve_min_interval_minutes(db_session))[
                "valid"
            ]
            is True
        )


class TestOverlapDetection:
    """Test overlap detection in cron_fire_task with real DB rows."""

    @patch("app.tasks.cron_tasks.SessionLocal")
    def test_overlap_detection(self, mock_session_local, db_session, test_organization, test_user):
        """Active cron run causes skip with skipped_overlap status."""
        from app.tasks.cron_tasks import cron_fire_task

        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        trigger = _make_real_trigger(db_session, test_organization, test_user, doc, ver)
        _make_real_schedule(db_session, trigger)

        # Insert an active cron run that should cause the overlap skip
        active_run = TriggerRun(
            id=generate_id("trun_"),
            trigger_id=trigger.id,
            organization_id=trigger.organization_id,
            status="running",
            source="cron",
            override_data=None,
            execution_id=None,
            created_at=utcnow(),
        )
        db_session.add(active_run)
        db_session.commit()

        mock_session_local.return_value = db_session
        with patch.object(db_session, "close", lambda: None):
            result = cron_fire_task(trigger_id=trigger.id)

        assert result["status"] == "skipped_overlap"
        # A new skipped_overlap row was persisted (separate from the active run)
        skipped = (
            db_session.query(TriggerRun)
            .filter(TriggerRun.trigger_id == trigger.id)
            .filter(TriggerRun.status == "skipped_overlap")
            .first()
        )
        assert skipped is not None


# TestFailureEscalation -- webhook, auto-disable, notification


class TestFailureEscalation:
    """Test failure escalation logic (CRON-06) with real DB rows."""

    def test_auto_disable_after_5_failures(self, db_session, test_organization, test_user):
        """5 consecutive failures disables schedule + sends webhook + notification."""
        from app.tasks.cron_tasks import _increment_failure_counter

        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        trigger = _make_real_trigger(db_session, test_organization, test_user, doc, ver)
        schedule = _make_real_schedule(db_session, trigger, consecutive_failures=4)
        db_session.commit()

        with (
            patch("app.services.webhook_service.build_webhook_payload") as mock_build,
            patch("app.tasks.webhook_tasks.deliver_webhook_task"),
            patch("app.services.notification_service.NotificationService") as mock_notif_cls,
        ):
            mock_build.return_value = {"event": "trigger.schedule.auto_disabled"}
            mock_notif = MagicMock()
            mock_notif_cls.return_value = mock_notif

            _increment_failure_counter(db_session, schedule, trigger)
            db_session.flush()

        # Real-DB state assertions: in-memory mutation must persist to DB on commit
        db_session.commit()
        fresh_schedule = (
            db_session.query(TriggerSchedule).filter(TriggerSchedule.id == schedule.id).first()
        )
        assert fresh_schedule is not None
        assert fresh_schedule.consecutive_failures == 5
        assert fresh_schedule.is_enabled is False

        # Webhook was sent with the auto_disabled event
        assert mock_build.call_count == 1
        assert mock_build.call_args[1]["event_type"] == "trigger.schedule.auto_disabled"

        # In-app notification was created
        mock_notif.create_notification.assert_called_once()
        notif_kwargs = mock_notif.create_notification.call_args[1]
        assert "auto-disabled" in notif_kwargs["title"]

    @patch("app.tasks.cron_tasks._update_next_run")
    @patch("app.tasks.cron_tasks.SessionLocal")
    def test_success_resets_failures(
        self,
        mock_session_local,
        _mock_update_next_run,
        db_session,
        test_organization,
        test_user,
    ):
        """Successful fire resets consecutive_failures to 0."""
        from app.tasks.cron_tasks import cron_fire_task

        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        trigger = _make_real_trigger(db_session, test_organization, test_user, doc, ver)
        schedule = _make_real_schedule(db_session, trigger, consecutive_failures=3)
        db_session.commit()

        ok_run = TriggerRun(
            id=generate_id("trun_"),
            trigger_id=trigger.id,
            organization_id=trigger.organization_id,
            status="completed",
            source="cron",
            override_data=None,
            execution_id=None,
            created_at=utcnow(),
        )

        mock_session_local.return_value = db_session
        with (
            patch.object(db_session, "close", lambda: None),
            patch("app.services.trigger_service.fire_trigger", return_value=(ok_run, None)),
        ):
            cron_fire_task(trigger_id=trigger.id)

        # Read fresh state from DB
        fresh_schedule = (
            db_session.query(TriggerSchedule).filter(TriggerSchedule.id == schedule.id).first()
        )
        assert fresh_schedule is not None
        assert fresh_schedule.consecutive_failures == 0


class TestTierLimits:
    """Test tier-based schedule limits with real DB rows."""

    # CONTRACT-TEST: 0 means unlimited, never "reject everything" (D-21)
    def test_zero_limit_means_unlimited(self, db_session, test_organization, test_user):
        """The SHIPPED configuration must let a schedule be created.

        Every other test here patches the limit to 1 or 5, so none of them ever
        exercised the value the platform actually ships: 0, which D-21 defined
        as unlimited. With the plain `count >= limit` this raised 403
        "Schedule limit reached (0)" on the very first schedule — cron was
        unusable out of the box.

        No patching on purpose: the real registry default is the whole point.
        """
        from app.services.schedule_service import check_schedule_limit

        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        trigger = _make_real_trigger(db_session, test_organization, test_user, doc, ver)
        _make_real_schedule(db_session, trigger)
        db_session.commit()

        # Does not raise — with the shipped default there is no ceiling.
        check_schedule_limit(db_session, test_organization.id)

    def test_free_limited_to_1_schedule(self, db_session, test_organization, test_user):
        """FREE plan limited to 1 schedule (hits limit when at 1)."""
        from fastapi import HTTPException

        from app.services.schedule_service import check_schedule_limit

        # Seed exactly one real schedule for the org
        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        trigger = _make_real_trigger(db_session, test_organization, test_user, doc, ver)
        _make_real_schedule(db_session, trigger)
        db_session.commit()

        with patch(
            "app.services.platform_settings_service.PlatformSettingsService.get_instance_limits",
            return_value={"max_cron_schedules": 1, "allowed_features": ["cron_scheduling"]},
        ):
            with pytest.raises(HTTPException) as exc_info:
                check_schedule_limit(db_session, test_organization.id)

            assert exc_info.value.status_code == 403
            assert "limit reached" in exc_info.value.detail

    def test_starter_limited_to_5(self, db_session, test_organization, test_user):
        """STARTER plan limited to 5 schedules."""
        from fastapi import HTTPException

        from app.services.schedule_service import check_schedule_limit

        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        # Seed 5 schedules (5 distinct triggers, each with 1 schedule)
        for i in range(5):
            trg = _make_real_trigger(db_session, test_organization, test_user, doc, ver)
            trg.name = f"starter limit trigger {i}"
            _make_real_schedule(db_session, trg)
        db_session.commit()

        with patch(
            "app.services.platform_settings_service.PlatformSettingsService.get_instance_limits",
            return_value={"max_cron_schedules": 5, "allowed_features": ["cron_scheduling"]},
        ):
            with pytest.raises(HTTPException) as exc_info:
                check_schedule_limit(db_session, test_organization.id)

            assert exc_info.value.status_code == 403
            assert "limit reached" in exc_info.value.detail

    def test_starter_allows_within_limit(self, db_session, test_organization, test_user):
        """STARTER plan allows creation when under limit."""
        from app.services.schedule_service import check_schedule_limit

        # Seed 2 schedules (under the 5 limit)
        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        for i in range(2):
            trg = _make_real_trigger(db_session, test_organization, test_user, doc, ver)
            trg.name = f"starter under-limit trigger {i}"
            _make_real_schedule(db_session, trg)
        db_session.commit()

        with patch(
            "app.services.platform_settings_service.PlatformSettingsService.get_instance_limits",
            return_value={"max_cron_schedules": 5, "allowed_features": ["cron_scheduling"]},
        ):
            # Should NOT raise
            check_schedule_limit(db_session, test_organization.id)


class TestScheduleCrud:
    """Test schedule CRUD operations via service with real DB rows."""

    def test_schedule_crud(self, db_session, test_organization, test_user):
        """Create, read, update, delete schedule via service with real DB."""
        from app.services.schedule_service import (
            create_schedule,
            delete_schedule,
            get_schedule_by_trigger,
            update_schedule,
        )

        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        trigger = _make_real_trigger(db_session, test_organization, test_user, doc, ver)
        db_session.commit()

        # CREATE -- Beat may or may not be available; the service has try/except.
        schedule = create_schedule(db_session, trigger, "0 9 * * 1-5", "UTC")
        db_session.commit()
        assert schedule.cron_expression == "0 9 * * 1-5"
        assert schedule.timezone == "UTC"
        assert schedule.is_enabled is True
        assert schedule.organization_id == trigger.organization_id
        assert schedule.trigger_id == trigger.id
        assert schedule.id.startswith("tsch_")

        # READ -- real DB query
        found = get_schedule_by_trigger(db_session, trigger.id)
        assert found is not None
        assert found.id == schedule.id

        # UPDATE
        updated = update_schedule(db_session, schedule, cron_expression="0 12 * * *")
        db_session.commit()
        db_session.refresh(updated)
        assert updated.cron_expression == "0 12 * * *"

        # DELETE
        delete_schedule(db_session, schedule)
        db_session.commit()
        # Row must be gone from the DB
        gone = db_session.query(TriggerSchedule).filter(TriggerSchedule.id == schedule.id).first()
        assert gone is None


class TestDisabledSkip:
    """Test that cron fires skip when trigger or schedule is disabled (real DB)."""

    @patch("app.tasks.cron_tasks.SessionLocal")
    def test_disabled_trigger_skipped(
        self, mock_session_local, db_session, test_organization, test_user
    ):
        """Cron fire skips when trigger is disabled."""
        from app.tasks.cron_tasks import cron_fire_task

        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        trigger = _make_real_trigger(
            db_session, test_organization, test_user, doc, ver, is_enabled=False
        )
        _make_real_schedule(db_session, trigger, is_enabled=True)
        db_session.commit()

        mock_session_local.return_value = db_session
        with patch.object(db_session, "close", lambda: None):
            result = cron_fire_task(trigger_id=trigger.id)
        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"

    @patch("app.tasks.cron_tasks.SessionLocal")
    def test_disabled_schedule_skipped(
        self, mock_session_local, db_session, test_organization, test_user
    ):
        """Cron fire skips when schedule is disabled."""
        from app.tasks.cron_tasks import cron_fire_task

        doc = _make_real_doc(db_session, test_organization, test_user)
        ver = _make_real_version(db_session, doc)
        trigger = _make_real_trigger(
            db_session, test_organization, test_user, doc, ver, is_enabled=True
        )
        _make_real_schedule(db_session, trigger, is_enabled=False)
        db_session.commit()

        mock_session_local.return_value = db_session
        with patch.object(db_session, "close", lambda: None):
            result = cron_fire_task(trigger_id=trigger.id)
        assert result["status"] == "skipped"
        assert result["reason"] == "disabled"
