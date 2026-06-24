"""Celery application configuration for async task processing."""

import logging
import os

from celery import Celery, signals

from app.config import settings
from app.shared.core.celery_queue_audit import _assert_queue_coherence_on_boot

logger = logging.getLogger(__name__)

# RabbitMQ broker URL from environment
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "amqp://jaot:jaot@localhost:5672//")

# Result backend: Redis preferred (SOLV-03) — persists across worker restarts.
# Falls back to rpc:// for local dev without Redis.
# result_expires = 7 days (604800s) — async solve results available for 1 week.
_redis_url = os.getenv("REDIS_URL", "")
if _redis_url:
    CELERY_RESULT_BACKEND = _redis_url
else:
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "rpc://")

celery_app = Celery(
    "jaot",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "app.domains.solver.tasks.solve_tasks",
        "app.tasks.email_tasks",
        "app.tasks.webhook_tasks",
        "app.tasks.trigger_tasks",
        "app.tasks.cron_tasks",
        "app.tasks.financial_tasks",  # Scheduled withdrawals + reconciliation
        "app.tasks.hexaly_platform_license_expiry",  # Phase 7.4 / HEX-09 - platform license sweep
        "app.tasks.contact_tasks",  # Phase 9 — public contact-form SMTP delivery
        "app.tasks.execution_reaper",  # W1/F-01 — stale async execution sweep + refund
    ],
)

# IN-04: single source of truth for the generic queue name. Used as
# task_default_queue AND in every beat_schedule[*].options.queue entry — the
# beat options are intentionally explicit (defensive form documented in
# CONTEXT.md D-08 — a future change to task_default_queue cannot silently
# re-route beat tasks). Extracting this constant locks both sites together
# so a rename touches one line and the boot-time queue audit catches drift.
_GENERIC_QUEUE = "jaot_default"

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task execution settings
    task_acks_late=True,  # Acknowledge after task completes
    task_reject_on_worker_lost=True,  # Requeue if worker dies
    # Result settings
    result_expires=settings.CELERY_RESULT_EXPIRES,
    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time per worker
    worker_concurrency=2,  # 2 concurrent workers
    # Required for celery-exporter to populate task-runtime and failure metrics.
    worker_send_task_events=True,
    task_send_sent_event=True,
    # Solve tasks route dynamically at the producer call site via
    # resolve_queue(). Generic tasks (email, webhooks, financial, contact,
    # cron, hexaly-expiry) inherit task_default_queue='jaot_default' below
    # — the queue consumed by celery_worker_default per docker-compose
    # `-Q jaot_default`. Boot-time audit (worker_init signal, plan 10-02 +
    # CR-02 fix) refuses to start the worker if any task or beat entry
    # references a queue not in the worker's -Q flag, so this file and
    # docker-compose.prod.yml CANNOT drift silently again.
    task_routes={},
    # Default queue
    task_default_queue=_GENERIC_QUEUE,
    # Beat scheduler: use SQLAlchemy backend for dynamic cron schedules
    beat_dburi=settings.DATABASE_URL,
    beat_schema=None,
)

_DAILY_SECONDS: int = 86400
# W1/F-01 — reaper cadence. 15 min keeps the zombie window well under the
# smallest reap threshold (EXECUTION_REAPER_PENDING_MAX_SECONDS, default 30 min).
_REAPER_INTERVAL_SECONDS: int = 900

# Beat schedule for financial tasks (D-25, D-27) + Phase 7 solver license sweep (D-25).
# Static fallback -- also works alongside sqlalchemy_celery_beat DB-backed schedules.
celery_app.conf.beat_schedule = {
    "process-scheduled-withdrawals": {
        "task": "process_scheduled_withdrawals",
        "schedule": _DAILY_SECONDS,
        "options": {"queue": _GENERIC_QUEUE},
    },
    "run-balance-reconciliation": {
        "task": "run_balance_reconciliation",
        "schedule": _DAILY_SECONDS,
        "options": {"queue": _GENERIC_QUEUE},
    },
    # Phase 7.4 / D-07 / HEX-09 — daily sweep of /etc/jaot/hexaly.lic.
    # Updates the HEXALY_LICENSE_DAYS_REMAINING gauge (label license_fingerprint)
    # so Alertmanager fires HexalyPlatformLicenseExpiringSoon when < 30 days.
    "hexaly-platform-license-expiry-sweep": {
        "task": "hexaly_platform_license_expiry_sweep",
        "schedule": _DAILY_SECONDS,
        "options": {"queue": _GENERIC_QUEUE},
    },
    # W1/F-01 — mark stale pending/running ModelExecutions failed and refund
    # pre-paid credits idempotently (app/tasks/execution_reaper.py).
    "reap-stale-executions": {
        "task": "reap_stale_executions",
        "schedule": _REAPER_INTERVAL_SECONDS,
        "options": {"queue": _GENERIC_QUEUE},
    },
}

# Task base class with common settings
celery_app.conf.task_base_class = "celery.Task"


@signals.worker_init.connect
def _audit_queue_coherence_on_boot(**_kwargs: object) -> None:
    """Phase 10 / D-08 layer 1 — fail-fast producer/consumer queue audit.

    Runs in the MASTER worker process BEFORE the prefork pool forks (Celery
    5.x ``worker_init`` signal). If any queue referenced by ``task_routes``,
    ``beat_schedule[*].options.queue``, or ``task_default_queue`` is not in
    this worker's consumed queue set, the audit logs CRITICAL with the
    orphan queue names and calls ``sys.exit(1)`` — exiting the MASTER (and
    therefore the container) so Docker's ``restart: unless-stopped`` sees a
    non-zero exit and the operator gets a visible restart loop.

    CR-02 fix: was previously bound to ``worker_process_init`` which fires
    inside the prefork CHILD. ``sys.exit(1)`` there only killed the child;
    the master respawned it indefinitely, leaving the container "running"
    while no work flowed — exactly the failure mode the audit was meant to
    prevent (CONTEXT.md D-08 fail-fast contract).

    Provenance: Phase 9's queue mismatch went undetected for ~37 days
    because the broker happily accepted producer messages with no consumer;
    log-only is not an acceptable failure mode (CONTEXT.md D-08).
    """
    _assert_queue_coherence_on_boot(celery_app)


@signals.worker_process_init.connect
def _configure_worker_email_service(**_kwargs: object) -> None:
    """Configure EmailService in each worker process.

    FastAPI's lifespan (app/main.py) configures EmailService for the api process
    only. Celery worker processes never run that lifespan, so without this hook
    they keep the default ConsoleBackend — every send returns True without
    actually delivering, and rows get status='sent' while the SMTP layer is
    bypassed entirely. Fires per child process in the prefork model.

    NOTE: This stays bound to ``worker_process_init`` (per-child) — unlike the
    queue audit above, EmailService configuration MUST run in each prefork
    child because the SMTP backend is a process-local cache that does not
    inherit cleanly across fork(). CR-02 only moved the audit signal; this
    handler is correctly per-child and remains so.
    """
    try:
        from app.services.email_service import EmailService
        from app.shared.db.session import SessionLocal

        db = SessionLocal()
        try:
            EmailService.configure_from_pss(db)
        finally:
            db.close()
    except Exception as exc:
        # Never crash the worker because of a config-read failure — log and
        # let the default ConsoleBackend stay so the process still serves
        # non-email tasks (solve_*, webhooks, etc.). Logged at ERROR with
        # exc_info: a silently misconfigured backend marks rows status='sent'
        # while bypassing SMTP, which is a data-integrity bug worth paging on.
        logger.error("Worker EmailService.configure failed: %s", exc, exc_info=True)
