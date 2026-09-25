"""A trigger runs the model and the solver it was set up with.

# CONTRACT-TEST: a trigger fire uses its schema defaults, keeps its model, refuses an unknown
# solver at the door, and offers no second try of a refused input.

Found driving the trigger pages in a browser (QA, 2026-09-25):

- The override field ``solver`` -> ``solver_name`` had the default ``jaos``. The
  page showed "Default: jaos" and the curl snippet sent ``jaos``. A fire with an
  empty body ran on SCIP: nothing applied a default.
- A trigger fires a pinned version of a studio model, and the execution it wrote
  left ``model_project_id`` and the version empty. The executions list said the
  model was "External" and the execution page said there was no model behind it.
- An override ``solver="nosuch"`` answered 202, failed in the worker, and left an
  execution whose solver was "nosuch".
- A rerun of a run whose input was refused refused it again, and every click
  added another refused run.
- ``GET /triggers/{id}/schedule`` answered 404 for every trigger with no
  schedule, which is the normal case, and the page logged an error for it.
- The page could not run a trigger once, and could not edit one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.testclient import TestClient as PlainClient

from app.models import ModelExecution, Organization, User
from app.models.model_project import ModelProject, ModelProjectVersion
from app.models.trigger import SolveTrigger, TriggerRun
from app.services import trigger_service
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

QUEUE = "app.tasks.trigger_tasks.trigger_solve_task.apply_async"
WEBHOOK = "app.tasks.webhook_tasks.deliver_webhook_task.delay"

# Optimum 11 at x=3, y=1. No solver named, so the model's own choice is SCIP.
_LP = {
    "name": "trigger_qa_model",
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

_SOLVER_FIELD = {
    "name": "solver",
    "type": "string",
    "model_field_path": "solver_name",
    "default": "highs",
    "required": False,
}


def _project_trigger(
    db: Session,
    org: Organization,
    user: User,
    *,
    override_schema: list | None = None,
    is_enabled: bool = True,
    solver_name: str | None = None,
) -> tuple[SolveTrigger, str, ModelProject, ModelProjectVersion]:
    """A studio model, one committed version, and a trigger pinned to it."""
    project = ModelProject(
        id=generate_id("mp_"),
        organization_id=org.id,
        name="Diet for the QA trigger",
        status="active",
        draft_model_json=_LP,
    )
    db.add(project)
    db.flush()
    version = ModelProjectVersion(
        id=generate_id("mpv_"),
        model_project_id=project.id,
        organization_id=org.id,
        sequence=1,
        commit_summary="v1",
        content_hash=generate_id("hash_"),
        model_json=_LP,
    )
    db.add(version)
    db.flush()
    secret = secrets.token_hex(16)
    now = utcnow()
    trigger = SolveTrigger(
        id=generate_id("trg_"),
        organization_id=org.id,
        created_by=user.id,
        name="QA nightly diet",
        model_project_id=project.id,
        model_project_version_id=version.id,
        trigger_secret=hashlib.sha256(secret.encode()).hexdigest(),
        override_schema=override_schema,
        webhook_url="https://example.com/hook",
        is_enabled=is_enabled,
        total_runs=0,
        created_at=now,
        updated_at=now,
    )
    if solver_name is not None:
        trigger.solver_name = solver_name
    db.add(trigger)
    db.commit()
    return trigger, secret, project, version


def _fire(client: TestClient, trigger: SolveTrigger, secret: str, body: dict):
    """Fire with the trigger secret only, the way an outside caller does."""
    return PlainClient(client.app).post(
        f"/api/v2/triggers/{trigger.id}/fire",
        json=body,
        headers={"Authorization": f"Bearer {secret}"},
    )


def _run_task(db: Session, trigger: SolveTrigger, run: TriggerRun, **kwargs):
    from app.tasks.trigger_tasks import trigger_solve_task

    with (
        patch("app.tasks.trigger_tasks.SessionLocal", return_value=db),
        patch("app.tasks.trigger_tasks._deliver_webhook"),
    ):
        return trigger_solve_task(
            run_id=run.id, trigger_id=trigger.id, override_data=run.override_data, **kwargs
        )


def _runs(db: Session, trigger: SolveTrigger) -> list[TriggerRun]:
    db.expire_all()
    return db.query(TriggerRun).filter(TriggerRun.trigger_id == trigger.id).all()


class TestTheSchemaDefaultIsApplied:
    def test_a_fire_without_the_field_runs_on_its_default(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        with patch(QUEUE) as queued:
            response = _fire(authenticated_client, trigger, secret, {})

        assert response.status_code == 202, response.text
        assert queued.call_count == 1
        assert queued.call_args.kwargs["kwargs"]["solver_name"] == "highs"
        assert queued.call_args.kwargs["queue"] == "solve_highs"

    def test_a_value_the_caller_sends_beats_the_default(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        with patch(QUEUE) as queued:
            response = _fire(
                authenticated_client, trigger, secret, {"override_data": {"solver": "scip"}}
            )

        assert response.status_code == 202, response.text
        assert queued.call_args.kwargs["kwargs"]["solver_name"] == "scip"

    def test_the_worker_applies_the_default_too(self, db_session, test_organization, test_user):
        """A message queued without a solver name resolves it in the worker."""
        trigger, _, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        run = trigger_service.create_run(db_session, trigger, None, "pending")
        db_session.commit()

        result = _run_task(db_session, trigger, run)

        assert result["status"] == "completed", result
        execution = db_session.get(ModelExecution, result["execution_id"])
        assert execution.solver_name == "highs"
        assert execution.objective_value == 11

    def test_apply_overrides_fills_a_default_at_its_path(self):
        schema = [
            {"name": "cap", "type": "number", "model_field_path": "limits.cap", "default": 7},
            {"name": "unset", "type": "number", "model_field_path": "limits.unset"},
        ]
        merged = trigger_service.apply_overrides({"limits": {}}, {}, schema)
        assert merged["limits"] == {"cap": 7}


class TestATriggerRunKeepsItsModel:
    def test_the_execution_names_the_pinned_project_and_version(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, _, project, version = _project_trigger(db_session, test_organization, test_user)
        run = trigger_service.create_run(db_session, trigger, None, "pending")
        db_session.commit()

        result = _run_task(db_session, trigger, run)

        execution = db_session.get(ModelExecution, result["execution_id"])
        assert execution.model_project_id == project.id
        assert execution.model_project_version_id == version.id
        # The trigger stays the source the page links back to.
        assert execution.origin == "triggered"
        assert execution.trigger_id == trigger.id

        shown = authenticated_client.get(f"/api/v2/models/executions/{execution.id}")
        assert shown.status_code == 200, shown.text
        assert shown.json()["model_name"] == project.name


class TestAnUnknownSolverIsRefusedAtTheDoor:
    def test_an_override_naming_no_solver_is_a_coded_422(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        with patch(QUEUE) as queued, patch(WEBHOOK):
            response = _fire(
                authenticated_client, trigger, secret, {"override_data": {"solver": "nosuch"}}
            )

        assert response.status_code == 422, response.text
        body = response.json()
        assert body["code"] == "trigger.solver_unavailable"
        assert body["params"] == {"solver": "nosuch"}
        assert queued.call_count == 0, "a solve was queued for a solver that does not exist"

        run = db_session.get(TriggerRun, body["detail"]["run_id"])
        assert run.status == "validation_failed"
        assert "nosuch" in run.error_message
        assert db_session.query(ModelExecution).filter_by(solver_name="nosuch").count() == 0

    def test_an_open_schema_is_checked_the_same_way(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(db_session, test_organization, test_user)
        with patch(QUEUE) as queued, patch(WEBHOOK):
            response = _fire(
                authenticated_client,
                trigger,
                secret,
                {"override_data": {"solver_name": "nosuch"}},
            )

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "trigger.solver_unavailable"
        assert queued.call_count == 0

    def test_auto_is_a_solver_choice_and_is_accepted(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        with patch(QUEUE) as queued:
            response = _fire(
                authenticated_client, trigger, secret, {"override_data": {"solver": "auto"}}
            )

        assert response.status_code == 202, response.text
        assert queued.call_count == 1

    def test_the_other_refusals_carry_a_code_too(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        with patch(QUEUE), patch(WEBHOOK):
            response = _fire(authenticated_client, trigger, secret, {"override_data": {"foo": 1}})

        assert response.status_code == 422, response.text
        body = response.json()
        assert body["code"] == "trigger.override_unknown_fields"
        assert body["params"] == {"fields": "foo"}
        # The body API clients already read keeps its shape.
        assert body["detail"]["error"] == "Unknown override fields: foo"


class TestARefusedInputIsNotRerun:
    def test_a_rerun_of_a_refused_run_refuses_without_a_new_run(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, _, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        refused = trigger_service.create_run(
            db_session, trigger, {"foo": 1}, "validation_failed", error="Unknown override fields"
        )
        db_session.commit()
        before = len(_runs(db_session, trigger))

        with patch(QUEUE) as queued, patch(WEBHOOK):
            response = authenticated_client.post(
                f"/api/v2/triggers/{trigger.id}/runs/{refused.id}/rerun"
            )

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "trigger.override_unknown_fields"
        assert queued.call_count == 0
        assert len(_runs(db_session, trigger)) == before, "each click added a refused run"

    def test_a_rerun_of_a_good_run_still_runs(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, _, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        done = trigger_service.create_run(db_session, trigger, {"solver": "scip"}, "completed")
        db_session.commit()

        with patch(QUEUE) as queued:
            response = authenticated_client.post(
                f"/api/v2/triggers/{trigger.id}/runs/{done.id}/rerun"
            )

        assert response.status_code == 202, response.text
        assert queued.call_count == 1


class TestNoScheduleIsNotAnError:
    def test_a_trigger_with_no_schedule_answers_200_and_null(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, _, _, _ = _project_trigger(db_session, test_organization, test_user)

        response = authenticated_client.get(f"/api/v2/triggers/{trigger.id}/schedule")

        assert response.status_code == 200, response.text
        assert response.json() is None

    def test_an_unknown_trigger_is_still_a_404(self, authenticated_client):
        response = authenticated_client.get("/api/v2/triggers/trg_nothere/schedule")
        assert response.status_code == 404


class TestRunNow:
    def test_run_now_fires_with_the_defaults_and_marks_the_source(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, _, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )
        with patch(QUEUE) as queued:
            response = authenticated_client.post(f"/api/v2/triggers/{trigger.id}/run")

        assert response.status_code == 202, response.text
        run = db_session.get(TriggerRun, response.json()["run_id"])
        assert run.source == "app"
        assert run.status == "pending"
        assert queued.call_count == 1, "Run now answered 202 without queuing the solve"
        assert queued.call_args.kwargs["kwargs"]["solver_name"] == "highs"

    def test_run_now_needs_a_signed_in_caller_not_the_secret(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(db_session, test_organization, test_user)
        anonymous = PlainClient(authenticated_client.app)

        assert anonymous.post(f"/api/v2/triggers/{trigger.id}/run").status_code == 401
        # The trigger secret is not a session: it opens /fire and nothing else.
        with_secret = anonymous.post(
            f"/api/v2/triggers/{trigger.id}/run",
            headers={"Authorization": f"Bearer {secret}"},
        )
        assert with_secret.status_code == 401
        assert _runs(db_session, trigger) == []

    def test_run_now_on_a_disabled_trigger_is_a_409(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, _, _, _ = _project_trigger(
            db_session, test_organization, test_user, is_enabled=False
        )
        with patch(QUEUE) as queued:
            response = authenticated_client.post(f"/api/v2/triggers/{trigger.id}/run")

        assert response.status_code == 409
        assert queued.call_count == 0

    def test_run_now_refuses_what_fire_would_refuse_and_records_nothing(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        required = {**_SOLVER_FIELD, "default": None, "required": True}
        trigger, _, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[required]
        )
        with patch(QUEUE) as queued, patch(WEBHOOK):
            response = authenticated_client.post(f"/api/v2/triggers/{trigger.id}/run")

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "trigger.override_missing_required"
        assert response.json()["params"] == {"fields": "solver"}
        assert queued.call_count == 0
        assert _runs(db_session, trigger) == []

    def test_another_organization_cannot_run_it(
        self, authenticated_client, db_session, test_organization_2, test_user_2
    ):
        trigger, _, _, _ = _project_trigger(db_session, test_organization_2, test_user_2)

        with patch(QUEUE) as queued:
            response = authenticated_client.post(f"/api/v2/triggers/{trigger.id}/run")

        assert response.status_code == 404
        assert queued.call_count == 0


class TestTheTriggerSolver:
    def test_editing_the_solver_changes_where_the_next_fire_runs(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(db_session, test_organization, test_user)

        edited = authenticated_client.patch(
            f"/api/v2/triggers/{trigger.id}", json={"solver_name": "highs"}
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["solver_name"] == "highs"

        with patch(QUEUE) as queued:
            response = _fire(authenticated_client, trigger, secret, {})
        assert response.status_code == 202, response.text
        assert queued.call_args.kwargs["kwargs"]["solver_name"] == "highs"

    def test_an_override_still_beats_the_trigger_solver(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(
            db_session,
            test_organization,
            test_user,
            override_schema=[{**_SOLVER_FIELD, "default": None}],
            solver_name="highs",
        )
        with patch(QUEUE) as queued:
            response = _fire(
                authenticated_client, trigger, secret, {"override_data": {"solver": "scip"}}
            )
        assert response.status_code == 202, response.text
        assert queued.call_args.kwargs["kwargs"]["solver_name"] == "scip"

    def test_an_unknown_solver_is_refused_on_edit(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, _, _, _ = _project_trigger(db_session, test_organization, test_user)

        response = authenticated_client.patch(
            f"/api/v2/triggers/{trigger.id}", json={"solver_name": "nosuch"}
        )

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "trigger.solver_unavailable"
        db_session.refresh(trigger)
        assert trigger.solver_name is None

    def test_null_goes_back_to_the_models_own_solver(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, _, _, _ = _project_trigger(
            db_session, test_organization, test_user, solver_name="highs"
        )

        response = authenticated_client.patch(
            f"/api/v2/triggers/{trigger.id}", json={"solver_name": None}
        )

        assert response.status_code == 200, response.text
        assert response.json()["solver_name"] is None

    def test_an_edit_can_change_a_default(
        self, authenticated_client, db_session, test_organization, test_user
    ):
        trigger, secret, _, _ = _project_trigger(
            db_session, test_organization, test_user, override_schema=[_SOLVER_FIELD]
        )

        response = authenticated_client.patch(
            f"/api/v2/triggers/{trigger.id}",
            json={"name": "Renamed", "override_schema": [{**_SOLVER_FIELD, "default": "scip"}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Renamed"

        with patch(QUEUE) as queued:
            _fire(authenticated_client, trigger, secret, {})
        assert queued.call_args.kwargs["kwargs"]["solver_name"] == "scip"


def test_a_required_field_with_a_default_is_satisfied_by_it():
    """Run now sends nothing, so a required field has to take its default."""
    schema = [{**_SOLVER_FIELD, "required": True}]
    assert trigger_service.validate_overrides({}, schema) is None
    no_default = [{**_SOLVER_FIELD, "required": True, "default": None}]
    assert trigger_service.validate_overrides({}, no_default) is not None


def test_every_refusal_code_has_words_in_english():
    messages = Path(__file__).resolve().parent.parent / "frontend" / "messages" / "en.json"
    codes = json.loads(messages.read_text(encoding="utf-8"))["errors"]["codes"]
    missing = []
    for code in trigger_service.REFUSAL_CODES:
        node = codes
        for part in code.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if not isinstance(node, str) or not node.strip():
            missing.append(code)
    assert missing == [], f"trigger refusal codes with no errors.codes entry: {missing}"
