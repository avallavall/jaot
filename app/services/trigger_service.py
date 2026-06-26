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
    Commits the new run and the updated trigger in a single transaction.

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
        _queue_validation_failed_webhook(trigger, run, error)

        logger.warning("Trigger %s validation failed: %s (run=%s)", trigger.id, error, run.id)
        return run, error

    # Validation passed — create pending run and queue Celery task
    run = create_run(db, trigger, override_data, "pending")

    _queue_solve_task(run.id, trigger.id, override_data)

    logger.info("Trigger %s fired — queued solve for run %s", trigger.id, run.id)
    return run, None


def _queue_solve_task(
    run_id: str,
    trigger_id: str,
    override_data: dict[str, Any] | None,
) -> None:
    """Queue the Celery trigger_solve_task.

    Import is deferred to avoid circular imports (tasks import services).
    """
    try:
        from app.tasks.trigger_tasks import trigger_solve_task  # noqa: PLC0415

        trigger_solve_task.delay(run_id, trigger_id, override_data)
        logger.debug("Queued trigger_solve_task for run %s", run_id)
    except Exception as exc:
        # Celery may not be running in test environments; log and continue
        logger.warning("Failed to queue trigger_solve_task for run %s: %s", run_id, exc)


def _queue_validation_failed_webhook(
    trigger: SolveTrigger,
    run: TriggerRun,
    error: str,
) -> None:
    """Queue a webhook notification for validation failures."""
    try:
        from app.services.webhook_service import build_webhook_payload  # noqa: PLC0415
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
        deliver_webhook_task.delay(
            str(trigger.webhook_url),
            payload,
            trigger.webhook_secret,
        )
        logger.debug("Queued validation_failed webhook for trigger %s run %s", trigger.id, run.id)
    except Exception as exc:
        logger.warning("Failed to queue validation_failed webhook for run %s: %s", run.id, exc)


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
