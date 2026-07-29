"""The solve pipeline: enqueue, wait, shape — shared by every endpoint that solves.

These three steps were private functions inside ``solve.py``, and the solver
domain's own routes were importing them by their underscore names across a layer
(D-16). They are not endpoint code: they are the path ADR-007 requires every
solve to ride, whoever asks for it — the universal endpoint, a project solve, a
template run, a file import.

Here they have names of their own, which is what makes the domain's use of them
a declared API instead of reaching into another module's privates.

They stay in the API layer rather than moving into ``app/domains/solver/``
because they raise ``HTTPException`` (tier caps, capacity, queue failures): the
domain would have to take a FastAPI dependency to host them, and translating
those into domain errors is a bigger change than this one.
"""

from __future__ import annotations

import logging
import threading
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.v2.solver_errors import solver_unavailable
from app.domains.solver import execution_writer
from app.domains.solver.adapters.base import (
    DEFAULT_SOLVER_NAME,
    SolverNotFoundError,
)
from app.domains.solver.queue_routing import resolve_queue
from app.domains.solver.services.availability_gate import ensure_hexaly_worker_or_503
from app.domains.solver.time_limits import (
    compute_celery_time_limits,
    resolve_solver_time_limit,
)
from app.models import ModelExecution, ModelProject, Organization
from app.models.audit_log import AuditAction
from app.schemas.optimization import (
    MultiObjectiveConfig,
    OptimizationProblem,
    OptimizationResult,
    SolverStatus,
)
from app.schemas.solution_structure import annotate_variable_structure
from app.schemas.tier import tier_cap_detail
from app.services.audit_service import log_action
from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.services.solve_orchestrator import (
    ExecutionSource,
    validate_problem,
)
from app.shared.core.prometheus_metrics import SOLVER_AUTO_ROUTE_DECISIONS
from app.shared.core.rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)

# Backpressure for the sync facade (restores the old orchestrator's 429): each
# sync solve parks a threadpool thread in ``task.get`` for up to
# ASYNC_WAIT_TIMEOUT_SECONDS. Without a cap, sustained concurrent sync load
# exhausts Starlette's request threadpool and takes the WHOLE API down instead
# of shedding solve load early. The cap bounds concurrent WAITERS in this
# process — the queue itself keeps accepting async work.
_SYNC_WAIT_CAP = 24


def _clamp_time_limit_to_plan(
    problem: OptimizationProblem,
    plan_max_seconds: float,
) -> OptimizationProblem:
    """Return a new OptimizationProblem with options.time_limit_seconds clamped.

    A ``plan_max_seconds`` of 0 means no ceiling — the operator has opted out and the
    request's own ``time_limit_seconds`` stands.

    If the input already satisfies the limit, returns the input unchanged.
    Otherwise returns a new instance via nested `model_copy(update=...)` —
    the original `problem` and `problem.options` are guaranteed untouched
    per the project immutability rule.
    """
    if plan_max_seconds <= 0 or problem.options.time_limit_seconds <= plan_max_seconds:
        return problem
    return problem.model_copy(
        update={
            "options": problem.options.model_copy(update={"time_limit_seconds": plan_max_seconds})
        }
    )


#: ADR-007 §4: server-side wait budget for `POST /solve/async?wait=true`. Kept below
#: the frontend proxy's 120s timeout so a long solve degrades to a clean
#: 202 + task_id instead of an opaque proxy 500.
ASYNC_WAIT_TIMEOUT_SECONDS = 100


_sync_wait_slots = threading.BoundedSemaphore(_SYNC_WAIT_CAP)


_NEAR_ZERO = 1e-9


class EnqueuedSolve:
    """Handle for a solve queued through the ONE async pipeline (ADR-007)."""

    __slots__ = (
        "task",
        "execution_id",
        "effective_solver",
        "auto_route_reason",
        "fallback_triggered",
        "envelope",
    )

    def __init__(
        self,
        *,
        task: Any,
        execution_id: str,
        effective_solver: str,
        auto_route_reason: str | None,
        fallback_triggered: bool,
        envelope: dict[str, Any],
    ) -> None:
        self.task = task
        self.execution_id = execution_id
        self.effective_solver = effective_solver
        self.auto_route_reason = auto_route_reason
        self.fallback_triggered = fallback_triggered
        self.envelope = envelope


