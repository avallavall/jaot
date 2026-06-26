"""Redis-backed rate limiter with in-memory fallback.

Uses sorted sets for a sliding window approach when Redis is available.
Falls back to an in-memory implementation when Redis is unavailable
(e.g., local development without Redis, or connection failures).
"""

import logging
import os
import sys
import time
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
    if minute_count >= limit_per_minute:
        retry_after = max(
            1, int(60 - (now - min((ts for ts in requests if ts > minute_ago), default=now)))
        )
        return False, {
            "error": "rate_limit_exceeded",
            "message": f"You have exceeded your rate limit of {limit_per_minute} requests/minute",
            "limit": limit_per_minute,
            "remaining": 0,
            "reset_at": int(now) + retry_after,
            "retry_after": retry_after,
        }

    # Day limit
    if day_count >= limit_per_day:
        tomorrow_midnight = int((now // 86400 + 1) * 86400)
        retry_after = tomorrow_midnight - int(now)
        return False, {
            "error": "rate_limit_exceeded",
            "message": f"You have exceeded your daily rate limit of {limit_per_day} requests",
            "limit": limit_per_day,
            "remaining": 0,
            "reset_at": tomorrow_midnight,
            "retry_after": retry_after,
        }

    # Record request
    requests.append(now)

    return True, {
        "minute_limit": limit_per_minute,
        "minute_remaining": limit_per_minute - minute_count - 1,
        "day_limit": limit_per_day,
        "day_remaining": limit_per_day - day_count - 1,
    }


def _check_redis(
    key: str,
    limit_per_minute: int,
    limit_per_day: int,
) -> tuple[bool, dict[str, Any] | None]:
    """Redis sliding window rate limit check using sorted sets."""
    now = time.time()
    now_str = str(now)
    minute_ago = now - 60
    day_ago = now - 86400

    minute_key = f"rl:{key}:min"
    day_key = f"rl:{key}:day"

    try:
        assert _redis_client is not None
        pipe = _redis_client.pipeline()

        # Clean old entries
        pipe.zremrangebyscore(minute_key, "-inf", minute_ago)
        pipe.zremrangebyscore(day_key, "-inf", day_ago)

        # Count current entries
        pipe.zcard(minute_key)
        pipe.zcard(day_key)

        results = pipe.execute()
        minute_count = results[2]
        day_count = results[3]

        if minute_count >= limit_per_minute:
            oldest = _redis_client.zrangebyscore(minute_key, minute_ago, "+inf", start=0, num=1)
            if oldest:
                retry_after = max(1, int(60 - (now - float(oldest[0]))))
            else:
                retry_after = 60
            return False, {
                "error": "rate_limit_exceeded",
                "message": f"You have exceeded your rate limit of {limit_per_minute} requests/minute",
                "limit": limit_per_minute,
                "remaining": 0,
                "reset_at": int(now) + retry_after,
                "retry_after": retry_after,
            }

        if day_count >= limit_per_day:
            tomorrow_midnight = int((now // 86400 + 1) * 86400)
            retry_after = tomorrow_midnight - int(now)
            return False, {
                "error": "rate_limit_exceeded",
                "message": f"You have exceeded your daily rate limit of {limit_per_day} requests",
                "limit": limit_per_day,
                "remaining": 0,
                "reset_at": tomorrow_midnight,
                "retry_after": retry_after,
            }

        # Record request in both windows
        assert _redis_client is not None
        pipe2 = _redis_client.pipeline()
        pipe2.zadd(minute_key, {now_str: now})
        pipe2.zadd(day_key, {now_str: now})
        pipe2.expire(minute_key, 120)  # TTL slightly > 1 minute
        pipe2.expire(day_key, 90000)  # TTL slightly > 1 day
        pipe2.execute()

        return True, {
            "minute_limit": limit_per_minute,
            "minute_remaining": limit_per_minute - minute_count - 1,
            "day_limit": limit_per_day,
            "day_remaining": limit_per_day - day_count - 1,
        }

    except (RedisError, ConnectionError, OSError) as e:
        logger.warning(f"Redis rate limit check failed, falling back to memory: {e}")
        return _check_memory(key, limit_per_minute, limit_per_day)


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
) -> tuple[bool, dict[str, Any] | None]:
    """Check if request is within rate limits.

    Args:
        organization_id: Organization ID (or any unique key like ``login:<email>``).
        limit_per_minute: Maximum requests allowed per minute.
        limit_per_day: Maximum requests allowed per day.

    Returns:
        ``(allowed, info)`` — if *allowed* is False, *info* contains error
        details including ``retry_after``.
    """
    if _is_bypassed():
        return True, None
    if _redis_client and not _fallback_mode:
        return _check_redis(organization_id, limit_per_minute, limit_per_day)
    return _check_memory(organization_id, limit_per_minute, limit_per_day)


def _check_memory_window(
    key: str,
    limit: int,
    window_seconds: int,
    label: str,
) -> tuple[bool, dict[str, Any] | None]:
    """In-memory sliding window rate limit check for a single named window."""
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
    now = time.time()
    now_str = str(now)
    window_ago = now - window_seconds

    window_key = f"rl:{key}:{label}"

    try:
        assert _redis_client is not None
        pipe = _redis_client.pipeline()

        # Clean old entries
        pipe.zremrangebyscore(window_key, "-inf", window_ago)
        # Count current entries
        pipe.zcard(window_key)

        results = pipe.execute()
        window_count = results[1]

        if window_count >= limit:
            oldest = _redis_client.zrangebyscore(window_key, window_ago, "+inf", start=0, num=1)
            if oldest:
                retry_after = max(1, int(window_seconds - (now - float(oldest[0]))))
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

        # Record request
        assert _redis_client is not None
        pipe2 = _redis_client.pipeline()
        pipe2.zadd(window_key, {now_str: now})
        pipe2.expire(window_key, window_seconds * 2)  # TTL = 2x window
        pipe2.execute()

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
