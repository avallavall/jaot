"""Unit tests for `app.shared.core.celery_queue_audit` — Phase 10 / D-08 layer 1.

Locks in the boot-time audit contract that prevents the producer/consumer
queue-name mismatch that went undetected for ~37 days in Phase 9. Each test
exercises ONE behavior in isolation; the audit module is exercised against a
`MagicMock` celery_app — no real Celery instance is required.

Reference: decision D-08.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from app.shared.core.celery_queue_audit import (
    AuditResult,
    _assert_queue_coherence_on_boot,
    _clear_specialized_queues_for_tests,
    audit_queue_coherence,
    register_specialized_queues,
)


@pytest.fixture(autouse=True)
def _reset_specialized_queues_registry() -> None:
    """Clear the audit's specialized-queue registry before each test.

    The registry is populated at import time by
    ``app/domains/solver/adapters/__init__.py::register_default_adapters()``
    during normal app bootstrap. In the unit-test suite, importing other
    modules can transitively load the solver domain and pre-populate the
    registry; this fixture isolates each test from that leak so the
    default-worker tests see an empty registry (correct precondition) and
    the specialized-worker test explicitly registers what it needs.
    """
    _clear_specialized_queues_for_tests()


def _make_fake_celery_app(
    task_default_queue: str = "jaot_default",
    task_routes: dict[str, dict[str, str]] | None = None,
    beat_schedule: dict[str, dict[str, object]] | None = None,
    task_queues: object | None = None,
) -> MagicMock:
    """Build a MagicMock celery_app with the four conf fields the audit reads.

    Defaults to a healthy post-plan-10-01 state: jaot_default everywhere,
    no static routes, no explicit task_queues (consumer set comes from argv).
    """
    fake = MagicMock()
    fake.conf.task_default_queue = task_default_queue
    fake.conf.task_routes = task_routes if task_routes is not None else {}
    fake.conf.beat_schedule = beat_schedule if beat_schedule is not None else {}
    fake.conf.task_queues = task_queues
    return fake


def test_audit_passes_when_all_queues_consumed() -> None:
    """Healthy state: every producer-side queue reference is in the consumer set."""
    fake_app = _make_fake_celery_app(
        beat_schedule={
            "daily-task": {
                "task": "some_task",
                "schedule": 86400.0,
                "options": {"queue": "jaot_default"},
            },
        },
    )
    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )
    assert isinstance(result, AuditResult)
    assert result.ok is True
    assert result.missing == frozenset()
    assert result.producer_queues == frozenset({"jaot_default"})
    assert result.consumer_queues == frozenset({"jaot_default"})


def test_audit_detects_orphan_default_queue() -> None:
    """task_default_queue points at a queue no worker consumes -> ok=False."""
    fake_app = _make_fake_celery_app(task_default_queue="orphan_queue")
    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )
    assert result.ok is False
    assert "orphan_queue" in result.missing


def test_audit_detects_orphan_task_route() -> None:
    """A task_routes entry targets a queue no worker consumes -> ok=False."""
    fake_app = _make_fake_celery_app(
        task_routes={"some_task": {"queue": "ghost"}},
    )
    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )
    assert result.ok is False
    assert "ghost" in result.missing


def test_audit_detects_orphan_beat_entry() -> None:
    """A beat_schedule entry targets a queue no worker consumes -> ok=False."""
    fake_app = _make_fake_celery_app(
        beat_schedule={
            "phantom-beat": {
                "task": "phantom_task",
                "schedule": 60.0,
                "options": {"queue": "vanished"},
            },
        },
    )
    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )
    assert result.ok is False
    assert "vanished" in result.missing


def test_audit_ignores_unmentioned_solver_queues() -> None:
    """Solver queues route dynamically via resolve_queue() at producer site
    (Phase 6 / D-03) — they MUST NOT be flagged as missing just because the
    default worker does not consume them. The audit scope is ONLY the queues
    REFERENCED in task_routes + beat_schedule + task_default_queue."""
    fake_app = _make_fake_celery_app()  # healthy default state, no solver mentions
    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )
    # Healthy: ok=True even though solve_scip/solve_highs/solve_hexaly are
    # NOT in this worker's -Q flag. Those queues are consumed by per-solver
    # workers (celery_worker_scip / _highs / _hexaly); the audit operates
    # on the union of REFERENCED queues, not the universe of possible queues.
    assert result.ok is True
    assert result.missing == frozenset()


def test_specialized_worker_skips_producer_coverage_check() -> None:
    """Production incident 2026-05-19: the audit must NOT enforce producer-coverage
    on a specialized solver worker. A worker booted with ``-Q solve_scip`` owns
    ONLY its dedicated queue; the catch-all ``jaot_default`` queue is the default
    worker's responsibility, not this one's. Before the role-split fix, every
    specialized worker was restart-looping with ``missing=['jaot_default']``
    because the audit confused "producer must be covered SOMEWHERE in the
    cluster" with "this worker must cover producer". Cross-worker coverage is
    enforced by tests/integration/test_queue_routing_coherence.py (parses
    compose). Role-detection: consumer overlaps the queues registered via
    ``register_specialized_queues`` (called from the solver domain bootstrap;
    keeps the app/shared boundary clean per import-linter).
    """
    register_specialized_queues({"solve_scip", "solve_highs", "solve_hexaly"})
    fake_app = _make_fake_celery_app()  # healthy producer side (jaot_default)
    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "solve_scip"]
    )
    assert result.ok is True
    assert result.missing == frozenset()
    # Even though producer={jaot_default} and consumer={solve_scip} disagree —
    # the role-split detected this as a specialized worker and short-circuited.
    assert result.producer_queues == frozenset({"jaot_default"})
    assert result.consumer_queues == frozenset({"solve_scip"})


def test_default_worker_still_enforces_producer_coverage() -> None:
    """The role-split must NOT relax the default worker's check — a Phase-9-style
    mismatch (task_default_queue points at an orphan queue while the default
    worker consumes ``jaot_default``) must still fail-fast.
    """
    fake_app = _make_fake_celery_app(task_default_queue="orphan_queue")
    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )
    assert result.ok is False
    assert "orphan_queue" in result.missing


def test_consumer_queues_parsed_from_dash_q_argv() -> None:
    """When task_queues is None, the helper falls back to parsing sys.argv
    for the `-Q` flag, including the comma-separated multi-queue form."""
    fake_app = _make_fake_celery_app()
    result_single = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )
    assert result_single.consumer_queues == frozenset({"jaot_default"})

    result_multi = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default,solve_scip"]
    )
    assert result_multi.consumer_queues == frozenset({"jaot_default", "solve_scip"})


def test_boot_guard_exits_non_zero_on_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    """When the audit fails, _assert_queue_coherence_on_boot logs CRITICAL
    naming the orphan queue and then calls sys.exit(1)."""
    fake_app = _make_fake_celery_app(task_default_queue="orphan_queue")

    caplog.set_level(logging.CRITICAL, logger="app.shared.core.celery_queue_audit")

    with pytest.raises(SystemExit) as exc_info:
        _assert_queue_coherence_on_boot(
            fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
        )

    assert exc_info.value.code == 1
    # The CRITICAL log MUST name the orphan queue so post-mortem inspection
    # of the worker container's stderr identifies the mismatch.
    assert "orphan_queue" in caplog.text


def test_boot_guard_returns_none_on_success(caplog: pytest.LogCaptureFixture) -> None:
    """When the audit passes, _assert_queue_coherence_on_boot returns None
    and logs INFO 'queue audit passed' (so the runbook can grep for it)."""
    fake_app = _make_fake_celery_app()

    caplog.set_level(logging.INFO, logger="app.shared.core.celery_queue_audit")

    result = _assert_queue_coherence_on_boot(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )
    assert result is None
    assert "queue audit passed" in caplog.text


def test_audit_fails_when_conf_claims_routing_intent_but_yields_empty_producer_set() -> None:
    """WR-05: an empty producer set with conf that claims routing intent
    (e.g. task_default_queue=None but beat_schedule non-empty) is itself a
    malformed-conf failure. The audit MUST report ok=False with a sentinel
    in `missing`, NOT silently pass with empty producer/empty missing.
    """
    # Case A: task_default_queue=None (not a string), beat_schedule non-empty.
    # _extract_producer_queues skips None (isinstance check), so producer set is
    # empty even though the beat schedule clearly intends to route somewhere.
    fake_app = _make_fake_celery_app(
        task_default_queue=None,  # type: ignore[arg-type]
        beat_schedule={
            "daily-task": {
                "task": "some_task",
                "schedule": 86400.0,
                "options": {"queue": None},  # also invalid -- not a string
            },
        },
    )

    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )

    assert result.ok is False, (
        "Empty producer set + non-empty beat_schedule should fail-fast — "
        "Phase 9-style routing drift returns silently otherwise (WR-05)."
    )
    assert result.producer_queues == frozenset()
    # The synthetic sentinel makes the failure mode legible in the CRITICAL log.
    assert any("malformed" in m for m in result.missing), (
        f"missing should contain the malformed-conf sentinel; got {result.missing}"
    )


def test_audit_passes_when_conf_truly_empty() -> None:
    """WR-05 negative: a conf with NO routing intent (task_default_queue=None,
    no routes, no beat) should pass with ok=True — there is genuinely nothing
    to route, so no consumer is missing. This guards against the WR-05 fix
    over-firing on a freshly-constructed Celery app before its conf is hydrated.
    """
    fake_app = _make_fake_celery_app(
        task_default_queue=None,  # type: ignore[arg-type]
        task_routes={},
        beat_schedule={},
    )

    result = audit_queue_coherence(
        fake_app, argv=["celery", "-A", "_", "worker", "-Q", "jaot_default"]
    )

    assert result.ok is True
    assert result.producer_queues == frozenset()
    assert result.missing == frozenset()


def test_audit_signal_binding_is_worker_init_not_worker_process_init() -> None:
    """CR-02 regression lock: the audit MUST connect to ``worker_init`` (master
    process, pre-prefork) and NOT to ``worker_process_init`` (per prefork
    child). ``sys.exit(1)`` in a child only kills the child; the master
    respawns it indefinitely and the container never exits — defeating the
    fail-fast contract Docker's restart-policy depends on (CONTEXT.md D-08).
    """
    from celery import signals

    from app.shared.core.celery_app import _audit_queue_coherence_on_boot

    # The function MUST be a receiver of worker_init, not worker_process_init.
    worker_init_receivers = [ref() for _, ref in signals.worker_init.receivers if ref() is not None]
    worker_process_init_receivers = [
        ref() for _, ref in signals.worker_process_init.receivers if ref() is not None
    ]

    assert _audit_queue_coherence_on_boot in worker_init_receivers, (
        "_audit_queue_coherence_on_boot must be connected to signals.worker_init "
        "(master process, pre-prefork) so sys.exit(1) exits the container — see CR-02."
    )
    assert _audit_queue_coherence_on_boot not in worker_process_init_receivers, (
        "_audit_queue_coherence_on_boot must NOT be connected to "
        "signals.worker_process_init (per prefork child) — sys.exit(1) there "
        "only kills the child and the master respawns it forever — see CR-02."
    )
