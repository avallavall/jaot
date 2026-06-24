"""Phase 10 / D-08 layer 1 — boot-time producer/consumer queue-coherence audit.

Invariant: if any queue name referenced by `task_routes`, `beat_schedule[*].
options.queue`, or `task_default_queue` is NOT in the worker's consumed queue
set (-Q flag, `task_queues` conf, or the SOLVER_QUEUE consumer guard env var
from plan 06), the worker MUST exit non-zero before consuming a single task.

Provenance: a Phase-9 producer/consumer mismatch (`task_default_queue="default"`
combined with `celery_worker_default -Q celery`) accumulated ~37 days of
unconsumed scheduled tasks on the orphan `default` queue. The broker happily
accepted producer messages with no consumer; nothing surfaced because Celery's
default behavior is to log-and-continue. **Log-only is not an acceptable
failure mode** — see decision D-08
("the startup check MUST refuse to start the worker on mismatch (fail-fast)").

Wiring: `app/shared/core/celery_app.py` connects `_assert_queue_coherence_on_boot`
to the `@signals.worker_init` signal — fires in the MASTER worker process
BEFORE the prefork pool forks. Calling `sys.exit(1)` there exits the master
(and therefore the container), so Docker's `restart: unless-stopped` sees a
non-zero exit and the operator gets a visible restart loop. The previous
binding to `worker_process_init` (per prefork CHILD) only killed children
and let the master respawn them indefinitely — fixed in CR-02.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


_specialized_queues: set[str] = set()


def register_specialized_queues(queues: Iterable[str]) -> None:
    """Declare which queue names are owned by specialized (non-default) workers.

    The audit uses this set to identify when the current process is a
    specialized worker (e.g. ``-Q solve_scip``) so the producer-coverage check
    is skipped — covering the generic ``task_default_queue`` is the default
    worker's responsibility, not a specialized one's. Cross-worker coverage is
    enforced by ``tests/integration/test_queue_routing_coherence.py``.

    Boundary note: import-linter forbids ``app/shared`` from importing from
    ``app/domains``. The solver domain (which owns ``SOLVER_QUEUE_MAP``) must
    call this function from its own bootstrap so the audit reads
    domain-specific data without ``app/shared`` reaching into ``app/domains``.
    Idempotent: re-registering the same names is a no-op.
    """
    _specialized_queues.update(name for name in queues if isinstance(name, str) and name)


def _clear_specialized_queues_for_tests() -> None:
    """Test-only hook: drop everything registered. Pytest fixtures call this
    so tests that exercise the default-worker path are not contaminated by a
    previous test's specialized registration.
    """
    _specialized_queues.clear()


def _solver_queues() -> frozenset[str]:
    """Return the registered specialized-queue set as a frozenset.

    Empty set is the safe default — when no queues are registered, every
    worker falls through to the producer-coverage check (Phase 9 protection).
    """
    return frozenset(_specialized_queues)


@dataclass(frozen=True)
class AuditResult:
    """Outcome of one producer/consumer queue-coherence check.

    Attributes:
        producer_queues: union of queues referenced by task_default_queue,
            task_routes[*]["queue"], and beat_schedule[*]["options"]["queue"].
        consumer_queues: union of queues this worker consumes (from task_queues
            conf, -Q flag in argv, or the SOLVER_QUEUE env var fallback).
        missing: producer_queues - consumer_queues; non-empty means mismatch.
        ok: True iff missing is empty.
    """

    producer_queues: frozenset[str]
    consumer_queues: frozenset[str]
    missing: frozenset[str]
    ok: bool


def _extract_producer_queues(celery_conf: object) -> frozenset[str]:
    """Collect every queue REFERENCED on the producer side.

    Reads three Celery conf fields:
    - `task_default_queue` (str): default routing target for any task without
      a static route, e.g. "jaot_default" post-plan-10-01.
    - `task_routes` (dict[str, dict]): static per-task routing overrides; each
      value may carry a "queue" key. Missing "queue" means inheritance — not a
      reference, so we do NOT add it to the producer set.
    - `beat_schedule` (dict[str, dict]): cron-like scheduled tasks; each entry
      may carry `options.queue`. Same inheritance rule applies.

    Guards against None / missing keys / non-dict route entries so a malformed
    Celery conf surfaces as an empty producer set (the audit then fails-fast
    if any consumer queue is also absent — defensive).
    """
    queues: set[str] = set()

    default_queue = getattr(celery_conf, "task_default_queue", None)
    if isinstance(default_queue, str) and default_queue:
        queues.add(default_queue)

    task_routes = getattr(celery_conf, "task_routes", None) or {}
    if isinstance(task_routes, dict):
        for route in task_routes.values():
            if isinstance(route, dict):
                route_queue = route.get("queue")
                if isinstance(route_queue, str) and route_queue:
                    queues.add(route_queue)

    beat_schedule = getattr(celery_conf, "beat_schedule", None) or {}
    if isinstance(beat_schedule, dict):
        for entry in beat_schedule.values():
            if not isinstance(entry, dict):
                continue
            options = entry.get("options")
            if isinstance(options, dict):
                beat_queue = options.get("queue")
                if isinstance(beat_queue, str) and beat_queue:
                    queues.add(beat_queue)

    return frozenset(queues)


def _parse_dash_q(argv: list[str]) -> frozenset[str]:
    """Parse the `-Q queue1,queue2` flag from a Celery CLI argv.

    Comma-separated forms are split and whitespace-trimmed. Empty pieces are
    dropped. If `-Q` is absent or the token after it is missing, returns an
    empty frozenset and the caller falls back to other sources.
    """
    argv_list = list(argv)
    for idx, token in enumerate(argv_list):
        if token == "-Q" and idx + 1 < len(argv_list):
            raw = argv_list[idx + 1]
            parts = (piece.strip() for piece in raw.split(","))
            return frozenset(piece for piece in parts if piece)
    return frozenset()


def _running_under_pytest(argv: list[str]) -> bool:
    """Detect when the audit is being invoked from inside a pytest run.

    WR-03 guard: when the test suite imports `celery_app` (e.g. via the
    integration tests in `tests/integration/test_queue_routing_coherence.py`),
    the module-level signal binding is wired but the audit is never invoked
    via a Celery worker boot. If it WERE invoked (e.g. a future test that
    constructs a real Worker), `sys.argv` would look like
    `['pytest', '-x', '...']` and the `-Q` parser would return an empty
    consumer set, fail-fasting on every test. Detect pytest by program name
    and let the caller treat that as "no argv-derived consumer queues" so
    the audit falls through to `SOLVER_QUEUE` env or the empty-set path
    (which the test caller controls via explicit `argv=...` anyway).
    """
    if not argv:
        return False
    arg0 = os.path.basename(argv[0]).lower()
    # Cover pytest, py.test, and the windows .exe forms.
    return arg0 in {"pytest", "py.test", "pytest.exe", "py.test.exe"}


def _extract_consumer_queues(celery_conf: object, argv: list[str] | None = None) -> frozenset[str]:
    """Collect every queue this worker CONSUMES.

    Three sources, in priority order:
    1. `celery_conf.task_queues` — a tuple of `kombu.Queue` (or equivalent)
       objects. Each has a `.name` attribute. Present only when explicitly
       set in the Celery config; this codebase does NOT set it (verify via
       grep).
    2. `-Q` flag in argv — the canonical worker-start form used by every
       celery_worker_* compose service. Default argv is `sys.argv`. Callers
       embedding Celery (pytest, gunicorn) should pass an explicit `argv`
       parameter; an unset `argv` falls back to `sys.argv` only if the
       process is NOT detectably running under pytest (WR-03 guard).
    3. `SOLVER_QUEUE` env var — the consumer-side guard set by every worker
       in `deploy/docker-compose.prod.yml`. Single value, no comma form
       expected.

    Returns an empty frozenset if all three sources are absent — the audit
    then fails-fast (better than silently passing with a phantom-healthy state).
    """
    task_queues = getattr(celery_conf, "task_queues", None)
    if task_queues:
        names: set[str] = set()
        try:
            for queue in task_queues:
                name = getattr(queue, "name", None)
                if isinstance(name, str) and name:
                    names.add(name)
        except (TypeError, AttributeError) as exc:
            # WR-01: broadened from `except TypeError` so a malformed
            # task_queues entry (custom __getattr__ raising AttributeError,
            # kombu.Queue subclass failing on attribute access during init)
            # falls through cleanly to argv parsing instead of bubbling an
            # unhandled exception out of the signal handler. Logged at
            # WARNING so operators can still inspect the malformed config.
            logger.warning(
                "task_queues iteration failed (%s: %s) — falling back to argv parsing",
                type(exc).__name__,
                exc,
            )
            names = set()
        if names:
            return frozenset(names)

    # WR-03: only consult sys.argv when the caller has not passed an explicit
    # argv AND the process does not look like pytest. Tests that need to
    # exercise the audit MUST pass argv explicitly (every test in
    # tests/unit/test_celery_queue_audit.py already does this); falling back
    # to ['pytest', ...] in sys.argv produces a false-negative empty consumer
    # set that would fail-fast under embedded Celery.
    if argv is not None:
        argv_for_parse: list[str] | None = argv
    elif _running_under_pytest(sys.argv):
        argv_for_parse = None
    else:
        argv_for_parse = sys.argv
    if argv_for_parse is not None:
        parsed = _parse_dash_q(argv_for_parse)
        if parsed:
            return parsed

    # Last-resort fallback: the SOLVER_QUEUE consumer guard env var, set per
    # worker service in docker-compose.prod.yml. Kept narrow (single value)
    # because it was designed for the per-solver guard, not for multi-queue.
    env_queue = os.environ.get("SOLVER_QUEUE", "").strip()
    if env_queue:
        return frozenset({env_queue})

    return frozenset()


_MALFORMED_CONF_SENTINEL = "<no producer queues — conf malformed>"


def _conf_has_routing_intent(celery_conf: object) -> bool:
    """WR-05 helper: detect when a conf claims routing config but yields no queues.

    Returns True if ANY of `task_default_queue` (truthy), `task_routes`
    (non-empty mapping), or `beat_schedule` (non-empty mapping) is present
    on the conf — i.e. the operator clearly intends to route work somewhere.
    Combined with an empty producer set, that means the conf is malformed
    (likely `task_default_queue=None` or routes/beat values that fail the
    `isinstance(..., str)` filter in `_extract_producer_queues`). The audit
    should surface this as a mismatch, not silently pass.
    """
    default_queue = getattr(celery_conf, "task_default_queue", None)
    if default_queue:
        return True

    task_routes = getattr(celery_conf, "task_routes", None)
    if isinstance(task_routes, dict) and task_routes:
        return True

    beat_schedule = getattr(celery_conf, "beat_schedule", None)
    if isinstance(beat_schedule, dict) and beat_schedule:
        return True

    return False


def audit_queue_coherence(celery_app: object, argv: list[str] | None = None) -> AuditResult:
    """Pure audit: compute producer/consumer queue sets and report missing.

    This function is side-effect-free (no logging, no sys.exit). The
    signal-bound wrapper `_assert_queue_coherence_on_boot` adds the
    fail-fast log + exit behavior on top.

    WR-05: an empty producer set with a conf that DOES claim routing intent
    (task_default_queue/task_routes/beat_schedule non-empty but yields no
    string queue names) is itself a malformed-conf failure — the docstring
    of ``_extract_producer_queues`` claims fail-fast on this case. Surface
    it as a synthetic missing-queue mismatch so ``ok=False`` and the boot
    guard's CRITICAL log + sys.exit(1) path fires. If the conf has no
    routing intent at all (truly empty config), the audit returns ok=True
    with empty sets — nothing was supposed to be routed anywhere.

    Role-split (post-CR-03, prod incident 2026-05-19): the audit only enforces
    producer-coverage on the **default worker** (the catch-all for generic
    tasks). Specialized workers (scip/highs/hexaly) own a dedicated solver
    queue and are not responsible for covering the generic producer set;
    before this fix the audit ran on every worker and the specialized workers
    were restart-looping in production because ``producer={jaot_default}``
    was never in their ``consumer={solve_scip}`` set. Role is detected by
    intersecting ``consumer_queues`` with the known solver-queue set (from
    ``SOLVER_QUEUE_MAP``): when the intersection is non-empty this worker is
    specialized and the audit short-circuits to ok=True. Cross-worker
    coverage ("every producer queue has SOME consumer in the cluster") is
    verified by ``tests/integration/test_queue_routing_coherence.py`` which
    parses docker-compose.prod.yml — that is the right layer for the
    cross-worker check; the runtime audit only sees its own process.
    """
    conf = getattr(celery_app, "conf", celery_app)
    producer_queues = _extract_producer_queues(conf)
    consumer_queues = _extract_consumer_queues(conf, argv=argv)

    if not producer_queues and _conf_has_routing_intent(conf):
        return AuditResult(
            producer_queues=frozenset(),
            consumer_queues=consumer_queues,
            missing=frozenset({_MALFORMED_CONF_SENTINEL}),
            ok=False,
        )

    if consumer_queues & _solver_queues():
        return AuditResult(
            producer_queues=producer_queues,
            consumer_queues=consumer_queues,
            missing=frozenset(),
            ok=True,
        )

    missing = producer_queues - consumer_queues
    return AuditResult(
        producer_queues=producer_queues,
        consumer_queues=consumer_queues,
        missing=missing,
        ok=len(missing) == 0,
    )


def _assert_queue_coherence_on_boot(celery_app: object, argv: list[str] | None = None) -> None:
    """Signal-bound entrypoint: audit, log, fail-fast on mismatch.

    Wiring contract (see `app/shared/core/celery_app.py`):
    ``@signals.worker_init.connect`` decorates a thin wrapper that
    calls this function with the module-level `celery_app`. Runs once in
    the MASTER worker process BEFORE the prefork pool forks — so
    ``sys.exit(1)`` exits the master (and the container), letting Docker's
    restart policy surface a visible failure to the operator.

    Success path: log at INFO level a one-line confirmation ("queue audit
    passed") that the runbook §3 verification step (plan 10-00) can grep
    for, then return.

    Failure path: log at CRITICAL with the orphan queue names listed
    (post-mortem inspection of the container's stderr identifies which
    config side drifted), then call `sys.exit(1)`. The CRITICAL log is
    issued BEFORE the exit so it flushes to stderr before the container
    terminates. Log-only is NOT acceptable — Phase 9's bug went undetected
    for ~37 days specifically because the broker happily accepted producer
    messages with no consumer-side log signal.
    """
    result = audit_queue_coherence(celery_app, argv=argv)
    if result.ok:
        logger.info(
            "worker_init: queue audit passed (producers=%s consumers=%s)",
            sorted(result.producer_queues),
            sorted(result.consumer_queues),
        )
        return

    logger.critical(
        "worker_init: queue audit FAILED — producer-side references "
        "queues no consumer-side -Q flag covers. missing=%s producers=%s "
        "consumers=%s. Refusing to start worker. Fix the routing config "
        "(see plan 10-02 / CONTEXT.md D-08) and redeploy.",
        sorted(result.missing),
        sorted(result.producer_queues),
        sorted(result.consumer_queues),
    )
    sys.exit(1)