def _enforce_tier_caps(
    db: Session,
    org: Organization,
    problem: OptimizationProblem,
) -> OptimizationProblem:
    """Check instance caps and reject if exceeded. Return problem with time_limit clamped."""
    limits = PSS.get_instance_limits(db)

    # 0 = unlimited. Nothing to upgrade to on a free, self-hosted platform, so the
    # message tells the operator which knob to turn instead of selling them a tier.
    max_vars = limits["max_variables"]
    num_vars = len(problem.variables)
    if max_vars > 0 and num_vars > max_vars:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=tier_cap_detail(
                error="variable_limit_exceeded",
                message=(
                    f"This model has {num_vars:,} variables and this instance is "
                    f"configured to allow up to {max_vars:,}. An administrator can "
                    f"raise or remove the limit in Settings (instance_max_variables; "
                    f"0 means unlimited)."
                ),
                current_plan=org.plan,
                limit=max_vars,
                current_value=num_vars,
                setting_key="instance_max_variables",
            ),
        )

    problem = _clamp_time_limit_to_plan(problem, limits["max_solve_time_seconds"])

    allowed, _rate_info = check_rate_limit(
        f"solve_daily:{org.id}",
        limits["max_daily_solves"],
        limits["max_daily_solves"],
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=tier_cap_detail(
                error="daily_solve_quota_exceeded",
                message=(
                    f"You've reached this instance's daily limit of "
                    f"{limits['max_daily_solves']:,} solves, which resets daily. "
                    f"An administrator can raise or remove it in Settings "
                    f"(instance_max_daily_solves; 0 means unlimited)."
                ),
                current_plan=org.plan,
                limit=limits["max_daily_solves"],
                setting_key="instance_max_daily_solves",
            ),
        )

    return problem


def _log_solve_analytics(
    db: Session, org: Organization, user: Any, problem: OptimizationProblem
) -> None:
    """Fire-and-forget SOLVER_SOLVE analytics for every async solve.

    ADR-007 S6: restores the signal the deleted sync orchestrator used to emit, now
    uniform across ALL solve entry points (they all funnel through the two enqueue
    helpers). No request context at the enqueue layer, so ``ip_address`` is None —
    geo is the only thing lost versus the old sync emission.
    """
    try:
        from app.services.analytics_service import AnalyticsService  # noqa: PLC0415
        from app.shared.constants import event_types as evt  # noqa: PLC0415

        AnalyticsService(db).log_event(
            user_id=getattr(user, "id", "anonymous"),
            org_id=org.id,
            event_type=evt.SOLVER_SOLVE,
            ip_address=None,
            metadata={
                "num_variables": len(problem.variables),
                "num_constraints": len(problem.constraints),
            },
        )
    except Exception:
        logger.debug("Failed to log SOLVER_SOLVE analytics event", exc_info=True)


def _mark_enqueue_failed(db: Session, execution: ModelExecution, error: str) -> None:
    """Mark an already-committed pending row FAILED after a broker enqueue error.

    P1.5 F0 (insert-before-enqueue): the pending row is committed before
    ``apply_async``, so a broker failure would otherwise leave a 'pending' zombie
    until the reaper. Marking it failed here keeps history truthful immediately.
    """
    try:
        if execution_writer.apply_failed(execution, error=error):
            db.commit()
    except Exception:
        logger.warning("Failed to mark enqueue-failed row %s", execution.id, exc_info=True)
        db.rollback()


