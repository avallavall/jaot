"""The job envelope cached in ``ModelExecution.scenario_analysis``.

A what-if batch (Sensitivity L2) is minutes of solving, so the row has to carry
more than the answer: it carries the JOB — queued / running / completed /
failed, when it started, and the result once there is one. That is what lets a
second request join the batch already in flight instead of starting a rival one,
and what lets the UI show "running" across a page reload.

Mostly pure dict helpers; ``claim_batch`` is the one exception — claiming has to
happen under a row lock to be meaningful, so it takes the session and leaves the
commit to its caller.
"""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import ModelExecution
from app.schemas.optimization import ScenarioAnalysis
from app.shared.utils.datetime_helpers import utcnow

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Grace on top of the batch budget before a "running" job is considered dead.
# Covers the worker's own soft/hard kill margins: a batch that outlives its
# budget by this much was lost with its worker, not still working.
STALE_GRACE_SECONDS = 180


def running_job(task_id: str | None, budget_seconds: float) -> dict[str, Any]:
    """Envelope for a batch that has just been queued."""
    return {
        "status": STATUS_RUNNING,
        "task_id": task_id,
        "requested_at": utcnow().isoformat(),
        "budget_seconds": budget_seconds,
        "completed_at": None,
        "error": None,
        "result": None,
        "progress": None,
    }


def with_progress(job: dict[str, Any], done: int, planned: int) -> dict[str, Any]:
    """Envelope carrying how far a still-running batch has got.

    Minutes of solving used to show one unchanging sentence, which reads exactly
    like a hang. Terminal states are never overwritten: a progress tick arriving
    after the batch finished must not resurrect "running".
    """
    if job.get("status") != STATUS_RUNNING:
        return job
    return {**job, "progress": {"done": done, "planned": planned}}


def completed_job(job: dict[str, Any], analysis: ScenarioAnalysis) -> dict[str, Any]:
    """Envelope carrying the finished analysis."""
    return {
        **job,
        "status": STATUS_COMPLETED,
        "completed_at": utcnow().isoformat(),
        "progress": None,
        "error": None,
        "result": analysis.model_dump(mode="json"),
    }


def failed_job(job: dict[str, Any], error: str) -> dict[str, Any]:
    """Envelope for a batch that could not be produced."""
    return {
        **job,
        "status": STATUS_FAILED,
        "completed_at": utcnow().isoformat(),
        "progress": None,
        "error": error[:1000],
        "result": None,
    }


def claim_batch(
    db: Session,
    execution_id: str,
    organization_id: str,
    budget_seconds: float,
    task_id: str | None = None,
) -> tuple[ModelExecution | None, dict[str, Any], bool]:
    """Lock the execution row and claim its what-if batch for this caller.

    Returns ``(execution, job, claimed)``. Only the caller that gets
    ``claimed=True`` may dispatch a task; everyone else gets the job already in
    flight (or the finished one) and dispatches nothing. The row lock — not the
    read-then-write — is what makes that hold under real concurrency, so two
    simultaneous requests can never buy two batches of full re-solves.

    ``task_id`` is the id the caller will dispatch WITH (Celery honours a
    pre-generated one), so the claim is the only write this request makes: a
    write-back after dispatch would race a fast worker and could bury a finished
    result under a stale "running" envelope.

    The caller owns the transaction: the lock lives until it commits.
    """
    execution = (
        db.query(ModelExecution)
        .filter(
            ModelExecution.id == execution_id,
            ModelExecution.organization_id == organization_id,
        )
        # `of=` because the row eager-joins an optional OrganizationModel and
        # Postgres refuses a bare FOR UPDATE over the nullable side of a join.
        .with_for_update(of=ModelExecution)
        .first()
    )
    if execution is None:
        return None, {}, False

    job = execution.scenario_analysis or {}
    if is_running(job) or job.get("status") == STATUS_COMPLETED:
        return execution, job, False

    claimed_job = running_job(task_id, budget_seconds)
    execution.scenario_analysis = claimed_job
    return execution, claimed_job, True


def is_running(job: dict[str, Any] | None) -> bool:
    """True while a batch is in flight and still within its own deadline.

    A job whose budget (plus the worker's kill margins) has elapsed without a
    terminal write went down with its worker — reporting it as running forever
    would make the button permanently dead, so it reads as not-running and the
    next request may re-queue it.
    """
    if not job or job.get("status") != STATUS_RUNNING:
        return False
    started = _parse(job.get("requested_at"))
    if started is None:
        return False
    budget = float(job.get("budget_seconds") or 0.0)
    return (utcnow() - started).total_seconds() < budget + STALE_GRACE_SECONDS


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
