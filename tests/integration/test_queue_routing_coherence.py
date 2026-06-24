"""CI lock for producer/consumer queue-name coherence — Phase 10 / D-08 layer 3.

Every PR that mutates one side of the producer/consumer queue contract MUST
also mutate the other side, or this test fails red in CI. The test loads the
ACTUAL `celery_app` Python object (not a regex of the source) and parses
EVERY compose file in the repo (`docker-compose.yml`, `deploy/docker-compose.prod.yml`)
for every celery worker service's `-Q` flag, then asserts that every
producer-side queue reference is consumed by at least one worker in each file.

Reference: decision D-08
("the integration test SHOULD load the actual celery_app Python object, not
just regex the source"). Source regex misses the case where a task module is
added without an `include` entry — its own bug-shape.

Phase 10 / CR-01: the original implementation only parsed
`deploy/docker-compose.prod.yml`. The dev `docker-compose.yml` and its test
profile drifted to a different `-Q` flag and the audit refused to start the
worker on local-dev `docker-compose up`. The parser now scans every compose
file and validates each independently against the producer set.

The third test (`test_no_producer_references_orphan_queue_names`) is the
explicit regression lock against the Phase-10 bug returning: any future PR
that reintroduces `"default"` or `"celery"` as a producer-side queue name
fails CI here and blames Phase 10. WR-04 extends it with a domain-prefix
pattern lock.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.shared.core.celery_app import celery_app
from app.shared.core.celery_queue_audit import _extract_producer_queues

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Validate both dev and prod compose. Dev names the service `celery_worker`
# (singular); the test profile uses `celery-worker-test-*`; prod uses
# `celery_worker_*` (suffix). The regex matches all three variants.
_COMPOSE_PATHS: tuple[Path, ...] = (
    _PROJECT_ROOT / "docker-compose.yml",
    _PROJECT_ROOT / "deploy" / "docker-compose.prod.yml",
)
_WORKER_SERVICE_RE = re.compile(r"^celery[_-]worker(?:[_-].+)?$")


def _parse_worker_queues_from_compose(compose_path: Path) -> dict[str, frozenset[str]]:
    """Parse a compose file for every celery worker service's -Q flag.

    Works on any compose file. For each service whose key matches
    `_WORKER_SERVICE_RE`, locate `-Q` in `command` and read the next element,
    splitting on commas (multi-queue form). Returns service -> frozenset of
    consumed queues. Services without `-Q` yield an empty frozenset —
    `test_each_compose_worker_has_q_flag` catches this.
    """
    assert compose_path.exists(), f"compose file missing at {compose_path}"

    compose_yaml = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = compose_yaml.get("services", {})
    assert isinstance(services, dict), "compose `services` is not a mapping"

    result: dict[str, frozenset[str]] = {}
    for service_name, service_config in services.items():
        if not _WORKER_SERVICE_RE.match(service_name):
            continue
        command = service_config.get("command")
        if not isinstance(command, list):
            result[service_name] = frozenset()
            continue
        consumed: set[str] = set()
        for idx, token in enumerate(command):
            if token == "-Q" and idx + 1 < len(command):
                raw = command[idx + 1]
                if isinstance(raw, str):
                    for piece in raw.split(","):
                        piece = piece.strip()
                        if piece:
                            consumed.add(piece)
                break
        result[service_name] = frozenset(consumed)
    return result


@pytest.mark.integration
@pytest.mark.parametrize("compose_path", _COMPOSE_PATHS, ids=lambda p: p.name)
def test_compose_workers_consume_all_producer_queues(compose_path: Path) -> None:
    """Every queue REFERENCED by the producer config is consumed by some worker.

    The canonical CI lock. Loads the real `celery_app` Python object and
    cross-checks its producer-side queue references (task_default_queue +
    task_routes + beat_schedule[*].options.queue) against the union of
    `-Q` flags across all celery worker services in the compose file.

    Phase 10 / CR-01: parametrized over every compose file in the repo
    (root `docker-compose.yml` and `deploy/docker-compose.prod.yml`). A
    future PR that adds a task_routes entry pointing at a queue no worker
    consumes — or a future PR that changes a compose `-Q` flag without
    updating the Python config in ANY file — fails this test red.
    """
    producer_queues = _extract_producer_queues(celery_app.conf)
    assert producer_queues, "producer_queues unexpectedly empty — celery_app misconfigured"

    worker_queues_by_service = _parse_worker_queues_from_compose(compose_path)
    assert worker_queues_by_service, f"no celery worker services found in {compose_path.name}"

    union_consumer_queues: frozenset[str] = frozenset().union(*worker_queues_by_service.values())

    missing = producer_queues - union_consumer_queues
    assert not missing, (
        f"producer/consumer queue mismatch in {compose_path.name} — "
        f"{sorted(missing)} are referenced by celery_app config but NOT "
        f"consumed by any worker service. "
        f"Producer queues: {sorted(producer_queues)}. "
        f"Union of consumer queues: {sorted(union_consumer_queues)}. "
        f"Fix the routing config (CONTEXT.md D-08): either update the "
        f"docker-compose `-Q` flag on a worker service to include the missing "
        f"queue, or remove the producer-side reference from celery_app.py."
    )


@pytest.mark.integration
@pytest.mark.parametrize("compose_path", _COMPOSE_PATHS, ids=lambda p: p.name)
def test_each_compose_worker_has_q_flag(compose_path: Path) -> None:
    """Defensive: every celery worker compose service must specify a -Q flag.

    Catches the case where a new worker service is added to a compose file
    without `-Q queue_name` — the parser would silently treat that service
    as consuming no queues, weakening the union check in the canonical test
    above. Parametrized over all compose files (Phase 10 / CR-01).
    """
    worker_queues_by_service = _parse_worker_queues_from_compose(compose_path)
    assert worker_queues_by_service, f"no celery worker services found in {compose_path.name}"

    services_without_q: list[str] = [
        name for name, queues in worker_queues_by_service.items() if not queues
    ]
    assert not services_without_q, (
        f"worker services missing a -Q flag in their `command` "
        f"({compose_path.name}): {services_without_q}. Every worker MUST "
        f"declare its consumed queue in compose so the boot audit and the CI "
        f"lock have a consumer set to compare against. CONTEXT.md D-08 layer 3."
    )


@pytest.mark.integration
def test_no_producer_references_orphan_queue_names() -> None:
    """Regression lock against the Phase-10 bug returning.

    The original Phase-9 bug-shape was `task_default_queue="default"` paired
    with `-Q celery`. Plan 10-01 renamed both sides to `jaot_default`. This
    test locks in the post-Phase-10 vocabulary by asserting that neither the
    literal `"default"` nor the literal `"celery"` appears as a producer-side
    queue reference. If a future PR reintroduces either, this test fails red
    in CI and blames Phase 10.
    """
    producer_queues = _extract_producer_queues(celery_app.conf)

    forbidden_legacy_names = {"default", "celery"}
    forbidden_present = producer_queues & forbidden_legacy_names

    assert not forbidden_present, (
        f"producer-side config references legacy queue name(s) {sorted(forbidden_present)} — "
        f"Phase 10 renamed both to `jaot_default` (plan 10-01) precisely because the "
        f"`default` vs `celery` mismatch went undetected for ~37 days. Any reintroduction "
        f"is a Phase-10 regression. Producer queues: {sorted(producer_queues)}."
    )


@pytest.mark.integration
def test_producer_queue_names_carry_domain_prefix() -> None:
    """WR-04: pattern lock for queue-name convention.

    The Phase-9 bug-shape was "any generic queue name without a domain
    prefix that the producer references and the consumer does not." The
    literal-names test above only forbids `"default"` and `"celery"`; a
    future PR that picks a third generic name (e.g. `task_default_queue=
    "async"` or `"tasks"`) would reintroduce the exact same bug-shape and
    silently pass the literal-names lock.

    This test asserts every producer-side queue name carries one of the
    domain prefixes the codebase commits to:

    - ``jaot_`` for generic / cross-domain work (jaot_default).
    - ``solve_`` for solver-bound work (solve_scip, solve_highs, solve_hexaly).

    Keep the literal-names test as the explicit lock against the original
    bug; this one is the pattern lock against the bug-shape.
    """
    producer_queues = _extract_producer_queues(celery_app.conf)
    allowed_prefixes = ("jaot_", "solve_")

    unprefixed = {q for q in producer_queues if not q.startswith(allowed_prefixes)}
    assert not unprefixed, (
        f"producer-side queue names without a domain prefix: {sorted(unprefixed)}. "
        f"Phase 10 D-08 mandates that every queue name carries a domain prefix "
        f"({', '.join(allowed_prefixes)}) — generic names like 'default' or 'tasks' "
        f"reintroduce the Phase-9 bug-shape. Producer queues: {sorted(producer_queues)}."
    )
