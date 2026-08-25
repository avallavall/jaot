"""The shared TTL probe, and the one decision it makes callers name.

Three modules had written this from scratch and disagreed on what a caller does
while a refresh is running. That difference was invisible from the outside,
which is what made it debt (D-29). These tests pin both answers.
"""

from __future__ import annotations

import threading
import time

from app.shared.utils.ttl_probe import TTLProbe


def _counter():
    """A refresh function that counts its calls and returns the count."""
    calls = [0]

    def _refresh() -> int:
        calls[0] += 1
        return calls[0]

    return _refresh, calls


def test_a_fresh_value_is_served_without_calling_refresh() -> None:
    probe = TTLProbe[int](ttl_seconds=60.0, on_contention="wait")
    refresh, calls = _counter()

    for _ in range(10):
        assert probe.get(refresh) == 1

    assert calls[0] == 1, f"refresh ran {calls[0]} times inside one TTL window"


def test_an_expired_value_is_refreshed() -> None:
    probe = TTLProbe[int](ttl_seconds=60.0, on_contention="wait")
    refresh, _ = _counter()

    assert probe.get(refresh) == 1
    probe.expire()
    assert probe.get(refresh) == 2


def test_a_zero_ttl_refreshes_every_time() -> None:
    probe = TTLProbe[int](ttl_seconds=0.0, on_contention="wait")
    refresh, _ = _counter()

    assert probe.get(refresh) == 1
    assert probe.get(refresh) == 2


def test_expire_keeps_the_value_and_clear_forgets_it() -> None:
    probe = TTLProbe[int](ttl_seconds=60.0, on_contention="wait")
    probe.get(lambda: 7)

    probe.expire()
    assert probe.last_known == 7, "expire threw the fallback away"

    probe.clear()
    assert probe.last_known is None


def test_a_value_of_none_still_counts_as_cached() -> None:
    """A refresh that legitimately answers None must not look like a miss."""
    probe = TTLProbe[int | None](ttl_seconds=60.0, on_contention="wait")
    refresh, calls = _counter()

    assert probe.get(lambda: None) is None
    assert probe.get(refresh) is None, "the cached None was treated as an empty cache"
    assert calls[0] == 0


# ---- the decision the three copies disagreed on ----


def _racing_refresh(hold_seconds: float):
    """A slow refresh that records how many threads entered it."""
    entered = [0]
    lock = threading.Lock()

    def _refresh() -> int:
        with lock:
            entered[0] += 1
        time.sleep(hold_seconds)
        return entered[0]

    return _refresh, entered


def test_wait_lets_exactly_one_thread_refresh() -> None:
    probe = TTLProbe[int](ttl_seconds=60.0, on_contention="wait")
    refresh, entered = _racing_refresh(0.05)
    results: list[int] = []
    barrier = threading.Barrier(8)

    def _worker() -> None:
        barrier.wait()
        results.append(probe.get(refresh))

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert entered[0] == 1, f"{entered[0]} threads ran the refresh; the single flight leaked"
    assert results == [1] * 8, "a waiting caller got something other than the refreshed value"


def test_serve_stale_lets_losers_through_with_the_old_value() -> None:
    """A loser returns immediately with the stale value instead of blocking."""
    probe = TTLProbe[str](ttl_seconds=60.0, on_contention="serve_stale", cold_value="cold")
    probe.get(lambda: "old")
    probe.expire()

    started = threading.Event()
    release = threading.Event()

    def _slow() -> str:
        started.set()
        release.wait(timeout=5.0)
        return "new"

    winner_result: list[str] = []
    winner = threading.Thread(target=lambda: winner_result.append(probe.get(_slow)))
    winner.start()
    assert started.wait(timeout=5.0), "the refresh never started"

    # The loser must not block behind the refresh.
    assert probe.get(lambda: "should never run") == "old"

    release.set()
    winner.join(timeout=5.0)
    assert winner_result == ["new"]


def test_serve_stale_with_nothing_cached_returns_the_cold_value() -> None:
    """No first wait configured: a loser on a cold cache gets cold_value."""
    probe = TTLProbe[bool](
        ttl_seconds=60.0,
        on_contention="serve_stale",
        first_wait_seconds=0.0,
        cold_value=False,
    )

    started = threading.Event()
    release = threading.Event()

    def _slow() -> bool:
        started.set()
        release.wait(timeout=5.0)
        return True

    winner = threading.Thread(target=lambda: probe.get(_slow))
    winner.start()
    assert started.wait(timeout=5.0)

    assert probe.get(lambda: True) is False, "a cold loser invented something other than cold_value"

    release.set()
    winner.join(timeout=5.0)


def test_a_first_wait_holds_the_cold_loser_until_there_is_a_real_answer() -> None:
    """The cold-start race: nobody may report the cold value while a probe is running.

    This is the case health.py cares about — a container starting inside a
    maintenance window must not answer "maintenance off" to the requests that
    arrive alongside the first probe.
    """
    probe = TTLProbe[bool](
        ttl_seconds=60.0,
        on_contention="serve_stale",
        first_wait_seconds=2.0,
        cold_value=False,
    )

    started = threading.Event()

    def _slow() -> bool:
        started.set()
        time.sleep(0.1)
        return True

    results: list[bool] = []
    winner = threading.Thread(target=lambda: results.append(probe.get(_slow)))
    winner.start()
    assert started.wait(timeout=5.0)

    results.append(probe.get(lambda: True))
    winner.join(timeout=5.0)

    assert results == [True, True], f"a caller reported the cold default: {results}"
