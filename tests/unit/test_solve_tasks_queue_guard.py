"""Unit tests for _assert_queue_match (Phase 6 INF-01 / D-05, D-06, D-07).

Wave 3 RED — these tests will FAIL until the helper is added to
app/domains/solver/tasks/solve_tasks.py in task 2 of plan 06-03.

Covers the consumer-side runtime guard — the second barrier of
defense-in-depth against routing misconfiguration. The producer-side
``apply_async(queue=resolve_queue(solver_name))`` is already in place
(plan 06-02); this layer protects against manual queue pokes, misrouted
messages, and misconfigured workers.

Security:
- Error messages MUST NOT leak broker URIs, filesystem paths, env var
  values other than the already-public queue names (from SOLVER_QUEUE_MAP).
"""

import pytest


@pytest.mark.unit
def test_assert_queue_match_no_env_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SOLVER_QUEUE env is unset, the guard is a no-op.

    Dev, tests, and the legacy monolithic worker run without SOLVER_QUEUE
    set. The guard must not raise in those environments — the producer
    remains the only source of truth for routing.
    """
    monkeypatch.delenv("SOLVER_QUEUE", raising=False)

    from app.domains.solver.tasks.solve_tasks import _assert_queue_match

    # None, "scip", "highs", and "gurobi" all must be no-ops when env is unset.
    assert _assert_queue_match(None) is None
    assert _assert_queue_match("scip") is None
    assert _assert_queue_match("highs") is None
    assert _assert_queue_match("gurobi") is None  # Guard is permissive without env.


@pytest.mark.unit
def test_assert_queue_match_matching_queue_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """SOLVER_QUEUE=solve_scip + solver_name='scip' -> no raise, returns None."""
    monkeypatch.setenv("SOLVER_QUEUE", "solve_scip")

    from app.domains.solver.tasks.solve_tasks import _assert_queue_match

    assert _assert_queue_match("scip") is None
    # D-02: None defaults to scip, so still matches solve_scip.
    assert _assert_queue_match(None) is None


@pytest.mark.unit
def test_assert_queue_match_matching_queue_highs(monkeypatch: pytest.MonkeyPatch) -> None:
    """SOLVER_QUEUE=solve_highs + solver_name='highs' -> no raise, returns None."""
    monkeypatch.setenv("SOLVER_QUEUE", "solve_highs")

    from app.domains.solver.tasks.solve_tasks import _assert_queue_match

    assert _assert_queue_match("highs") is None


@pytest.mark.unit
def test_assert_queue_match_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SOLVER_QUEUE=solve_scip + solver_name='highs' -> SolverQueueMismatchError.

    This is the core defense-in-depth assertion (D-05/D-06/D-07):
    a HiGHS task must never be processed on the SCIP worker even if
    somehow it lands on solve_scip (manual poke, routing bug, etc).

    Security: error message contains BOTH solver names but NO broker
    URI, NO filesystem path, NO env var values beyond the public queue
    names (already exposed via SOLVER_QUEUE_MAP).
    """
    monkeypatch.setenv("SOLVER_QUEUE", "solve_scip")

    from app.domains.solver.adapters.base import SolverQueueMismatchError
    from app.domains.solver.tasks.solve_tasks import _assert_queue_match

    with pytest.raises(SolverQueueMismatchError) as exc_info:
        _assert_queue_match("highs")

    message = str(exc_info.value)
    assert "solve_scip" in message
    assert "highs" in message
    # No broker / filesystem / env-value leaks.
    assert "amqp://" not in message
    assert "redis://" not in message
    assert "/app/" not in message
    assert "CELERY_BROKER" not in message
    assert "SOLVER_QUEUE=" not in message


@pytest.mark.unit
def test_assert_queue_match_unknown_solver_name_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """SOLVER_QUEUE=solve_scip + solver_name='gurobi' -> SolverQueueMismatchError.

    The guard wraps the whitelist rejection from resolve_queue() into
    a SolverQueueMismatchError so the task's outer try/except treats it
    uniformly (single exception type for routing failures).

    Security: message does not leak broker config.
    """
    monkeypatch.setenv("SOLVER_QUEUE", "solve_scip")

    from app.domains.solver.adapters.base import SolverQueueMismatchError
    from app.domains.solver.tasks.solve_tasks import _assert_queue_match

    with pytest.raises(SolverQueueMismatchError) as exc_info:
        _assert_queue_match("gurobi")

    message = str(exc_info.value)
    assert "gurobi" in message
    assert "solve_scip" in message
    assert "amqp://" not in message
    assert "redis://" not in message
    assert "CELERY_BROKER" not in message
