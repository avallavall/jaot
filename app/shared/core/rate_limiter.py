"""Redis-backed rate limiter with in-memory fallback.

Uses sorted sets for a sliding window approach when Redis is available.
Falls back to an in-memory implementation when Redis is unavailable
(e.g., local development without Redis, or connection failures).
"""

import logging
import os
import sys
import time
import uuid
from collections import defaultdict
from typing import Any

try:
    from redis.exceptions import RedisError
except ImportError:
    # redis not installed — define a placeholder so except clauses compile
    RedisError = type("RedisError", (Exception,), {})

logger = logging.getLogger(__name__)

_redis_client = None
_fallback_mode = False


def init_redis(redis_url: str) -> bool:
    """Initialize Redis connection for rate limiting.

    Args:
        redis_url: Redis connection URL (e.g. redis://localhost:6379/0).
                   Empty string disables Redis and uses in-memory fallback.

    Returns:
        True if Redis connection succeeded, False otherwise.
    """
    global _redis_client, _fallback_mode
    if not redis_url:
        logger.warning("REDIS_URL not set — rate limiter using in-memory fallback")
        _fallback_mode = True
        return False
    try:
        import redis as redis_lib

        _redis_client = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=2)
        _redis_client.ping()
        _fallback_mode = False
        logger.info("Rate limiter connected to Redis")
        return True
    except (RedisError, ConnectionError, OSError, ImportError) as e:
        logger.warning(f"Redis connection failed — falling back to in-memory: {e}")
        _fallback_mode = True
        _redis_client = None
        return False


_memory_store: dict[str, list[float]] = defaultdict(list)