def enqueue_async_solve(
    *,
    db: Session,
    org: Organization,
    user: Any,
    problem: OptimizationProblem,
    workspace_id: str | None,
    solver_name_param: str | None,
    origin: str | None,
    source_kind: str | None,
    source_id: str | None,
    dataset_id: str | None,
    model_project_version_id: str | None = None,
    execution_id_override: str | None = None,
    parser: Any = None,
) -> EnqueuedSolve:
    """The ONE enqueue path every solve rides (ADR-007): tier caps, provenance,
    auto-routing, queue routing, Celery time limits, the
    pending ``ModelExecution`` row, and the task envelope.

    ``execution_id_override`` binds the row to an idempotency-derived id so a
    retry with the same ``Idempotency-Key`` finds it (the wrapped ``POST /solve``).
    """
    from app.domains.solver.tasks.solve_tasks import solve_async
    from app.shared.utils.id_generator import generate_id

    problem = _enforce_tier_caps(db, org, problem)
    # Recover flat/imported variable index structure (a JModel-compiled problem
    # already carries it; this is a no-op there). Do it before enqueue so the
    # structure travels with the problem to the worker and lands on the result.
    annotate_variable_structure(problem)

    ws_id = workspace_id
    execution_id = execution_id_override or generate_id("exe_")

    # Provenance is sanitized up front: it scopes the dataset lookup below, and
    # the execution INSERT at the end reuses these values.
    async_source = ExecutionSource.from_request(origin, source_kind, source_id)
    # Only mirror the id onto the TYPED project column when it names a real project in
    # this org — source_id is client-supplied, and the typed column feeds joins/reconcile
    # (§14) + P1.5, which must never carry a cross-org or dangling id. The generic
    # source_kind/source_id provenance stays as sanitized above.
    typed_model_project_id: str | None = None
    if async_source.source_kind == "model_project" and async_source.source_id:
        owns_project = (
            db.query(ModelProject.id)
            .filter(
                ModelProject.id == async_source.source_id,
                ModelProject.organization_id == org.id,
            )
            .first()
        )
        if owns_project:
            typed_model_project_id = async_source.source_id

    # §8 Scenarios / S1: dataset provenance. Resolved BEFORE the task is enqueued
    # so an unknown/foreign dataset 404s up front. Org-scoped (and pinned to the
    # project when the solve names one) — a client-supplied id must never resolve
    # across orgs.
    dataset_name: str | None = None
    if dataset_id is not None:
        # Inline org-scoped lookup mirroring model_project_service.get_dataset_or_404 —
        # importing that service here would let the solver-domain routes that import
        # this module reach app.domains.dsl transitively, breaching the
        # domains-independent import contract.
        from app.models.model_project import ModelProjectDataset  # noqa: PLC0415

        ds_query = db.query(ModelProjectDataset).filter(
            ModelProjectDataset.id == dataset_id,
            ModelProjectDataset.organization_id == org.id,
        )
        if typed_model_project_id is not None:
            ds_query = ds_query.filter(
                ModelProjectDataset.model_project_id == typed_model_project_id
            )
        dataset = ds_query.first()
        if dataset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
        dataset_name = dataset.name

    # Resolve "auto" to a concrete solver BEFORE enqueuing.
    # D-11 / D-13: uses worker-health probe instead
    # of BYOL license-state DB query.
    requested_async_solver = problem.solver_name or solver_name_param
    async_auto_reason: str | None = None
    async_fallback_triggered: bool = False
    if requested_async_solver == "auto":
        from app.domains.solver.services.auto_router import select_solver  # noqa: PLC0415
        from app.domains.solver.services.solver_service import (  # noqa: PLC0415
            get_solver_service as _get_svc,
        )

        async_effective, async_auto_reason, async_fallback_triggered = select_solver(
            problem, parser if parser is not None else _get_svc().parser
        )
        # D-13: structured log + counter on async path.
        logger.info(
            "auto_route_decision",
            extra={
                "solver_used": async_effective,
                "auto_route_reason": async_auto_reason,
                "execution_id": execution_id,
                "organization_id": org.id,
                "fallback_triggered": async_fallback_triggered,
            },
        )
        SOLVER_AUTO_ROUTE_DECISIONS.labels(
            solver_used=async_effective, reason=async_auto_reason
        ).inc()
    else:
        async_effective = requested_async_solver

    effective_async_solver = async_effective or DEFAULT_SOLVER_NAME

    # D-11 / WR-04: direct hexaly + worker down → 503 up front.
    # The auto-router resolved "auto" → effective_async_solver above; if the router
    # chose hexaly_unavailable_fallback (SCIP) the gate must NOT fire — only direct
    # hexaly selection should 503.
    if not async_fallback_triggered:
        ensure_hexaly_worker_or_503(effective_async_solver)

    # Validate BEFORE enqueuing: a parseable-but-semantically-invalid problem
    # (undefined var refs, inverted bounds) raises HTTP 400 here — never reaches
    # the worker.
    validate_problem(problem)

    # Stamp the effective time limit before the dump, so whatever the worker
    # receives is what it runs with. Only Hexaly is affected: it has no natural
    # stopping point, so a request that names no limit gets the configured one.
    problem.options.time_limit_seconds = resolve_solver_time_limit(
        db, effective_async_solver, problem.options.time_limit_seconds
    )

    problem_data = problem.model_dump(mode="json")
    # Phase 7.4: use the post-auto-routing effective solver (computed above).
    # Thread the auto-route reason + fallback flag through to the worker for
    # result-dict construction (D-13 async parity).
    effective_solver_name = async_effective
    if async_auto_reason is not None:
        problem_data["_auto_route_reason"] = async_auto_reason
    if async_fallback_triggered:
        problem_data["_fallback_triggered"] = True

    # An unknown solver name rejects the submission before anything is queued.
    try:
        target_queue = resolve_queue(effective_solver_name)
    except SolverNotFoundError as exc:
        raise solver_unavailable(exc, effective_solver_name) from exc

    # W15/F-01: worker-level kill switch. Solver-internal limits stop
    # well-behaved solves; a C-level hang survives them. Derive Celery
    # soft/hard time limits from the request's own solver time limit so a
    # hung worker child is killed, the refund fires, and the slot frees up.
    soft_limit, hard_limit = compute_celery_time_limits(db, problem.options.time_limit_seconds)

    # P1.5 F0 (ADR-007 debt) — insert the pending row BEFORE enqueuing so a
    # broker-accepted task can never briefly exist with no history row: the reaper
    # reconciles a crashed worker BY its row, and the idempotent-retry attach path
    # (S2) needs the row present from enqueue time. ``solve_async`` keys its terminal
    # write off ``celery_task_id``, so the id is generated here and passed to
    # ``apply_async(task_id=...)`` — the row and the task share it from birth (the
    # execute_model insert-first pattern keys off execution_id instead, so it never
    # needed this).
    celery_task_id = str(uuid4())

    # Minimal execution record so /async/{task_id} can verify ownership (prevents IDOR).
    # Provenance (async_source / typed_model_project_id / dataset) was resolved and
    # validated up front. ADR-007 S3: the ONE writer owns
    # the row so the insert shape stays identical across every enqueue site.
    execution = execution_writer.insert_pending(
        db,
        execution_id=execution_id,
        organization_id=org.id,
        celery_task_id=celery_task_id,
        input_data=problem_data,
        solver_name=effective_solver_name or DEFAULT_SOLVER_NAME,
        executed_by_user_id=user.id if user else None,
        # D-13: persist auto-routing slug at enqueue time (Plan 09 migration column).
        auto_route_reason=async_auto_reason,
        origin=async_source.origin,
        source_kind=async_source.source_kind,
        source_id=async_source.source_id,
        # Typed per-project column for fast per-project history + the §14 durable
        # reconcile + P1.5 — populated only when validated as an in-org project above.
        model_project_id=typed_model_project_id,
        # Version provenance rides ONLY alongside a validated in-org project id so a
        # client can never stamp a dangling version id (S4a: project-solve passes it).
        model_project_version_id=(
            model_project_version_id if typed_model_project_id is not None else None
        ),
        # §8/S1: dataset provenance — name is a snapshot so history survives
        # dataset deletion. Both None unless the id resolved in-org above.
        dataset_id=dataset_id,
        dataset_name=dataset_name,
    )
    # Audit who ran which solve — rides the pending row's transaction. The old
    # in-request orchestrator emitted this; the async rewrite dropped it and every
    # solve vanished from the org audit log.
    log_action(
        db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.SOLVE,
        workspace_id=ws_id,
        target_type="execution",
        target_id=execution_id,
        target_name=problem.name,
        metadata={"solver": effective_solver_name or DEFAULT_SOLVER_NAME},
    )
    pending_committed = False
    try:
        db.commit()
        pending_committed = True
    except Exception:
        # Best-effort (mirrors the historic behavior): a duplicate id from a racing
        # idempotent retry, or a transient DB error, must not fail an otherwise-valid
        # solve — the racer's row (or the reaper) still tracks it and the caller still
        # gets the result from the task itself.
        logger.warning(
            "Failed to commit pending ModelExecution %s before enqueue",
            execution_id,
            exc_info=True,
        )
        db.rollback()

    # WR-07: if the broker is unreachable, apply_async raises and the client
    # sees a clean 503 with nothing queued (bar the pending row, marked failed below).
    try:
        task = solve_async.apply_async(
            kwargs={
                "problem_data": problem_data,
                "organization_id": org.id,
                "user_id": user.id if user else None,
                "workspace_id": ws_id,
                "warm_start_execution_id": (
                    problem.warm_start.execution_id if problem.warm_start else None
                ),
                "solver_name": effective_solver_name,
            },
            task_id=celery_task_id,
            queue=target_queue,
            soft_time_limit=soft_limit,
            time_limit=hard_limit,
        )
    except Exception as exc:
        logger.error("apply_async failed for solve %s: %s", execution_id, exc)
        if pending_committed:
            _mark_enqueue_failed(db, execution, f"Failed to enqueue task: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enqueue_failed",
                "message": "Failed to enqueue solve task. Please retry shortly.",
            },
        ) from exc

    _log_solve_analytics(db, org, user, problem)

    task_envelope = {
        # P1.5 F0: report the id we pre-generated and submitted (celery honors
        # task_id=), so the envelope, the pending row's celery_task_id, and the id
        # the worker runs under are the SAME by construction.
        "task_id": celery_task_id,
        # ADR-007 §6: the ModelExecution row id is first-class in the async contract
        # (additive) — task_id keys Celery/WS, execution_id keys history.
        "execution_id": execution_id,
        "status": "pending",
        "message": "Task queued for processing",
        "ws_url": f"/api/v2/ws/executions/{celery_task_id}",
        "poll_url": f"/api/v2/solve/async/{celery_task_id}",
    }
    return EnqueuedSolve(
        task=task,
        execution_id=execution_id,
        effective_solver=effective_async_solver,
        auto_route_reason=async_auto_reason,
        fallback_triggered=async_fallback_triggered,
        envelope=task_envelope,
    )


