"""SDK-import probe for Hexaly (Phase 7 / D-19).

Used as skip-guard in tests that exercise the real Hexaly SDK:

    @pytest.mark.skipif(not hexaly_available(), reason="Hexaly SDK not installed")

Kept in a standalone module (not inside ``hexaly.py``) so the
skip guard is usable from tests that never import the adapter
itself — the adapter module imports the hexaly SDK eagerly in its
``solve()`` path and would itself raise ImportError in minimal
environments.
"""

from __future__ import annotations

_cache: bool | None = None


def hexaly_available() -> bool:
    """Return True when ``hexaly.optimizer`` is importable.

    Cached per-process: the import check is not free and the answer
    cannot change within a single worker lifetime. Tests that toggle
    ``sys.modules['hexaly.optimizer']`` must call
    :func:`_reset_cache_for_tests` to force a re-probe.
    """
    global _cache
    if _cache is None:
        try:
            import hexaly.optimizer  # noqa: F401, PLC0415

            _cache = True
        except ImportError:
            _cache = False
    return _cache


def _reset_cache_for_tests() -> None:
    """Clear the module-level availability cache. Test-only hook."""
    global _cache
    _cache = None
