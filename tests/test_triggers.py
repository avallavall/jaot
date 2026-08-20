"""
Tests for the HTTP trigger API (/api/v2/triggers).

Covers:
- CRUD: create, list, get, update, delete, toggle
- Fire: bearer auth, body auth, invalid secret, disabled trigger, overrides, validation failure
- Run history: paginated list, get run detail, rerun
- Service: validate_overrides, apply_overrides
- Multi-tenant isolation
"""

import hashlib
import secrets
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Organization, User
from app.models.builder_document import ModelBuilderDocument
from app.models.model_version import ModelVersion
from app.models.trigger import SolveTrigger, TriggerRun
from app.services.trigger_service import apply_overrides, validate_overrides
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _create_doc(
    db: Session,
    org: Organization,
    user: User,
    name: str = "Test Document",
) -> ModelBuilderDocument:
    """Insert a builder document directly into the DB."""
    now = utcnow()
    doc = ModelBuilderDocument(
        id=generate_id("bld_"),
        organization_id=org.id,
        created_by=user.id,
        name=name,
        canvas_json={"nodes": [], "edges": []},
        model_json={"variables": [], "constraints": [], "objective": {}},
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
) -> ModelVersion:
    """Insert a ModelVersion directly into the DB."""
    ver = ModelVersion(
        id=generate_id("ver_"),
        document_id=doc.id,
        organization_id=doc.organization_id,
        canvas_json={"nodes": [], "edges": []},
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
    override_schema=None,
    plaintext_secret: str = None,
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


def _create_run(
    db: Session,
    trigger: SolveTrigger,
    status: str = "completed",
    override_data: dict = None,
) -> TriggerRun:
    """Insert a TriggerRun directly into the DB."""
    run = TriggerRun(
        id=generate_id("trun_"),
        trigger_id=trigger.id,
        organization_id=trigger.organization_id,
        override_data=override_data,
        status=status,
        webhook_attempts=0,
        created_at=utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _triggers_url(suffix: str = "") -> str:
    return f"/api/v2/triggers{suffix}"


class TestCreateTrigger:
    def test_create_trigger_success(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """POST /triggers returns 201 with trigger_secret in response."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "My Trigger",
                "document_id": doc.id,
                "version_id": ver.id,
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "trigger_secret" in data
        assert len(data["trigger_secret"]) == 64  # hex(32 bytes)
        assert data["name"] == "My Trigger"
        assert data["id"].startswith("trg_")
        assert data["is_enabled"] is True

    def test_create_trigger_secret_not_stored_plaintext(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Trigger secret stored in DB is the SHA-256 hash, not the plaintext."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "Hash Test",
                "document_id": doc.id,
                "version_id": ver.id,
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 201
        plaintext = response.json()["trigger_secret"]

        # Fetch from DB and verify stored value is the hash
        trigger_id = response.json()["id"]
        trigger = db_session.query(SolveTrigger).filter(SolveTrigger.id == trigger_id).first()
        assert trigger is not None
        assert trigger.trigger_secret != plaintext
        assert trigger.trigger_secret == _hash(plaintext)

    def test_create_trigger_missing_fields(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Missing required fields returns 422."""
        response = authenticated_client.post(
            _triggers_url("/"),
            json={"name": "Incomplete"},
        )
        assert response.status_code == 422

    def test_create_trigger_invalid_document(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Non-existent document_id returns 404."""
        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "Bad Doc",
                "document_id": "bld_doesnotexist",
                "version_id": "ver_doesnotexist",
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 404

    def test_create_trigger_invalid_version(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Non-existent version_id (but valid document) returns 404."""
        doc = _create_doc(db_session, test_organization, test_user)
        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "Bad Version",
                "document_id": doc.id,
                "version_id": "ver_doesnotexist",
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 404

    def test_create_trigger_auto_names_unnamed_version(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Creating a trigger with an unnamed version auto-promotes it to named."""
        doc = _create_doc(db_session, test_organization, test_user)
        # Explicitly create an unnamed version
        ver = _create_version(db_session, doc, is_named=False)
        assert not ver.is_named

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "Trigger With Unnamed Ver",
                "document_id": doc.id,
                "version_id": ver.id,
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 201

        # Version should now be named
        db_session.expire(ver)
        ver_refreshed = db_session.get(ModelVersion, ver.id)
        assert ver_refreshed.is_named is True
        assert "Pinned for trigger" in (ver_refreshed.version_name or "")


class TestListTriggers:
    def test_list_triggers(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /triggers returns triggers for the current org."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        _create_trigger(db_session, test_organization, test_user, doc, ver, name="T1")
        _create_trigger(db_session, test_organization, test_user, doc, ver, name="T2")

        response = authenticated_client.get(_triggers_url("/"))
        assert response.status_code == 200
        names = [t["name"] for t in response.json()]
        assert "T1" in names
        assert "T2" in names

    def test_list_triggers_filter_by_document(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /triggers?document_id= filters correctly."""
        doc1 = _create_doc(db_session, test_organization, test_user, name="Doc1")
        doc2 = _create_doc(db_session, test_organization, test_user, name="Doc2")
        ver1 = _create_version(db_session, doc1)
        ver2 = _create_version(db_session, doc2)
        _create_trigger(db_session, test_organization, test_user, doc1, ver1, name="Trig-Doc1")
        _create_trigger(db_session, test_organization, test_user, doc2, ver2, name="Trig-Doc2")

        response = authenticated_client.get(_triggers_url(f"/?document_id={doc1.id}"))
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Trig-Doc1"


class TestGetTrigger:
    def test_get_trigger(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /triggers/{id} returns trigger without trigger_secret, with prefix."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        response = authenticated_client.get(_triggers_url(f"/{trigger.id}"))
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == trigger.id
        assert "trigger_secret" not in data
        assert "trigger_secret_prefix" in data
        assert data["trigger_secret_prefix"].endswith("...")


class TestUpdateTrigger:
    def test_update_trigger(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PATCH /triggers/{id} updates name and webhook_url."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        response = authenticated_client.patch(
            _triggers_url(f"/{trigger.id}"),
            json={"name": "Updated Name", "webhook_url": "https://new.example.com/hook"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert "new.example.com" in data["webhook_url"]

    def test_update_trigger_cannot_change_version_id(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """PATCH with version_id is silently ignored — version_id is immutable."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)
        original_version_id = trigger.version_id

        response = authenticated_client.patch(
            _triggers_url(f"/{trigger.id}"),
            json={"version_id": "ver_should_not_change", "name": "Same"},
        )
        assert response.status_code == 200
        # version_id must not have changed
        assert response.json()["version_id"] == original_version_id


class TestDeleteTrigger:
    def test_delete_trigger(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """DELETE /triggers/{id} returns 204 and trigger is gone on re-get."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        response = authenticated_client.delete(_triggers_url(f"/{trigger.id}"))
        assert response.status_code == 204

        # Verify gone
        response = authenticated_client.get(_triggers_url(f"/{trigger.id}"))
        assert response.status_code == 404


class TestToggleTrigger:
    def test_toggle_trigger_enable_disable(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """POST /triggers/{id}/toggle toggles is_enabled."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(
            db_session, test_organization, test_user, doc, ver, is_enabled=True
        )

        # Disable
        response = authenticated_client.post(
            _triggers_url(f"/{trigger.id}/toggle"), json={"enabled": False}
        )
        assert response.status_code == 200
        assert response.json()["is_enabled"] is False

        # Re-enable
        response = authenticated_client.post(
            _triggers_url(f"/{trigger.id}/toggle"), json={"enabled": True}
        )
        assert response.status_code == 200
        assert response.json()["is_enabled"] is True


class TestFireTrigger:
    @patch("app.services.trigger_service._queue_solve_task")
    def test_fire_trigger_bearer_auth(
        self,
        mock_queue,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Fire with secret in Authorization: Bearer header returns 202."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, secret = _create_trigger(db_session, test_organization, test_user, doc, ver)

        # Use an unauthenticated client — fire is public auth
        from starlette.testclient import TestClient as STC

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            _triggers_url(f"/{trigger.id}/fire"),
            json={},
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert response.status_code == 202
        data = response.json()
        assert "run_id" in data
        assert data["status"] == "pending"

    @patch("app.services.trigger_service._queue_solve_task")
    def test_fire_trigger_body_auth(
        self,
        mock_queue,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Fire with secret in request body returns 202."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, secret = _create_trigger(db_session, test_organization, test_user, doc, ver)

        from starlette.testclient import TestClient as STC

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            _triggers_url(f"/{trigger.id}/fire"),
            json={"trigger_secret": secret},
        )
        assert response.status_code == 202

    def test_fire_trigger_invalid_secret(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Fire with wrong secret returns 401."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        from starlette.testclient import TestClient as STC

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            _triggers_url(f"/{trigger.id}/fire"),
            json={"trigger_secret": "wrong_secret"},
        )
        assert response.status_code == 401

    def test_fire_trigger_missing_secret(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Fire without any secret returns 401."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        from starlette.testclient import TestClient as STC

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            _triggers_url(f"/{trigger.id}/fire"),
            json={},
        )
        assert response.status_code == 401

    def test_fire_trigger_disabled(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Fire on disabled trigger returns 409."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, secret = _create_trigger(
            db_session, test_organization, test_user, doc, ver, is_enabled=False
        )

        from starlette.testclient import TestClient as STC

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            _triggers_url(f"/{trigger.id}/fire"),
            json={"trigger_secret": secret},
        )
        assert response.status_code == 409

    def test_fire_trigger_not_found(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Fire on non-existent trigger returns 404."""
        from starlette.testclient import TestClient as STC

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            _triggers_url("/trg_doesnotexist/fire"),
            json={"trigger_secret": "anysecret"},
        )
        assert response.status_code == 404

    @patch("app.services.trigger_service._queue_solve_task")
    def test_fire_trigger_with_overrides(
        self,
        mock_queue,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Fire with valid overrides returns 202 and run is created."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        # Open schema — any keys allowed
        trigger, secret = _create_trigger(db_session, test_organization, test_user, doc, ver)

        from starlette.testclient import TestClient as STC

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            _triggers_url(f"/{trigger.id}/fire"),
            json={"trigger_secret": secret, "override_data": {"capacity": 100}},
        )
        assert response.status_code == 202

    @patch("app.services.trigger_service._queue_validation_failed_webhook")
    def test_fire_trigger_invalid_overrides(
        self,
        mock_webhook,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Fire with undeclared override keys returns 422 AND creates validation_failed run."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        # Strict schema — only 'capacity' is allowed
        schema = [
            {
                "name": "capacity",
                "type": "integer",
                "model_field_path": "capacity",
                "required": False,
                "description": "Max capacity",
            }
        ]
        trigger, secret = _create_trigger(
            db_session, test_organization, test_user, doc, ver, override_schema=schema
        )

        from starlette.testclient import TestClient as STC

        fresh_client = STC(authenticated_client.app)
        response = fresh_client.post(
            _triggers_url(f"/{trigger.id}/fire"),
            json={
                "trigger_secret": secret,
                "override_data": {"unknown_key": "bad"},
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "run_id" in detail

        # Verify run was created with validation_failed status
        run_id = detail["run_id"]
        run = db_session.query(TriggerRun).filter(TriggerRun.id == run_id).first()
        assert run is not None
        assert run.status == "validation_failed"

    @patch("app.services.trigger_service._queue_solve_task")
    def test_fire_trigger_idempotent_concurrent_no_negative_runs(
        self,
        mock_queue,
        db_engine,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Concurrent fires of the same trigger create N independent runs.

        Documents the current contract: fire_trigger has NO server-side
        idempotency key — every call creates a fresh TriggerRun. Two requests
        racing through threading.Barrier produce exactly two runs, both
        belonging to the trigger and the org, both with status="pending",
        with distinct ids. No partial/negative state, no orphan rows, no
        cross-org leakage.

        If a future change adds idempotency (Idempotency-Key header), this
        test must be updated to assert exactly 1 run.
        """
        import queue
        import threading

        from sqlalchemy.orm import sessionmaker

        from app.services.trigger_service import fire_trigger

        # Seed the trigger using the live db_session, then commit so threads
        # can see it.
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)
        trigger_id = trigger.id
        org_id = test_organization.id
        db_session.commit()

        SessionFactory = sessionmaker(bind=db_engine)
        results: queue.Queue = queue.Queue()
        n_threads = 2
        barrier = threading.Barrier(n_threads, timeout=10)

        def fire_worker(thread_id: int) -> None:
            session = SessionFactory()
            try:
                trg = session.query(SolveTrigger).filter(SolveTrigger.id == trigger_id).first()
                barrier.wait()
                run, error = fire_trigger(session, trg, None)
                session.commit()
                results.put(("ok", run.id, run.status, error))
            except Exception as exc:
                session.rollback()
                results.put(("error", str(exc)))
            finally:
                session.close()

        threads = [
            threading.Thread(target=fire_worker, args=(i,), name=f"fire-{i}")
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        outcomes = []
        while not results.empty():
            outcomes.append(results.get())

        assert len(outcomes) == n_threads, f"expected {n_threads} outcomes, got {outcomes}"
        assert all(o[0] == "ok" for o in outcomes), f"thread errors: {outcomes}"

        run_ids = [o[1] for o in outcomes]
        assert len(set(run_ids)) == n_threads, f"run_ids must be unique, got {run_ids}"

        # Verify both runs persisted in the DB and belong to this trigger+org
        fresh = SessionFactory()
        try:
            persisted = fresh.query(TriggerRun).filter(TriggerRun.trigger_id == trigger_id).all()
            persisted_ids = {r.id for r in persisted}
            assert set(run_ids).issubset(persisted_ids), (
                f"runs missing from DB: created={run_ids}, persisted={persisted_ids}"
            )
            assert len(persisted) == n_threads, (
                f"expected exactly {n_threads} runs for trigger {trigger_id}, got {len(persisted)}"
            )
            for r in persisted:
                assert r.organization_id == org_id
                assert r.status == "pending"
        finally:
            fresh.close()

        # The Celery dispatch happened once per fire (no duplicates suppressed,
        # no extras enqueued).
        assert mock_queue.call_count == n_threads


class TestRunHistory:
    def test_list_runs_paginated(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /triggers/{id}/runs returns paginated run history ordered newest first."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        for _ in range(5):
            _create_run(db_session, trigger)

        response = authenticated_client.get(_triggers_url(f"/{trigger.id}/runs?page=1&page_size=3"))
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 3
        assert data["has_next"] is True

    def test_get_run_detail(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """GET /triggers/{id}/runs/{run_id} returns full run with result and override data."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)
        run = _create_run(db_session, trigger, status="completed", override_data={"key": "value"})

        response = authenticated_client.get(_triggers_url(f"/{trigger.id}/runs/{run.id}"))
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == run.id
        assert data["status"] == "completed"
        assert data["override_data"] == {"key": "value"}

    @patch("app.services.trigger_service._queue_solve_task")
    def test_rerun_uses_original_override_data(
        self,
        mock_queue,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """POST /triggers/{id}/runs/{run_id}/rerun creates a new run with original overrides."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)
        original_run = _create_run(
            db_session, trigger, status="completed", override_data={"capacity": 50}
        )

        response = authenticated_client.post(
            _triggers_url(f"/{trigger.id}/runs/{original_run.id}/rerun")
        )
        assert response.status_code == 202
        new_run_id = response.json()["run_id"]
        assert new_run_id != original_run.id

        # New run should have same override_data as original
        new_run = db_session.query(TriggerRun).filter(TriggerRun.id == new_run_id).first()
        assert new_run is not None
        assert new_run.override_data == {"capacity": 50}


class TestValidateOverrides:
    def test_validate_overrides_valid(self):
        """Known fields pass validation."""
        schema = [
            {"name": "capacity", "type": "integer", "model_field_path": "capacity"},
            {"name": "timeout", "type": "number", "model_field_path": "time_limit"},
        ]
        error = validate_overrides({"capacity": 10}, schema)
        assert error is None

    def test_validate_overrides_unknown_field(self):
        """Unknown fields return an error string."""
        schema = [{"name": "capacity", "type": "integer", "model_field_path": "capacity"}]
        error = validate_overrides({"capacity": 10, "unknown": "bad"}, schema)
        assert error is not None
        assert "unknown" in error

    def test_validate_overrides_none_schema_allows_all(self):
        """None schema (open schema) allows any keys."""
        error = validate_overrides({"any_key": "any_value"}, None)
        assert error is None

    def test_validate_overrides_required_field_missing(self):
        """Missing required field returns an error string."""
        schema = [
            {
                "name": "capacity",
                "type": "integer",
                "model_field_path": "capacity",
                "required": True,
            }
        ]
        error = validate_overrides({}, schema)
        assert error is not None
        assert "capacity" in error

    def test_validate_overrides_empty_data_no_required(self):
        """Empty override_data with no required fields passes."""
        schema = [{"name": "capacity", "type": "integer", "model_field_path": "capacity"}]
        error = validate_overrides({}, schema)
        assert error is None


class TestApplyOverrides:
    def test_apply_overrides_merges_correctly(self):
        """apply_overrides places values at model_field_path correctly."""
        schema = [
            {
                "name": "capacity",
                "type": "integer",
                "model_field_path": "items.capacity",
            }
        ]
        model_json = {"items": {"capacity": 10}, "constraints": []}
        result = apply_overrides(model_json, {"capacity": 99}, schema)
        assert result["items"]["capacity"] == 99
        # Original unchanged
        assert model_json["items"]["capacity"] == 10

    def test_apply_overrides_open_schema_top_level(self):
        """Open schema (None) sets keys at the top level of model_json."""
        model_json = {"a": 1, "b": 2}
        result = apply_overrides(model_json, {"b": 99, "c": 3}, None)
        assert result["b"] == 99
        assert result["c"] == 3
        assert result["a"] == 1

    def test_apply_overrides_empty_data(self):
        """Empty override_data returns a copy of model_json unchanged."""
        model_json = {"a": 1}
        result = apply_overrides(model_json, {}, None)
        assert result == model_json
        assert result is not model_json  # deep copy

    def test_apply_overrides_nested_path_creation(self):
        """apply_overrides creates intermediate dicts for deep paths."""
        schema = [{"name": "val", "type": "integer", "model_field_path": "deep.nested.key"}]
        model_json = {}
        result = apply_overrides(model_json, {"val": 42}, schema)
        assert result["deep"]["nested"]["key"] == 42


class TestTriggerCrossOrgIsolation:
    def test_trigger_cross_org_isolation(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """Org 1's client cannot GET, update, or delete org 2's triggers."""
        # Create trigger for org 2
        doc2 = _create_doc(db_session, test_organization_2, test_user_2)
        ver2 = _create_version(db_session, doc2)
        trigger2, _ = _create_trigger(db_session, test_organization_2, test_user_2, doc2, ver2)

        # Org 1's authenticated client attempts access to org 2's trigger
        response = authenticated_client.get(_triggers_url(f"/{trigger2.id}"))
        assert response.status_code == 404

        response = authenticated_client.patch(
            _triggers_url(f"/{trigger2.id}"), json={"name": "Stolen"}
        )
        assert response.status_code == 404

        response = authenticated_client.delete(_triggers_url(f"/{trigger2.id}"))
        assert response.status_code == 404

    def test_trigger_runs_cross_org_isolation(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
        test_organization_2: Organization,
        test_user_2: User,
    ):
        """Org 1 cannot list runs for org 2's trigger."""
        doc2 = _create_doc(db_session, test_organization_2, test_user_2)
        ver2 = _create_version(db_session, doc2)
        trigger2, _ = _create_trigger(db_session, test_organization_2, test_user_2, doc2, ver2)
        _create_run(db_session, trigger2)

        response = authenticated_client.get(_triggers_url(f"/{trigger2.id}/runs"))
        assert response.status_code == 404


def _create_studio_project(db: Session, org: Organization, *, committed: bool = True):
    """A studio ModelProject and, unless told otherwise, one committed version.

    The model solves to a known optimum (11 at x=3, y=1), so a fired trigger can
    be checked on its answer and not merely on its status.
    """
    from app.models.model_project import ModelProject, ModelProjectVersion

    model_json = {
        "name": "trigger_studio_model",
        "variables": [
            {"name": "x", "type": "continuous", "lower_bound": 0},
            {"name": "y", "type": "continuous", "lower_bound": 0},
        ],
        "objective": {"sense": "maximize", "expression": "3*x + 2*y"},
        "constraints": [
            {"name": "c1", "expression": "x + y <= 4"},
            {"name": "cap_x", "expression": "x <= 3"},
        ],
    }
    project = ModelProject(
        id=generate_id("mp_"),
        organization_id=org.id,
        name="Studio model for triggers",
        status="active",
        draft_model_json=model_json,
    )
    db.add(project)
    db.flush()
    version = None
    if committed:
        version = ModelProjectVersion(
            id=generate_id("mpv_"),
            model_project_id=project.id,
            organization_id=org.id,
            sequence=1,
            commit_summary="v1",
            content_hash="hash_studio_trigger",
            model_json=model_json,
        )
        db.add(version)
        db.flush()
    db.commit()
    return project, version


class TestTriggersOnStudioModels:
    """# CONTRACT-TEST: a trigger can automate a model built in the studio.

    `document_id` was a NOT NULL foreign key to `model_builder_documents` and the
    studio never creates one, so nothing anyone built since the P1.5 fusion — when
    the studio became the one place models are built — could be automated at all.
    The trigger form listed builder documents and the empty state linked to
    /builder, an area already taken out of the menu.
    """

    def test_a_studio_project_can_be_triggered(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        project, version = _create_studio_project(db_session, test_organization)

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "Nightly re-plan",
                "model_project_id": project.id,
                "model_project_version_id": version.id,
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["source"] == "project"
        assert data["model_project_version_id"] == version.id
        assert data["document_id"] is None

        stored = db_session.query(SolveTrigger).filter(SolveTrigger.id == data["id"]).one()
        assert stored.model_project_version_id == version.id
        assert stored.trigger_source == "project"

    def test_the_worker_solves_the_pinned_project_version(
        self,
        db_session: Session,
        test_organization: Organization,
    ):
        """The run must reach the model, not just the row. Asserted on the model
        the worker resolved, which is where the builder-only lookup used to end."""
        from app.tasks.trigger_tasks import _pinned_model_json

        project, version = _create_studio_project(db_session, test_organization)
        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=test_organization.id,
            name="Resolve check",
            model_project_id=project.id,
            model_project_version_id=version.id,
            trigger_secret=_hash("s"),
            webhook_url="https://example.com/hook",
        )
        db_session.add(trigger)
        db_session.commit()

        resolved = _pinned_model_json(db_session, trigger)
        assert resolved is not None
        assert resolved["objective"]["expression"] == "3*x + 2*y"
        assert {v["name"] for v in resolved["variables"]} == {"x", "y"}

    def test_a_vanished_project_version_fails_the_run_instead_of_solving(
        self,
        db_session: Session,
        test_organization: Organization,
    ):
        """The database will not let this row exist — the foreign key is RESTRICT,
        so a pinned version cannot be deleted from under a live trigger. The
        object is therefore left unpersisted on purpose: what is pinned here is
        the worker's behaviour if it ever does happen, which must be to fail the
        run rather than solve an empty model."""
        from app.tasks.trigger_tasks import _pinned_model_json

        project, _ = _create_studio_project(db_session, test_organization, committed=False)
        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=test_organization.id,
            name="Dangling",
            model_project_id=project.id,
            model_project_version_id="mpv_does_not_exist",
            trigger_secret=_hash("s"),
            webhook_url="https://example.com/hook",
        )

        assert _pinned_model_json(db_session, trigger) is None

    def test_both_sources_at_once_is_refused(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """Ambiguity is refused rather than resolved by a precedence rule the
        caller never saw and would learn about from the solve."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        project, version = _create_studio_project(db_session, test_organization)

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "Both",
                "document_id": doc.id,
                "version_id": ver.id,
                "model_project_id": project.id,
                "model_project_version_id": version.id,
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 422

    def test_another_orgs_project_is_a_404(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization_2: Organization,
    ):
        """Multi-tenancy: the project carries the tenancy, so it is what is checked."""
        project, version = _create_studio_project(db_session, test_organization_2)

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "Not mine",
                "model_project_id": project.id,
                "model_project_version_id": version.id,
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 404
        assert db_session.query(SolveTrigger).count() == 0

    def test_a_version_from_another_project_is_a_404(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
    ):
        """Pinning our own project to someone else's version must not work either."""
        mine, _ = _create_studio_project(db_session, test_organization)
        other, other_version = _create_studio_project(db_session, test_organization)

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "Crossed",
                "model_project_id": mine.id,
                "model_project_version_id": other_version.id,
                "webhook_url": "https://example.com/hook",
            },
        )
        assert response.status_code == 404


class TestWebhookAddressIsCheckedAtTheDoor:
    """A webhook the server will never call is refused while it can still be fixed.

    Found by driving the app (QA sweep, 2026-08-20): the form took
    ``http://192.168.18.113:8080/hook`` and ``http://169.254.169.254/...``, the
    run said "completed", and ``deliver_webhook`` dropped the payload with one
    line in the server log. Nobody using the app could learn that.
    """

    def test_a_private_address_is_refused_with_a_code(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "LAN hook",
                "document_id": doc.id,
                "version_id": ver.id,
                # A literal address, so the check never depends on DNS.
                "webhook_url": "http://192.168.18.113:8080/hook",
            },
        )
        assert response.status_code == 422, response.text
        body = response.json()
        # CONTRACT-TEST: this refusal is about the ADDRESS, not about the shape of
        # the URL, and the form has to tell them apart to point at the right field.
        assert body["code"] == "trigger.webhook_url_unreachable"
        assert body["params"]["address"] == "192.168.18.113"

    def test_the_loopback_address_of_the_server_is_refused(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)

        response = authenticated_client.post(
            _triggers_url("/"),
            json={
                "name": "The API itself",
                "document_id": doc.id,
                "version_id": ver.id,
                "webhook_url": "http://127.0.0.1:8001/api/v2/admin/settings/values",
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "trigger.webhook_url_unreachable"

    def test_editing_a_trigger_cannot_move_its_webhook_to_a_private_address(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        response = authenticated_client.patch(
            _triggers_url(f"/{trigger.id}"),
            json={"webhook_url": "http://10.0.0.5/hook"},
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "trigger.webhook_url_unreachable"

        db_session.refresh(trigger)
        assert trigger.webhook_url == "https://example.com/webhook"


class TestTheListNamesTheModelAndItsSchedule:
    """# CONTRACT-TEST: the trigger list carries the model name and the schedule flag.

    The page showed `Model: mp_19e7…` and nothing else, because the response
    only carried the id. To draw the "scheduled" badge it then called
    GET /triggers/<id>/schedule once per row, and every unscheduled trigger
    answered 404 — the normal answer — which logged an error in the browser
    console. Both facts now come with the list itself.
    """

    def _schedule(self, db: Session, trigger: SolveTrigger, *, is_enabled: bool = True):
        from app.models.trigger import TriggerSchedule

        schedule = TriggerSchedule(
            id=generate_id("tsch_"),
            trigger_id=trigger.id,
            organization_id=trigger.organization_id,
            cron_expression="0 3 * * *",
            timezone="UTC",
            is_enabled=is_enabled,
        )
        db.add(schedule)
        db.commit()
        return schedule

    def test_the_list_names_a_builder_model_and_a_studio_model(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        doc = _create_doc(db_session, test_organization, test_user, name="Cutting stock")
        ver = _create_version(db_session, doc)
        _create_trigger(db_session, test_organization, test_user, doc, ver, name="From builder")
        project, version = _create_studio_project(db_session, test_organization)
        db_session.add(
            SolveTrigger(
                id=generate_id("trg_"),
                organization_id=test_organization.id,
                created_by=test_user.id,
                name="From studio",
                model_project_id=project.id,
                model_project_version_id=version.id,
                trigger_secret=_hash(secrets.token_hex(16)),
                webhook_url="https://example.com/webhook",
                is_enabled=True,
                total_runs=0,
            )
        )
        db_session.commit()

        response = authenticated_client.get(_triggers_url("/"))
        assert response.status_code == 200, response.text
        by_name = {t["name"]: t for t in response.json()}
        assert by_name["From builder"]["model_name"] == "Cutting stock"
        assert by_name["From studio"]["model_name"] == project.name

    def test_a_single_trigger_carries_the_name_too(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        doc = _create_doc(db_session, test_organization, test_user, name="Shift roster")
        ver = _create_version(db_session, doc)
        trigger, _ = _create_trigger(db_session, test_organization, test_user, doc, ver)

        response = authenticated_client.get(_triggers_url(f"/{trigger.id}"))
        assert response.status_code == 200, response.text
        assert response.json()["model_name"] == "Shift roster"

    def test_only_an_enabled_schedule_marks_a_trigger_as_scheduled(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """The badge has always meant "runs on its own", so a paused schedule
        must not light it up."""
        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)
        bare, _ = _create_trigger(db_session, test_organization, test_user, doc, ver, name="Bare")
        running, _ = _create_trigger(db_session, test_organization, test_user, doc, ver, name="On")
        paused, _ = _create_trigger(db_session, test_organization, test_user, doc, ver, name="Off")
        self._schedule(db_session, running, is_enabled=True)
        self._schedule(db_session, paused, is_enabled=False)

        response = authenticated_client.get(_triggers_url("/"))
        assert response.status_code == 200, response.text
        flags = {t["name"]: t["has_active_schedule"] for t in response.json()}
        assert flags["On"] is True
        assert flags["Off"] is False
        assert flags["Bare"] is False
        assert bare.id and paused.id  # the rows are real, not stubs

    def test_the_list_costs_the_same_number_of_queries_whatever_its_length(
        self,
        authenticated_client: TestClient,
        db_session: Session,
        test_organization: Organization,
        test_user: User,
    ):
        """This is the defect itself: the page grew one round trip per row.

        Counting SELECTs is the only way to see it — the response body looks
        identical either way.
        """
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        doc = _create_doc(db_session, test_organization, test_user)
        ver = _create_version(db_session, doc)

        def count_selects() -> int:
            seen = []

            def record(conn, cursor, statement, params, context, executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    seen.append(statement)

            # Listening on the Engine class catches whichever engine the test
            # harness swapped in, without the test having to know its name.
            event.listen(Engine, "before_cursor_execute", record)
            try:
                response = authenticated_client.get(_triggers_url("/"))
                assert response.status_code == 200, response.text
            finally:
                event.remove(Engine, "before_cursor_execute", record)
            return len(seen)

        _create_trigger(db_session, test_organization, test_user, doc, ver, name="One")
        with_one = count_selects()

        for i in range(6):
            _create_trigger(db_session, test_organization, test_user, doc, ver, name=f"More{i}")
        with_seven = count_selects()

        assert with_seven == with_one, (
            f"the list ran {with_seven} SELECTs for 7 triggers and {with_one} for 1 — "
            "it is asking per row again"
        )
