"""TriggerService — core fire logic, override validation and merging.

All functions accept a SQLAlchemy Session directly and have no FastAPI
context, following the same pattern as version_service.py.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.trigger import SolveTrigger, TriggerRun
from app.shared.utils.datetime_helpers import utcnow
from app.shared.utils.id_generator import generate_id

logger = logging.getLogger(__name__)


def validate_overrides(
    override_data: dict[str, Any] | None,
    override_schema: list[dict[str, Any]] | None,
) -> str | None:
    """Validate that override_data keys are permitted by the override_schema.

    If override_schema is None (open schema), any keys are accepted.
    If override_schema is defined, only keys listed in the schema are allowed.

    Args:
        override_data: Key-value pairs supplied by the caller.
        override_schema: List of declared field dicts with at least a 'name' key.

    Returns:
        An error string describing the violation, or None if validation passes.
    """
    if override_schema is None:
        # Open schema — any keys permitted
        return None

    declared_names = {f["name"] for f in override_schema}
    required_names = {f["name"] for f in override_schema if f.get("required")}
    # No override_data is equivalent to an empty set of supplied keys: it can
    # never have unknown keys, only missing-required ones.
    supplied_keys = set(override_data.keys()) if override_data else set()

    unknown_keys = supplied_keys - declared_names
    if unknown_keys:
        return f"Unknown override fields: {', '.join(sorted(unknown_keys))}"

    missing_required = required_names - supplied_keys
    if missing_required:
        return f"Missing required override fields: {', '.join(sorted(missing_required))}"

    return None


def _set_nested(obj: Any, path: str, value: Any) -> None:
    """Set a value at a dot-separated path within a nested dict.

    Creates intermediate dicts as needed.

    Args:
        obj: The root dict to modify.
        path: Dot-separated path (e.g. "items.capacity").
        value: The value to set.
    """
    parts = path.split(".")
    current = obj
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        if part not in current:
            current[part] = {}
        current = current[part]
    if isinstance(current, dict):
        current[parts[-1]] = value


def apply_overrides(
    model_json: dict[str, Any],
    override_data: dict[str, Any],
    override_schema: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Merge override values into model_json.

    When an override_schema is defined, each field's model_field_path
    determines where in model_json the override value is placed.

    When no schema is defined (open schema), override_data keys are
    treated as direct top-level keys in model_json.

    The original model_json dict is NOT mutated — a shallow copy is made
    before applying overrides.

    Args:
        model_json: The base model JSON dict (solver-ready format).
        override_data: Key-value overrides from the caller.
        override_schema: List of declared field dicts (may be None).

    Returns:
        A new dict with overrides applied.
    """
    import copy

    result = copy.deepcopy(model_json)

    if not override_data:
        return result

    if override_schema is not None:
        # Schema-guided: use model_field_path for each declared field
        path_map: dict[str, str] = {f["name"]: f["model_field_path"] for f in override_schema}
        for key, value in override_data.items():
            path = path_map.get(key)
            if path:
                _set_nested(result, path, value)
    else:
        # Open schema: treat keys as direct top-level model_json keys
        for key, value in override_data.items():
            result[key] = value

    return result


def create_run(
    db: Session,
    trigger: SolveTrigger,
    override_data: dict[str, Any] | None,
    status: str,
    error: str | None = None,
) -> TriggerRun:
    """Create a TriggerRun record and update trigger counters.

    Increments trigger.total_runs and updates trigger.last_fired_at.

    Flushes, and leaves the commit to the caller — the run and the counters
    belong to whatever transaction fired the trigger. This docstring used to
    claim it committed, which is how ``rerun`` shipped without one.

    Args:
        db: Database session.
        trigger: The SolveTrigger being fired.
        override_data: Override inputs from the caller (stored for /rerun).
        status: Initial run status (e.g. "pending" or "validation_failed").
        error: Optional error message to store on the run.

    Returns:
        The newly created TriggerRun.
    """
    now = utcnow()
    run = TriggerRun(
        id=generate_id("trun_"),
        trigger_id=trigger.id,
        organization_id=trigger.organization_id,
        override_data=override_data,
        status=status,
        error_message=error,
        created_at=now,
    )
    db.add(run)

    trigger.total_runs = (trigger.total_runs or 0) + 1
    trigger.last_fired_at = now

    db.flush()
    db.refresh(run)

    logger.info("Created TriggerRun %s for trigger %s (status=%s)", run.id, trigger.id, status)
    return run


