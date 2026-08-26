"""Unit tests for /health MAINTENANCE_MODE TTL cache — Phase 7.1 Plan 01.

Covers D-7.1-13 / E-13:
    Test D: Cache hit reuses PSS result — PSS.get_bool called exactly 1 time
            when helper is called 10 times within the TTL window.
    Test E: Cache TTL expiry refreshes — after advancing monotonic time past TTL,
            a new call increments PSS.get_bool counter to 2.
    Test F: Single-flight lock, no stampede — 10 threads racing through
            _probe_maintenance_mode() with empty cache; PSS.get_bool called
            exactly 1 time.
    Test G: Session hygiene (D-25) — a cache hit opens no session at all, and a
            refresh closes the one it opens.
    Test H: Stale-if-error (D-25) — when the pool cannot hand out a connection,
            the probe serves the last known value instead of raising.

D-25 changed the contract: the helper opens (and closes) its own short-lived
session instead of receiving one from ``Depends(get_db)``, so that a health
check stops checking out a pooled connection on every call. The TTL, expiry and
single-flight invariants below are unchanged — only who owns the session moved.
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError


def _make_pss_counter():
    """Return a (mock_fn, counter_list) pair.

    counter[0] increments on each call. Returns False always.
    """
    counter = [0]

    def _impl(db, key, default=False):
        counter[0] += 1
        return False

    return _impl, counter


@pytest.fixture(autouse=True)
def _reset_maintenance_probe():
    """Forget the cached flag before AND after every test in this module.

    The probe is a process global with a 10 s TTL. Clearing only on the way in
    let the last test here leave `True` behind: `monkeypatch` undoes the PSS
    patch at teardown, but it cannot undo a value already written into the
    cache, and the next test in the same process that calls GET /health inside
    that window reads `maintenance: true`. Under pytest-randomly that is a
    different test every run.
    """
    import app.api.v2.health as health_mod

    health_mod._maintenance_probe.clear()
    yield
    health_mod._maintenance_probe.clear()


def _reset_cache():
    """Kept so the explicit call in each test still reads as a reset."""
    import app.api.v2.health as health_mod

    health_mod._maintenance_probe.clear()


# Test D: Cache hit reuses PSS result


def test_cache_hit_reuses_pss_result(monkeypatch) -> None:
    """Test D: 10 back-to-back calls → PSS.get_bool invoked exactly 1 time."""
    _reset_cache()

    pss_impl, counter = _make_pss_counter()

    monkeypatch.setattr(
        "app.services.platform_settings_service.PlatformSettingsService.get_bool",
        pss_impl,
    )

    from app.api.v2.health import _probe_maintenance_mode

    for _ in range(10):
        result = _probe_maintenance_mode()
        assert result is False

    assert counter[0] == 1, (
        f"PSS.get_bool should be called exactly 1 time due to TTL cache, "
        f"but was called {counter[0]} times"
    )


# Test E: Cache TTL expiry refreshes


def test_cache_ttl_expiry_refreshes(monkeypatch) -> None:
    """Test E: After TTL expiry, next call re-invokes PSS.get_bool (count → 2)."""
    _reset_cache()

    pss_impl, counter = _make_pss_counter()

    monkeypatch.setattr(
        "app.services.platform_settings_service.PlatformSettingsService.get_bool",
        pss_impl,
    )

    from app.api.v2.health import _probe_maintenance_mode

    # First call — populates cache (count=1)
    _probe_maintenance_mode()
    assert counter[0] == 1

    # Age the entry past its TTL, keeping the value it holds.
    import app.api.v2.health as health_mod

    assert health_mod._maintenance_probe.last_known is not None
    health_mod._maintenance_probe.expire()

    # Second call — cache is stale, should re-invoke PSS.get_bool (count=2)
    _probe_maintenance_mode()
    assert counter[0] == 2, (
        f"PSS.get_bool should be called a second time after TTL expiry, "
        f"but call count is {counter[0]}"
    )


# Test F: Single-flight lock — no stampede under 10 concurrent threads


def test_single_flight_lock_no_stampede(monkeypatch) -> None:
    """Test F: 10 threads race with empty cache; PSS.get_bool called exactly 1 time."""
    _reset_cache()

    pss_impl, counter = _make_pss_counter()

    # Add a short sleep inside PSS mock to maximise race-condition surface.
    call_lock = threading.Lock()

    def _slow_pss(db, key, default=False):
        time.sleep(0.02)  # 20ms — enough for other threads to arrive at the lock
        with call_lock:
            counter[0] += 1
        return False

    monkeypatch.setattr(
        "app.services.platform_settings_service.PlatformSettingsService.get_bool",
        _slow_pss,
    )

    from app.api.v2.health import _probe_maintenance_mode

    results: list[bool] = []
    errors: list[Exception] = []

    def _thread_fn():
        try:
            val = _probe_maintenance_mode()
            results.append(val)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_thread_fn) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert not errors, f"Thread errors: {errors}"
    assert len(results) == 10, f"Expected 10 results, got {len(results)}"
    assert all(r is False for r in results)
    assert counter[0] == 1, (
        f"Single-flight lock should allow PSS.get_bool exactly 1 time "
        f"under 10-thread race, but was called {counter[0]} times"
    )


# Test G: session hygiene — a cache hit must not touch the pool at all


def test_cache_hit_opens_no_session(monkeypatch) -> None:
    """# CONTRACT-TEST: a cached maintenance read checks out no DB connection.

    This is the whole point of D-25. ``Depends(get_db)`` acquired a pooled
    connection before the handler ran, so every health check queued for one even
    though the TTL cache answers ~9 out of 10 of them from memory. If this ever
    regresses, the health check starts competing with real traffic for the pool
    again — and under saturation that is what turns a slow API into a restarting
    container.
    """
    _reset_cache()

    pss_impl, _ = _make_pss_counter()
    monkeypatch.setattr(
        "app.services.platform_settings_service.PlatformSettingsService.get_bool",
        pss_impl,
    )

    sessions_opened = [0]
    sessions_closed = [0]

    import app.shared.db.session as session_mod

    real_session_factory = session_mod.SessionLocal

    def _counting_session_factory(*args, **kwargs):
        sessions_opened[0] += 1
        session = real_session_factory(*args, **kwargs)
        real_close = session.close

        def _counting_close():
            sessions_closed[0] += 1
            return real_close()

        session.close = _counting_close
        return session

    monkeypatch.setattr(session_mod, "SessionLocal", _counting_session_factory)

    from app.api.v2.health import _probe_maintenance_mode

    # First call is the refresh: exactly one session, and it must be returned.
    _probe_maintenance_mode()
    assert sessions_opened[0] == 1, "the refresh should open exactly one session"
    assert sessions_closed[0] == 1, "the refresh leaked its session back to the pool"

    # Every subsequent call inside the TTL window must open none.
    for _ in range(10):
        _probe_maintenance_mode()

    assert sessions_opened[0] == 1, (
        f"cached maintenance reads opened {sessions_opened[0]} sessions instead of 1; "
        "the health check is checking out pooled connections it does not need"
    )


# Test H: stale-if-error — an exhausted pool must not break the health check


def test_exhausted_pool_serves_last_known_value(monkeypatch) -> None:
    """# CONTRACT-TEST: pool exhaustion degrades to the cached value, never raises.

    An exhausted pool is precisely when the health endpoint most needs to
    answer: if it raises here, the container health check fails and Docker
    restarts a process whose only problem was load.
    """
    _reset_cache()

    # Prime the cache with a known True so we can tell "stale value" apart from
    # "default False".
    def _pss_true(db, key, default=False):
        return True

    monkeypatch.setattr(
        "app.services.platform_settings_service.PlatformSettingsService.get_bool",
        _pss_true,
    )

    from app.api.v2.health import _probe_maintenance_mode

    assert _probe_maintenance_mode() is True

    # Expire the cache, then make the pool refuse to hand out a connection.
    import app.api.v2.health as health_mod
    import app.shared.db.session as session_mod

    assert health_mod._maintenance_probe.last_known is True
    health_mod._maintenance_probe.expire()

    def _exhausted(*args, **kwargs):
        raise SQLAlchemyTimeoutError("QueuePool limit of size 5 overflow 5 reached")

    monkeypatch.setattr(session_mod, "SessionLocal", _exhausted)

    assert _probe_maintenance_mode() is True, (
        "with the pool exhausted the probe must serve the last known value, "
        "not raise and not silently flip maintenance off"
    )


def test_exhausted_pool_with_cold_cache_defaults_to_off(monkeypatch) -> None:
    """With no value ever read, an exhausted pool reports maintenance off.

    False is the safe default: reporting maintenance ON would take a healthy
    site down over a transient pool blip.
    """
    _reset_cache()

    import app.shared.db.session as session_mod

    def _exhausted(*args, **kwargs):
        raise SQLAlchemyTimeoutError("QueuePool limit of size 5 overflow 5 reached")

    monkeypatch.setattr(session_mod, "SessionLocal", _exhausted)

    from app.api.v2.health import _probe_maintenance_mode

    assert _probe_maintenance_mode() is False


# CONTRACT-TEST: a cold-start race must not report maintenance OFF while it is ON.


def test_cold_start_race_reports_maintenance_on(monkeypatch) -> None:
    """Every caller in the first race gets the true value, not the safe default.

    The single flight is non-blocking, so a caller that finds the refresh already
    running serves the last known value — which, before anything has ever been
    read, is a hard-coded False. A container starting inside a maintenance window
    sees a liveness probe, a metrics scrape and a user request arrive together:
    one won the lock, the others answered `maintenance_mode: false` while it was
    on. With no stale value to fall back on, they now wait for the real one.
    """
    _reset_cache()

    call_lock = threading.Lock()
    calls = [0]

    def _slow_pss_on(db, key, default=False):
        time.sleep(0.05)  # hold the lock long enough for the others to pile up
        with call_lock:
            calls[0] += 1
        return True

    monkeypatch.setattr(
        "app.services.platform_settings_service.PlatformSettingsService.get_bool",
        _slow_pss_on,
    )

    from app.api.v2.health import _probe_maintenance_mode

    results: list[bool] = []

    def _thread_fn():
        results.append(_probe_maintenance_mode())

    threads = [threading.Thread(target=_thread_fn) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(results) == 5
    assert all(r is True for r in results), (
        f"maintenance is ON, yet the cold-start race answered {results} — "
        "the losers served the hard-coded False"
    )
    assert calls[0] == 1, "single flight still holds: one read for the whole race"
