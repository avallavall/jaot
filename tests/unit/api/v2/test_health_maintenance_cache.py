"""Unit tests for /health MAINTENANCE_MODE TTL cache — Phase 7.1 Plan 01.

Covers D-7.1-13 / E-13:
    Test D: Cache hit reuses PSS result — PSS.get_bool called exactly 1 time
            when helper is called 10 times within the TTL window.
    Test E: Cache TTL expiry refreshes — after advancing monotonic time past TTL,
            a new call increments PSS.get_bool counter to 2.
    Test F: Single-flight lock, no stampede — 10 threads racing through
            _probe_maintenance_mode() with empty cache; PSS.get_bool called
            exactly 1 time.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock


def _make_pss_counter():
    """Return a (mock_fn, counter_list) pair.

    counter[0] increments on each call. Returns False always.
    """
    counter = [0]

    def _impl(db, key, default=False):
        counter[0] += 1
        return False

    return _impl, counter


def _reset_cache():
    """Reset the module-level cache to None before each test."""
    import app.api.v2.health as health_mod

    health_mod._maintenance_probe_cache = None


# Test D: Cache hit reuses PSS result


def test_cache_hit_reuses_pss_result(monkeypatch) -> None:
    """Test D: 10 back-to-back calls → PSS.get_bool invoked exactly 1 time."""
    _reset_cache()

    pss_impl, counter = _make_pss_counter()
    fake_db = MagicMock()

    monkeypatch.setattr(
        "app.services.platform_settings_service.PlatformSettingsService.get_bool",
        pss_impl,
    )

    from app.api.v2.health import _probe_maintenance_mode

    for _ in range(10):
        result = _probe_maintenance_mode(fake_db)
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
    fake_db = MagicMock()

    monkeypatch.setattr(
        "app.services.platform_settings_service.PlatformSettingsService.get_bool",
        pss_impl,
    )

    from app.api.v2.health import _MAINTENANCE_PROBE_CACHE_SECONDS, _probe_maintenance_mode

    # First call — populates cache (count=1)
    _probe_maintenance_mode(fake_db)
    assert counter[0] == 1

    # Advance monotonic time past TTL to simulate expiry.
    # We patch time.monotonic to return a value > (now + TTL).
    import app.api.v2.health as health_mod

    original_cache = health_mod._maintenance_probe_cache
    assert original_cache is not None
    stale_ts = original_cache[0] - (_MAINTENANCE_PROBE_CACHE_SECONDS + 1.0)

    # Inject a cache entry with a stale timestamp
    health_mod._maintenance_probe_cache = (stale_ts, False)

    # Second call — cache is stale, should re-invoke PSS.get_bool (count=2)
    _probe_maintenance_mode(fake_db)
    assert counter[0] == 2, (
        f"PSS.get_bool should be called a second time after TTL expiry, "
        f"but call count is {counter[0]}"
    )


# Test F: Single-flight lock — no stampede under 10 concurrent threads


def test_single_flight_lock_no_stampede(monkeypatch) -> None:
    """Test F: 10 threads race with empty cache; PSS.get_bool called exactly 1 time."""
    _reset_cache()

    pss_impl, counter = _make_pss_counter()
    fake_db = MagicMock()

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
            val = _probe_maintenance_mode(fake_db)
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