def fire_trigger(
    db: Session,
    trigger: SolveTrigger,
    override_data: dict[str, Any] | None,
) -> tuple["TriggerRun", str | None]:
    """Validate overrides and either queue a solve or record a validation failure.

    If override validation fails:
    - Creates a run with status="validation_failed"
    - Queues an outbound webhook to notify the trigger owner
    - Returns (run, error_message)

    If validation passes:
    - Creates a run with status="pending"
    - Queues trigger_solve_task via Celery
    - Returns (run, None)

    Args:
        db: Database session.
        trigger: The SolveTrigger being fired.
        override_data: Override inputs from the caller.

    Returns:
        Tuple of (TriggerRun, error_message_or_None).
    """
    schema = trigger.override_schema
    error = validate_overrides(override_data, schema)  # type: ignore[arg-type]

    if error:
        # Record validation failure without queuing a solve
        run = create_run(db, trigger, override_data, "validation_failed", error=error)

        # Queue webhook to notify owner of the validation failure
        _queue_validation_failed_webhook(db, trigger, run, error)

        logger.warning("Trigger %s validation failed: %s (run=%s)", trigger.id, error, run.id)
        return run, error

    # Validation passed — create pending run and queue Celery task
    run = create_run(db, trigger, override_data, "pending")

    _queue_solve_task(db, run.id, trigger.id, override_data)

    logger.info("Trigger %s fired — queued solve for run %s", trigger.id, run.id)
    return run, None


def owner_is_active(db: Session, trigger: SolveTrigger) -> bool:
    """False when the organization, or the user who created the trigger, is off.

    Deactivating an organization or deleting a user (a soft delete) cuts off
    their sessions and API keys. The trigger secret is a credential too, and
    cron fires need none: a deactivated account kept solving on schedule and
    on every ``/fire`` until something noticed.
    """
    from app.models import Organization, User  # noqa: PLC0415

    org = db.get(Organization, trigger.organization_id)
    if org is None or not org.is_active:
        return False
    if trigger.created_by:
        creator = db.get(User, trigger.created_by)
        if creator is not None and not creator.is_active:
            return False
    return True


def pinned_model_json(db: Session, trigger: SolveTrigger) -> dict[str, Any] | None:
    """The model this trigger fires, whichever kind of model it pins.

    ``None`` means the pinned version is gone — the caller fails the run rather
    than solving something the trigger did not ask for.

    A studio project pins a committed ``ModelProjectVersion``, which always
    carries ``model_json``. A builder document pins a version snapshot, which may
    not: those predate the column, so that path keeps its two fallbacks (the
    document's own JSON, then the canvas as context).
    """
    if trigger.trigger_source == "project":
        from app.models.model_project import ModelProjectVersion  # noqa: PLC0415

        version = (
            db.query(ModelProjectVersion)
            .filter(ModelProjectVersion.id == trigger.model_project_version_id)
            .first()
        )
        if not version:
            return None
        # `or {}` would turn "this version carries no model" into an empty problem,
        # and the run would fail with "2 validation errors: variables, objective"
        # — sending the operator to debug their overrides. None is the accurate
        # answer, and the caller already reports it as a missing pinned version.
        if not version.model_json:
            return None
        return dict(version.model_json)

    from app.models.builder_document import ModelBuilderDocument  # noqa: PLC0415
    from app.models.model_version import ModelVersion  # noqa: PLC0415

    version = db.query(ModelVersion).filter(ModelVersion.id == trigger.version_id).first()
    if not version:
        return None
    if version.model_json:
        return dict(version.model_json)

    doc = (
        db.query(ModelBuilderDocument)
        .filter(ModelBuilderDocument.id == trigger.document_id)
        .first()
    )
    if doc and doc.model_json:
        return dict(doc.model_json)
    if version.canvas_json:
        # Canvas JSON is not directly solvable but preserve it as context.
        return {"canvas": version.canvas_json}
    return {}


def effective_solver(problem: Any) -> str:
    """The solver a problem runs on: its own choice, ``auto`` resolved, else the default."""
    from app.domains.solver.services.solver_service import SolverService  # noqa: PLC0415

    name, _reason, _fallback = SolverService().resolve_effective_solver(
        problem.solver_name, problem
    )
    return name


