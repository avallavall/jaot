"""Admission control must not exceed what the DB pool can serve (D-25).

Measured 2026-08-01: production runs four worker processes, each with a pool of
``DB_POOL_SIZE=5`` + ``DB_MAX_OVERFLOW=5`` = 10 connections, against an AnyIO
threadpool left at its default of 40 tokens — a 4:1 ratio. Endpoints are
synchronous by design (ADR-009) and hold their connection for the whole request,
so the surplus could not fail fast: request 11 waited out ``pool_timeout``
(unset, so SQLAlchemy's 30s default) and then 500'd, having occupied a thread
the entire time. Workers are independent, so one hot worker failed while the
other three idled.

These tests pin both halves of the fix: a short, explicit pool timeout, and a
threadpool sized from the pool rather than from AnyIO's default.
"""

from __future__ import annotations

import anyio
import pytest

from app.config import settings
from app.main import _configure_threadpool


class TestPoolTimeout:
    """# CONTRACT-TEST: waiting for a connection fails fast, not after 30s."""

    def test_engine_uses_the_configured_timeout(self) -> None:
        """Built from ``build_engine`` rather than the module-level ``engine``.

        The test harness replaces ``app.shared.db.session.engine`` with its own
        (bigger pool, no timeout), so asserting on that global would be
        asserting on the harness, not on how production is configured.
        """
        from app.shared.db.session import build_engine

        assert build_engine().pool._timeout == settings.DB_POOL_TIMEOUT

    def test_timeout_is_not_the_sqlalchemy_default(self) -> None:
        """Regression lock: 30s unset was what turned saturation into 500s."""
        from app.shared.db.session import build_engine

        assert build_engine().pool._timeout != 30

    def test_timeout_is_far_below_the_container_health_grace(self) -> None:
        """The health probe allows 10s per attempt; a pool wait must fit inside it.

        With the old 30s default, a saturated pool blew through Docker's
        timeout, the container was marked unhealthy and restarted, and its load
        landed on the remaining workers — a slow API becoming a restarting one.
        """
        assert 0 < settings.DB_POOL_TIMEOUT <= 10


class TestThreadpoolSizing:
    """# CONTRACT-TEST: concurrent requests never outnumber usable connections."""

    async def _tokens_after_configure(self) -> float:
        _configure_threadpool()
        return anyio.to_thread.current_default_thread_limiter().total_tokens

    def test_defaults_to_pool_capacity(self, monkeypatch) -> None:
        """With no explicit override, tokens == pool_size + max_overflow."""
        monkeypatch.setattr(settings, "API_THREADPOOL_TOKENS", 0)
        monkeypatch.setattr(settings, "DB_POOL_SIZE", 5)
        monkeypatch.setattr(settings, "DB_MAX_OVERFLOW", 5)

        tokens = anyio.run(self._tokens_after_configure)

        assert tokens == 10, (
            f"threadpool sized to {tokens} against a pool capacity of 10; "
            "admitting more concurrent requests than connections is exactly "
            "the 4:1 ratio D-25 exists to remove"
        )

    def test_explicit_override_wins(self, monkeypatch) -> None:
        """An operator who knows their traffic can raise it above the pool."""
        monkeypatch.setattr(settings, "API_THREADPOOL_TOKENS", 24)
        monkeypatch.setattr(settings, "DB_POOL_SIZE", 5)
        monkeypatch.setattr(settings, "DB_MAX_OVERFLOW", 5)

        assert anyio.run(self._tokens_after_configure) == 24

    def test_is_not_anyio_default(self, monkeypatch) -> None:
        """Regression lock: 40 is the untuned default that caused the incident."""
        monkeypatch.setattr(settings, "API_THREADPOOL_TOKENS", 0)
        monkeypatch.setattr(settings, "DB_POOL_SIZE", 5)
        monkeypatch.setattr(settings, "DB_MAX_OVERFLOW", 5)

        assert anyio.run(self._tokens_after_configure) != 40

    @pytest.mark.parametrize("bad_capacity", [(0, 0), (-5, 0)])
    def test_nonsense_capacity_leaves_the_default_alone(self, monkeypatch, bad_capacity) -> None:
        """A misconfigured pool must not set the limiter to zero and wedge the app."""
        pool_size, overflow = bad_capacity
        monkeypatch.setattr(settings, "API_THREADPOOL_TOKENS", 0)
        monkeypatch.setattr(settings, "DB_POOL_SIZE", pool_size)
        monkeypatch.setattr(settings, "DB_MAX_OVERFLOW", overflow)

        tokens = anyio.run(self._tokens_after_configure)

        assert tokens > 0, "a zero-token limiter would deadlock every request"

    def test_never_raises_when_the_limiter_is_unavailable(self, monkeypatch) -> None:
        """Failing to tune the limiter degrades to the default; it must not stop boot."""
        import anyio.to_thread as to_thread_mod

        def _explode():
            raise RuntimeError("no running event loop")

        monkeypatch.setattr(to_thread_mod, "current_default_thread_limiter", _explode)

        # Must not raise.
        _configure_threadpool()
