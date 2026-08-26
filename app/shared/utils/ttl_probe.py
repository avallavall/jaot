"""One expensive probe, refreshed at most once per TTL per process.

Three modules had written this from scratch: the maintenance-mode flag on
``/health``, the Hexaly worker probe, and the monthly LLM spend. The skeleton
was the same in all three — a ``(stamp, value)`` tuple, a lock, a re-check
after acquiring it — and they disagreed on one decision that is invisible from
the outside: what a caller does when it finds a refresh already running.

That decision is ``on_contention`` here, and every caller has to name it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock
from typing import Generic, Literal, TypeVar

T = TypeVar("T")

OnContention = Literal["wait", "serve_stale", "refresh_anyway"]


class TTLProbe(Generic[T]):
    """A value the process re-reads at most once every ``ttl_seconds``.

    Args:
        ttl_seconds: How long a value stays fresh.
        on_contention: What a caller does when another thread is already
            refreshing.

            ``"wait"`` blocks on the lock and then finds the cache filled.
            Correct when the refresh is short and bounded, so waiting costs
            little and a stale answer buys nothing.

            ``"serve_stale"`` returns the last value instead, however old.
            Correct when the refresh can block for a long time — a database
            checkout against a saturated pool — and an old answer beats a slow
            one. Waiting would have produced that same old answer anyway, just
            later.

            ``"refresh_anyway"`` runs its own refresh alongside. No caller ever
            blocks and no caller ever gets a stale answer, at the price of N
            refreshes when N callers arrive together on an expired value.
            Correct when blocking is the thing you cannot afford — a
            synchronous call inside an ``async def`` handler holds the event
            loop, and every route in that worker stops with it — and the
            refresh is cheap enough that a few of them do no harm.
        first_wait_seconds: ``serve_stale`` only, and only for the very first
            call, where there is no stale value and the alternative is
            ``cold_value``. Waiting briefly for a real answer beats inventing
            one. 0 means never wait.
        cold_value: What ``serve_stale`` returns when it has nothing at all.

    Not a decorator and not keyed: one instance holds one value. A cache keyed
    by argument is a different thing and does not belong here.
    """

    __slots__ = ("_cached", "_cold", "_first_wait", "_lock", "_on_contention", "_ttl")

    def __init__(
        self,
        *,
        ttl_seconds: float,
        on_contention: OnContention,
        first_wait_seconds: float = 0.0,
        cold_value: T = None,  # type: ignore[assignment]
    ) -> None:
        if on_contention not in ("wait", "serve_stale", "refresh_anyway"):
            raise ValueError(f"unknown on_contention: {on_contention!r}")
        if on_contention == "serve_stale" and cold_value is None:
            # The whole point of serve_stale is answering without waiting, and
            # on the first call there is nothing to answer with. Returning None
            # from a probe declared as returning T is how a caller ends up
            # reading "no budget" or "not in maintenance" as a fact.
            raise ValueError("serve_stale needs a cold_value to answer with before the first read")
        self._ttl = ttl_seconds
        self._on_contention: OnContention = on_contention
        self._first_wait = first_wait_seconds
        self._cold: T = cold_value
        self._cached: tuple[float, T] | None = None
        self._lock = Lock()

    @property
    def last_known(self) -> T | None:
        """The last value read, however stale. None if there has never been one.

        A refresh function uses this to fall back on its own failure: writing
        the old value back keeps the TTL alive, so the next caller does not
        immediately pay for another failed attempt.
        """
        cached = self._cached
        return cached[1] if cached is not None else None

    def clear(self) -> None:
        """Forget the value entirely, so the next call refreshes from cold."""
        self._cached = None

    def expire(self) -> None:
        """Mark the value stale without forgetting it.

        The next call refreshes, and a refresh that fails can still fall back
        on ``last_known``. ``clear`` throws that fallback away too.
        """
        cached = self._cached
        if cached is not None:
            self._cached = (float("-inf"), cached[1])

    def _fresh(self) -> tuple[bool, T | None]:
        """(hit, value). The flag is separate because ``value`` may be None."""
        cached = self._cached
        if cached is not None and (time.monotonic() - cached[0]) < self._ttl:
            return True, cached[1]
        return False, None

    def _stale(self) -> T:
        """The last value, or ``cold_value``. Only ``serve_stale`` reaches this,
        and its constructor refuses to build without a ``cold_value``."""
        cached = self._cached
        return cached[1] if cached is not None else self._cold

    def get(self, refresh: Callable[[], T]) -> T:
        """The cached value, calling ``refresh`` when it has expired.

        ``refresh`` must not raise: an infrastructure probe that raises here
        would reach the caller as an unhandled error. Catch inside it and
        return ``last_known`` when there is nothing better.
        """
        hit, value = self._fresh()
        if hit:
            return value  # type: ignore[return-value]

        # The fast path above reads the tuple without the lock. Binding a name
        # is atomic under the GIL, so the worst case is reading a value that
        # expired a moment ago, which the next call refreshes.
        if self._on_contention == "refresh_anyway":
            value = refresh()
            self._cached = (time.monotonic(), value)
            return value

        if self._on_contention == "wait":
            acquired = self._lock.acquire()
        elif self._cached is None and self._first_wait > 0:
            acquired = self._lock.acquire(timeout=self._first_wait)
        else:
            acquired = self._lock.acquire(blocking=False)

        if not acquired:
            return self._stale()

        try:
            # Re-check: another thread may have refreshed while this one waited.
            hit, value = self._fresh()
            if hit:
                return value  # type: ignore[return-value]

            value = refresh()
            self._cached = (time.monotonic(), value)
            return value
        finally:
            self._lock.release()