def solve_dispatch(
    db: Session,
    trigger: SolveTrigger,
    override_data: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(task kwargs, Celery options)`` for this trigger's solve.

    Every other solve goes to its solver's queue with worker time limits derived
    from its own limit. Triggered solves went to ``jaot_default``, the small
    worker that sends email and webhooks and runs the reaper, with no limit at
    all: one long triggered solve held it for hours, and a large one killed it
    for memory.

    Best effort: when the model cannot be built here, the task still runs on the
    default queue and fails the run with the exact reason, which costs nothing.
    """
    from app.domains.solver.adapters.base import SolverNotFoundError  # noqa: PLC0415
    from app.domains.solver.queue_routing import resolve_queue  # noqa: PLC0415
    from app.domains.solver.time_limits import (  # noqa: PLC0415
        compute_celery_time_limits,
        resolve_solver_time_limit,
    )
    from app.schemas.optimization import OptimizationProblem  # noqa: PLC0415
    from app.services.platform_settings_service import (  # noqa: PLC0415
        PlatformSettingsService as PSS,
    )

    base = pinned_model_json(db, trigger)
    if base is None:
        return {}, {}
    try:
        problem = OptimizationProblem.model_validate(
            apply_overrides(base, override_data or {}, trigger.override_schema)  # type: ignore[arg-type]
        )
        solver = effective_solver(problem)
        queue = resolve_queue(solver)
    except (ValueError, SolverNotFoundError):
        return {}, {}

    time_limit = problem.options.time_limit_seconds
    ceiling = PSS.get_instance_limits(db)["max_solve_time_seconds"]
    if ceiling > 0 and time_limit > ceiling:
        time_limit = float(ceiling)
    time_limit = resolve_solver_time_limit(
        solver, time_limit, PSS.get_int(db, "hexaly_default_time_limit_seconds")
    )
    soft, hard = compute_celery_time_limits(time_limit, PSS.get_int(db, "SOLVER_DEFAULT_TIMEOUT"))
    return (
        {"solver_name": solver, "time_limit_seconds": time_limit},
        {"queue": queue, "soft_time_limit": soft, "time_limit": hard},
    )


def _queue_solve_task(
    db: Session,
    run_id: str,
    trigger_id: str,
    override_data: dict[str, Any] | None,
) -> None:
    """Queue the Celery trigger_solve_task, once the run row is committed.

    ``create_run`` flushes and leaves the commit to the caller, so a job queued
    here reached a worker that owns a different connection and could not see the
    run yet. The worker answered ``run_not_found`` and stopped, and the row it
    could not find stayed ``pending`` for good — which the cron overlap check
    reads as "still running", so that schedule never fired again.

    Import is deferred to avoid circular imports (tasks import services).
    """
    from app.shared.db.after_commit import queue_after_commit  # noqa: PLC0415
    from app.tasks.trigger_tasks import trigger_solve_task  # noqa: PLC0415

    trigger = db.get(SolveTrigger, trigger_id)
    task_kwargs, celery_options = (
        solve_dispatch(db, trigger, override_data) if trigger is not None else ({}, {})
    )
    queue_after_commit(
        db,
        trigger_solve_task,
        run_id,
        trigger_id,
        override_data,
        celery_options=celery_options or None,
        **task_kwargs,
    )
    logger.debug("Queued trigger_solve_task for run %s (on commit)", run_id)


def _queue_validation_failed_webhook(
    db: Session,
    trigger: SolveTrigger,
    run: TriggerRun,
    error: str,
) -> None:
    """Queue a webhook notification for validation failures, once committed.

    ``deliver_webhook_task`` writes the attempt count onto the run, so it has
    the same problem as the solve task: a delivery that starts before the run
    exists cannot record anything against it.
    """
    from app.services.webhook_service import build_webhook_payload  # noqa: PLC0415
    from app.shared.db.after_commit import queue_after_commit  # noqa: PLC0415
    from app.tasks.webhook_tasks import deliver_webhook_task  # noqa: PLC0415

    payload = build_webhook_payload(
        event_type="trigger.execution.validation_failed",
        organization_id=trigger.organization_id,
        data={
            "run_id": run.id,
            "trigger_id": trigger.id,
            "error": error,
        },
    )
    queue_after_commit(
        db,
        deliver_webhook_task,
        str(trigger.webhook_url),
        payload,
        trigger.webhook_secret,
        run.id,
    )
    logger.debug("Queued validation_failed webhook for trigger %s run %s", trigger.id, run.id)


# SERVICE CLASS (namespace for backwards-compat imports)


class TriggerService:
    """Namespace class exposing trigger service functions as static methods.

    The actual logic lives in module-level functions; this class exists so
    callers can use either ``trigger_service.fire_trigger(...)`` or
    ``TriggerService.fire_trigger(...)``.
    """

    validate_overrides = staticmethod(validate_overrides)
    apply_overrides = staticmethod(apply_overrides)
    create_run = staticmethod(create_run)
    fire_trigger = staticmethod(fire_trigger)