def wait_for_task(task: Any) -> dict[str, Any] | BaseException | None:
    """Bounded blocking wait on a queued solve; ``None`` means the budget ran out.

    Runs in the threadpool — every caller is a sync ``def`` handler on purpose;
    a blocking ``get`` must never sit on the event loop. With ``propagate=False``
    a hard task failure comes back as the exception OBJECT, never raises.

    Raises:
        HTTPException 429: all sync-wait slots are busy — the task IS queued;
            the caller should poll it via the async endpoint instead.
    """
    from celery.exceptions import TimeoutError as CeleryTimeoutError  # noqa: PLC0415

    if not _sync_wait_slots.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail=(
                "Server is at capacity for synchronous solves. Your task was queued — "
                f"poll GET /api/v2/solve/async/{task.id} for the result, or use "
                "POST /api/v2/solve/async directly."
            ),
        )
    try:
        return task.get(timeout=ASYNC_WAIT_TIMEOUT_SECONDS, propagate=False)
    except CeleryTimeoutError:
        return None
    finally:
        _sync_wait_slots.release()


def shape_sync_result(
    payload: dict[str, Any] | BaseException,
    *,
    db: Session,
    org_id: str,
    execution_id: str,
    solver_used: str,
    auto_route_reason: str | None,
    fallback_triggered: bool,
) -> dict[str, Any]:
    """Map the worker envelope to the SYNC ``OptimizationResult`` contract.

    ADR-007 §4: the caller ran the exact enqueue path (provenance, pending row);
    this helper only reshapes. The worker's ``OptimizationResult`` carries a
    schema default for ``execution_id`` (the sync orchestrator used to inject
    it), so it is injected here.
    """
    if isinstance(payload, BaseException):
        # Task hard-killed or crashed before its own error handling: the reaper
        # reconciles the row; report the sync error shape.
        result = OptimizationResult(
            status=SolverStatus.ERROR,
            solve_time_seconds=0.0,
            error_message=f"Solve task failed: {payload}",
        )
    elif payload.get("status") == "success":
        result = OptimizationResult(**payload["result"])
    else:
        # Task-level error: the worker returned {"status": "error"} (an exception
        # it caught).
        result = OptimizationResult(
            status=SolverStatus.ERROR,
            solve_time_seconds=0.0,
            error_message=str(payload.get("error") or "Solve failed"),
        )

    result.execution_id = execution_id
    envelope = payload if isinstance(payload, dict) else {}
    result.solver_used = envelope.get("solver_used") or solver_used
    result.auto_route_reason = envelope.get("auto_route_reason") or auto_route_reason
    warning = envelope.get("warning")
    if warning is None and fallback_triggered:
        # Same message the sync route surfaces on a Hexaly→SCIP fallback.
        warning = "Hexaly temporarily unavailable; solved with SCIP (quadratic quality may differ)"
    if warning is not None:
        result.warning = warning
    return result.model_dump(mode="json")


