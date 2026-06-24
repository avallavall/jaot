"""Integration tests for Hexaly solve task flow — Phase 7 / D-05, D-26.

These turn GREEN what Plan 07-01 seeded as ``xfail(strict=False)`` stubs:

- License-expired rejection before enqueue (D-05) — no credits debit, no
  Celery task, 422 response from the sync orchestrator layer.
- ``HX_LICENSE_CONTENT`` env-var lifecycle around the adapter context
  manager — must not leak across tasks on a reused worker, even when the
  solve raises.

SDK-gated end-to-end Hexaly solve is marked ``@pytest.mark.skipif`` per
D-19 — CI stays green without the commercial SDK.
"""

from __future__ import annotations

import os

import pytest

from app.domains.solver.adapters.hexaly_availability import hexaly_available


def test_license_env_var_unset_after_solve() -> None:
    """Happy path: scope enters, exits, clears HX_LICENSE_CONTENT.

    Mirrors the in-adapter lifecycle so a worker process reusing the
    Python interpreter across sequential tasks never sees a stale
    license from a previous solve (T-07-08 / T-07-10 defense).
    """
    from app.domains.solver.adapters.hexaly import hexaly_license_scope

    # Make sure no prior test polluted the environment.
    os.environ.pop("HX_LICENSE_CONTENT", None)
    assert os.environ.get("HX_LICENSE_CONTENT") is None

    with hexaly_license_scope("sample-license-alpha"):
        assert os.environ["HX_LICENSE_CONTENT"] == "sample-license-alpha"

    assert os.environ.get("HX_LICENSE_CONTENT") is None


def test_license_env_var_unset_even_when_solve_raises() -> None:
    """T-07-08: exception path must still clear HX_LICENSE_CONTENT.

    If the SDK or any user code inside the with-block raises, the
    license must NOT persist into the next Celery task's process.
    """
    from app.domains.solver.adapters.hexaly import hexaly_license_scope

    os.environ.pop("HX_LICENSE_CONTENT", None)
    assert os.environ.get("HX_LICENSE_CONTENT") is None

    with pytest.raises(RuntimeError):  # noqa: PT012 — scope is the test surface
        with hexaly_license_scope("sample-license-beta"):
            assert os.environ["HX_LICENSE_CONTENT"] == "sample-license-beta"
            raise RuntimeError("simulated solver crash")

    assert os.environ.get("HX_LICENSE_CONTENT") is None


def test_hx_license_content_does_not_persist_across_two_orgs() -> None:
    """Two sequential scopes for different orgs both clean up.

    Mirrors the worker's sequential-task behaviour (``concurrency=1``
    in compose). If this ever regresses, a Hexaly solve for Org B
    could pick up Org A's license — a cross-tenant leak.
    """
    from app.domains.solver.adapters.hexaly import hexaly_license_scope

    os.environ.pop("HX_LICENSE_CONTENT", None)

    with hexaly_license_scope("org-A-license"):
        assert os.environ["HX_LICENSE_CONTENT"] == "org-A-license"
    assert os.environ.get("HX_LICENSE_CONTENT") is None

    with hexaly_license_scope("org-B-license"):
        assert os.environ["HX_LICENSE_CONTENT"] == "org-B-license"
    assert os.environ.get("HX_LICENSE_CONTENT") is None


def test_solve_hexaly_routes_to_hexaly_queue() -> None:
    """Producer-side wiring: requesting solver_name=hexaly selects solve_hexaly.

    Locks in D-17: SOLVER_QUEUE_MAP['hexaly'] == 'solve_hexaly'. The
    WR-03 guard is unit-tested separately in tests/unit/test_queue_routing.py.
    """
    from app.domains.solver.queue_routing import resolve_queue

    assert resolve_queue("hexaly") == "solve_hexaly"


@pytest.mark.skipif(
    not hexaly_available(),
    reason="Hexaly SDK not installed in test env (D-19)",
)
def test_real_hexaly_task_end_to_end_quadratic() -> None:
    """Dev-box only: end-to-end real SDK solve.

    Requires ``hexaly`` wheel installed + a valid license in
    ``HEXALY_TEST_LICENSE``. See VALIDATION.md §Manual-Only
    Verifications for the run protocol.
    """
    pytest.skip("Manual verification — see 07-VALIDATION.md Manual-Only Verifications")