def _check_memory(
    key: str,
    limit_per_minute: int,
    limit_per_day: int,
    cost: int = 1,
) -> tuple[bool, dict[str, Any] | None]:
    """In-memory sliding window rate limit check."""
    now = time.time()
    minute_ago = now - 60
    day_ago = now - 86400

    requests = _memory_store[key]

    # Prune entries older than 1 day
    requests[:] = [ts for ts in requests if ts > day_ago]

    minute_count = sum(1 for ts in requests if ts > minute_ago)
    day_count = len(requests)

    # Minute limit
    if limit_per_minute > 0 and minute_count + cost > limit_per_minute:
        retry_after = max(
            1, int(60 - (now - min((ts for ts in requests if ts > minute_ago), default=now)))
        )
        return False, {
            "error": "rate_limit_exceeded",
            "message": f"You have exceeded your rate limit of {limit_per_minute} requests/minute",
            "limit": limit_per_minute,
            # What is left, not a flat zero: a caller asking for several slots
            # at once can be refused with room still on the clock, and the
            # message it writes needs the true figure.
            "remaining": max(0, limit_per_minute - minute_count),
            "reset_at": int(now) + retry_after,
            "retry_after": retry_after,
        }

    # Day limit
    if limit_per_day > 0 and day_count + cost > limit_per_day:
        tomorrow_midnight = int((now // 86400 + 1) * 86400)
        retry_after = tomorrow_midnight - int(now)
        return False, {
            "error": "rate_limit_exceeded",
            "message": f"You have exceeded your daily rate limit of {limit_per_day} requests",
            "limit": limit_per_day,
            "remaining": max(0, limit_per_day - day_count),
            "reset_at": tomorrow_midnight,
            "retry_after": retry_after,
        }

    # Record the request, once per unit of cost, and only now that both windows
    # have room for the whole of it.
    requests.extend([now] * cost)

    return True, {
        "minute_limit": limit_per_minute,
        "minute_remaining": limit_per_minute - minute_count - cost,
        "day_limit": limit_per_day,
        "day_remaining": limit_per_day - day_count - cost,
    }


#: Prune, count, compare and record in one step on the Redis server. It was two
#: round trips (count in one pipeline, add in another), so N requests arriving
#: together all counted the same free slots and all passed: a daily quota of
#: 100 with 60 used let two 40-solve launches through to 140, and the
#: all-or-nothing promise of a comparison's quota did not hold.
#:
#: Returns ``{verdict, minute_count, day_count}``: verdict 0 = the minute window
#: is full, 1 = the day window is full, 2 = recorded.
_SLIDING_WINDOW_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', ARGV[3])
local minute_count = redis.call('ZCARD', KEYS[1])
local day_count = redis.call('ZCARD', KEYS[2])
local cost = tonumber(ARGV[6])
if tonumber(ARGV[4]) > 0 and minute_count + cost > tonumber(ARGV[4]) then
    return {0, minute_count, day_count}
end
if tonumber(ARGV[5]) > 0 and day_count + cost > tonumber(ARGV[5]) then
    return {1, minute_count, day_count}
end
for i = 0, cost - 1 do
    local member = ARGV[7] .. ':' .. i
    redis.call('ZADD', KEYS[1], ARGV[1], member)
    redis.call('ZADD', KEYS[2], ARGV[1], member)
end
redis.call('EXPIRE', KEYS[1], 120)
redis.call('EXPIRE', KEYS[2], 90000)
return {2, minute_count, day_count}
"""

#: The same, for one window of any length.
_SINGLE_WINDOW_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[2])
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[3]) then
    return {0, count}
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[5])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
return {1, count}
"""


def _member_prefix(now_str: str) -> str:
    """A sorted-set member no other request can share.

    A sorted set keeps one entry per member. Two requests that read the clock
    in the same microsecond, in two processes, wrote the same member and
    counted as one.
    """
    return f"{now_str}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _check_redis(
    key: str,
    limit_per_minute: int,
    limit_per_day: int,
    cost: int = 1,
) -> tuple[bool, dict[str, Any] | None]:
    """Redis sliding window rate limit check using sorted sets, atomically."""
    now = time.time()
    now_str = str(now)
    minute_ago = now - 60
    day_ago = now - 86400

    minute_key = f"rl:{key}:min"
    day_key = f"rl:{key}:day"

    try:
        assert _redis_client is not None
        verdict, minute_count, day_count = (
            int(v)
            for v in _redis_client.eval(
                _SLIDING_WINDOW_LUA,
                2,
                minute_key,
                day_key,
                now_str,
                minute_ago,
                day_ago,
                limit_per_minute,
                limit_per_day,
                cost,
                _member_prefix(now_str),
            )
        )

        if verdict == 0:
            oldest = _redis_client.zrangebyscore(
                minute_key, minute_ago, "+inf", start=0, num=1, withscores=True
            )
            if oldest:
                retry_after = max(1, int(60 - (now - float(oldest[0][1]))))
            else:
                retry_after = 60
            return False, {
                "error": "rate_limit_exceeded",
                "message": f"You have exceeded your rate limit of {limit_per_minute} requests/minute",
                "limit": limit_per_minute,
                "remaining": max(0, limit_per_minute - minute_count),
                "reset_at": int(now) + retry_after,
                "retry_after": retry_after,
            }

        if verdict == 1:
            tomorrow_midnight = int((now // 86400 + 1) * 86400)
            retry_after = tomorrow_midnight - int(now)
            return False, {
                "error": "rate_limit_exceeded",
                "message": f"You have exceeded your daily rate limit of {limit_per_day} requests",
                "limit": limit_per_day,
                "remaining": max(0, limit_per_day - day_count),
                "reset_at": tomorrow_midnight,
                "retry_after": retry_after,
            }

        return True, {
            "minute_limit": limit_per_minute,
            "minute_remaining": limit_per_minute - minute_count - cost,
            "day_limit": limit_per_day,
            "day_remaining": limit_per_day - day_count - cost,
        }

    except (RedisError, ConnectionError, OSError) as e:
        logger.warning(f"Redis rate limit check failed, falling back to memory: {e}")
        return _check_memory(key, limit_per_minute, limit_per_day, cost)


# Test bypass — set by conftest.py autouse fixture. Checked at call time so
# it works regardless of how callers imported check_rate_limit.
#
# Belt-and-suspenders: also honor the PYTEST_CURRENT_TEST env var that
# pytest sets automatically for every test invocation. This guarantees
# bypass is active during any pytest run even if a rogue test forgot to
# restore `_bypass` after toggling it off, or if fixture ordering puts
# the autouse below another fixture that issues rate-limited calls.
# Real-rate-limit tests that need the limiter active use the
# `real_rate_limiter` fixture, which sets `_force_real` to disable this
# env-based bypass.
_bypass = False
_force_real = False


def _is_bypassed() -> bool:
    if _force_real:
        return False
    if _bypass:
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def check_rate_limit(
    organization_id: str,
    limit_per_minute: int,
    limit_per_day: int,
    cost: int = 1,
) -> tuple[bool, dict[str, Any] | None]:
    """Check if request is within rate limits.

    Args:
        organization_id: Organization ID (or any unique key like ``login:<email>``).
        limit_per_minute: Maximum requests allowed per minute.
        limit_per_day: Maximum requests allowed per day.
        cost: How many slots this one request needs. All of them are taken
            together or none is: a caller that needs four slots and finds room
            for three is refused and charged nothing (D-30). A solver
            comparison asks for one slot per solver, and a matrix for one per
            cell, so a rejected launch used to leave the user's quota spent on
            a table that never ran.

    Returns:
        ``(allowed, info)`` — if *allowed* is False, *info* contains error
        details including ``retry_after``.
    """
    if _is_bypassed():
        return True, None
    if cost < 1:
        raise ValueError(f"cost must be at least 1, got {cost}")
    if _redis_client and not _fallback_mode:
        return _check_redis(organization_id, limit_per_minute, limit_per_day, cost)
    return _check_memory(organization_id, limit_per_minute, limit_per_day, cost)


def _check_memory_window(
    key: str,
    limit: int,
    window_seconds: int,
    label: str,
) -> tuple[bool, dict[str, Any] | None]:
    """In-memory sliding window rate limit check for a single named window."""
    if limit <= 0:
        # Not "zero requests allowed" — unlimited. Self-hosted operators set 0 to
        # turn a limit off, and the naive `count >= limit` below would lock the
        # whole instance out instead.
        return True, None

    now = time.time()
    window_ago = now - window_seconds

    requests = _memory_store[key]

    # Prune entries older than the window
    requests[:] = [ts for ts in requests if ts > window_ago]
    window_count = len(requests)

    if window_count >= limit:
        retry_after = max(1, int(window_seconds - (now - min(requests, default=now))))
        return False, {
            "error": "rate_limit_exceeded",
            "message": f"You have exceeded your rate limit of {limit} requests/{label}",
            "limit": limit,
            "remaining": 0,
            "reset_at": int(now) + retry_after,
            "retry_after": retry_after,
        }

    requests.append(now)
    return True, {f"{label}_limit": limit, f"{label}_remaining": limit - window_count - 1}


def _check_redis_window(
    key: str,
    limit: int,
    window_seconds: int,
    label: str,
) -> tuple[bool, dict[str, Any] | None]:
    """Redis sliding window rate limit check for a single named window."""
    if limit <= 0:
        return True, None  # unlimited — see _check_memory_window

    now = time.time()
    now_str = str(now)
    window_ago = now - window_seconds

    window_key = f"rl:{key}:{label}"

    try:
        assert _redis_client is not None
        verdict, window_count = (
            int(v)
            for v in _redis_client.eval(
                _SINGLE_WINDOW_LUA,
                1,
                window_key,
                now_str,
                window_ago,
                limit,
                window_seconds * 2,
                _member_prefix(now_str),
            )
        )

        if verdict == 0:
            # The score, not the member: the member is unique now, not the time.
            oldest = _redis_client.zrangebyscore(
                window_key, window_ago, "+inf", start=0, num=1, withscores=True
            )
            if oldest:
                retry_after = max(1, int(window_seconds - (now - float(oldest[0][1]))))
            else:
                retry_after = window_seconds
            return False, {
                "error": "rate_limit_exceeded",
                "message": f"You have exceeded your rate limit of {limit} requests/{label}",
                "limit": limit,
                "remaining": 0,
                "reset_at": int(now) + retry_after,
                "retry_after": retry_after,
            }

        return True, {
            f"{label}_limit": limit,
            f"{label}_remaining": limit - window_count - 1,
        }

    except (RedisError, ConnectionError, OSError) as e:
        logger.warning(f"Redis {label} rate limit check failed, falling back to memory: {e}")
        return _check_memory_window(key, limit, window_seconds, label)


def check_rate_limit_hourly(
    key: str,
    limit_per_hour: int,
) -> tuple[bool, dict[str, Any] | None]:
    """Check if request is within hourly rate limits.

    Used for password reset (3/hour per email).

    Args:
        key: Unique key (e.g., ``reset:user@example.com``).
        limit_per_hour: Maximum requests allowed per hour.

    Returns:
        ``(allowed, info)`` — if *allowed* is False, *info* contains error
        details including ``retry_after``.
    """
    if _is_bypassed():
        return True, None
    if _redis_client and not _fallback_mode:
        return _check_redis_window(key, limit_per_hour, 3600, "hour")
    return _check_memory_window(key, limit_per_hour, 3600, "hour")


# 15-minute window helper. Sole consumer: POST /api/v2/contact (3/15min per IP — tighter
# than global 60/min so spammers are gated at endpoint level without affecting public traffic).


_WINDOW_15MIN_SECONDS = 900


def check_rate_limit_15min(
    key: str,
    limit_per_15min: int,
) -> tuple[bool, dict[str, Any] | None]:
    """Check if request is within a 15-minute sliding window rate limit.

    Used for the public /api/v2/contact endpoint (3 / 15min per IP, D-02).
    Honors ``_is_bypassed()`` first so tests can opt into bypass via the
    standard ``PYTEST_CURRENT_TEST`` env var; tests that need the real
    limiter active use the ``real_rate_limiter`` fixture.

    Args:
        key: Unique key (e.g., ``contact_ip:1.2.3.4``).
        limit_per_15min: Maximum requests allowed per 15-minute window.

    Returns:
        ``(allowed, info)`` — if *allowed* is False, *info* contains error
        details including ``retry_after``.
    """
    if _is_bypassed():
        return True, None
    if _redis_client and not _fallback_mode:
        return _check_redis_window(key, limit_per_15min, _WINDOW_15MIN_SECONDS, "15min")
    return _check_memory_window(key, limit_per_15min, _WINDOW_15MIN_SECONDS, "15min")


def clear(organization_id: str | None = None) -> None:
    """Clear rate limit counters.

    Args:
        organization_id: If provided, clear only this key. Otherwise clear all.
    """
    # In-memory
    if organization_id:
        _memory_store.pop(organization_id, None)
    else:
        _memory_store.clear()

    # Redis
    if _redis_client and not _fallback_mode:
        try:
            if organization_id:
                _redis_client.delete(
                    f"rl:{organization_id}:min",
                    f"rl:{organization_id}:day",
                    f"rl:{organization_id}:hour",
                    f"rl:{organization_id}:15min",
                )
            else:
                # Scan and delete all rate-limit keys
                cursor = 0
                while True:
                    cursor, keys = _redis_client.scan(cursor, match="rl:*", count=100)
                    if keys:
                        _redis_client.delete(*keys)
                    if cursor == 0:
                        break
        except (RedisError, ConnectionError, OSError) as e:
            logger.warning(f"Failed to clear Redis rate limit keys: {e}")


# Module alias registration — pin both import paths to one module object.
# Without this, importing via the shim (app.core.rate_limiter) can create a
# second module instance, breaking global-state injection in tests.
sys.modules["app.core.rate_limiter"] = sys.modules[__name__]