def _enqueue_multi_objective_async(
    *,
    db: Session,
    org: Organization,
    user: Any,
    problem: OptimizationProblem,
    config: MultiObjectiveConfig,
    workspace_id: str | None,
    origin: str | None,
    source_kind: str | None,
    source_id: str | None,
) -> EnqueuedSolve:
    """Enqueue a multi-objective solve (ADR-007 S4b).

    Multi-objective can't ride ``enqueue_async_solve`` (that hardcodes the
    single-solve task + auto-routing). It always runs SCIP scalarization (no
    routing) and dispatches the dedicated ``solve_multi_objective_async`` task.
    Same pending-row + queue time-limit discipline as the single-solve path.
    """
    from app.domains.solver.tasks.solve_tasks import solve_multi_objective_async
    from app.shared.utils.id_generator import generate_id

    problem = _enforce_tier_caps(db, org, problem)
    annotate_variable_structure(problem)  # recover flat index structure (no-op for JModel)
    execution_id = generate_id("exe_")

    # Provenance up front (sanitized) — mirrors the single-solve enqueue; the typed
    # project column is only set when source_id names a real in-org project.
    mo_source = ExecutionSource.from_request(origin, source_kind, source_id)
    typed_model_project_id: str | None = None
    if mo_source.source_kind == "model_project" and mo_source.source_id:
        owns_project = (
            db.query(ModelProject.id)
            .filter(
                ModelProject.id == mo_source.source_id,
                ModelProject.organization_id == org.id,
            )
            .first()
        )
        if owns_project:
            typed_model_project_id = mo_source.source_id

    # Validate BEFORE enqueuing (parity with the single-solve enqueue).
    validate_problem(problem)

    problem_data = problem.model_dump(mode="json")
    config_data = config.model_dump(mode="json")

    soft_limit, hard_limit = compute_celery_time_limits(db, problem.options.time_limit_seconds)
    target_queue = resolve_queue("scip")

    # P1.5 F0 (ADR-007 debt): insert-before-enqueue with a pre-generated task id — same
    # rationale as the single-solve enqueue (the worker keys off ``celery_task_id``).
    celery_task_id = str(uuid4())

    execution = execution_writer.insert_pending(
        db,
        execution_id=execution_id,
        organization_id=org.id,
        celery_task_id=celery_task_id,
        input_data=problem_data,
        solver_name="scip",
        executed_by_user_id=user.id if user else None,
        origin=mo_source.origin,
        source_kind=mo_source.source_kind,
        source_id=mo_source.source_id,
        model_project_id=typed_model_project_id,
    )
    # Same audit parity as the single-solve enqueue.
    log_action(
        db,
        organization_id=org.id,
        actor=user,
        action=AuditAction.SOLVE,
        workspace_id=workspace_id,
        target_type="execution",
        target_id=execution_id,
        target_name=str(problem_data.get("name") or "multi_objective"),
        metadata={"solver": "scip", "multi_objective": True},
    )
    pending_committed = False
    try:
        db.commit()
        pending_committed = True
    except Exception:
        logger.warning(
            "Failed to commit pending ModelExecution %s before multi-objective enqueue",
            execution_id,
            exc_info=True,
        )
        db.rollback()

    try:
        task = solve_multi_objective_async.apply_async(
            kwargs={
                "problem_data": problem_data,
                "config_data": config_data,
                "organization_id": org.id,
                "user_id": user.id if user else None,
                "workspace_id": workspace_id,
            },
            task_id=celery_task_id,
            queue=target_queue,
            soft_time_limit=soft_limit,
            time_limit=hard_limit,
        )
    except Exception as exc:
        logger.error("apply_async failed for multi-objective solve %s: %s", execution_id, exc)
        if pending_committed:
            _mark_enqueue_failed(db, execution, f"Failed to enqueue task: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "enqueue_failed",
                "message": "Failed to enqueue multi-objective solve. Please retry shortly.",
            },
        ) from exc

    _log_solve_analytics(db, org, user, problem)

    task_envelope = {
        # P1.5 F0: the pre-generated id (submitted via task_id=) is the single id
        # shared by the envelope, the pending row and the running task.
        "task_id": celery_task_id,
        "execution_id": execution_id,
        "status": "pending",
        "message": "Multi-objective task queued for processing",
        "ws_url": f"/api/v2/ws/executions/{celery_task_id}",
        "poll_url": f"/api/v2/solve/async/{celery_task_id}",
    }
    return EnqueuedSolve(
        task=task,
        execution_id=execution_id,
        effective_solver="scip",
        auto_route_reason=None,
        fallback_triggered=False,
        envelope=task_envelope,
    )


def apply_solution_filter(result: Any, solution_filter: str | None) -> Any:
    """Compact-solution presentation for programmatic callers (MCP agents, ERPs).

    ``solution_filter="nonzero"`` drops near-zero variables from the response's
    ``variables``/``solution`` and records how many were omitted in
    ``variables_omitted`` — a few hundred binaries otherwise blow an MCP
    client's token budget. Presentation-only: the persisted ModelExecution
    keeps the full solution. Passthrough for 202 envelopes, error shapes, and
    anything without a solution.
    """
    if solution_filter != "nonzero":
        return result
    if isinstance(result, OptimizationResult):
        payload = result.model_dump(mode="json")
    elif isinstance(result, dict):
        payload = result
    else:
        return result

    omitted = 0
    variables = payload.get("variables")
    if isinstance(variables, list):
        kept_vars = [v for v in variables if abs(v.get("value") or 0.0) > _NEAR_ZERO]
        omitted = max(omitted, len(variables) - len(kept_vars))
        payload["variables"] = kept_vars
    solution = payload.get("solution")
    if isinstance(solution, dict):
        kept_sol = {k: v for k, v in solution.items() if abs(v or 0.0) > _NEAR_ZERO}
        omitted = max(omitted, len(solution) - len(kept_sol))
        payload["solution"] = kept_sol
    if omitted:
        payload["variables_omitted"] = omitted
    return payload
