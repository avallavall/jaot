"""Tests for Redis-backed rate limiter with in-memory fallback.

All tests run against the in-memory fallback (no Redis required for CI).
Test 9 mocks the Redis client to verify the Redis code path.
"""

from unittest.mock import MagicMock

import pytest

from app.services.platform_settings_service import PlatformSettingsService as PSS
from app.shared.core import rate_limiter as rl_module
from app.shared.core.rate_limiter import (
    check_rate_limit,
    clear,
    init_redis,
)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset rate limiter state between tests."""
    rl_module._bypass = False
    rl_module._force_real = True  # override PYTEST_CURRENT_TEST bypass for this suite
    clear()
    # Ensure fallback mode for most tests
    original_client = rl_module._redis_client
    original_fallback = rl_module._fallback_mode
    rl_module._redis_client = None
    rl_module._fallback_mode = True
    yield
    clear()
    rl_module._redis_client = original_client
    rl_module._fallback_mode = original_fallback
    rl_module._bypass = True  # restore bypass for other tests
    rl_module._force_real = False


def test_rate_limiter_allows_within_limit():
    """check_rate_limit returns True for first request."""
    allowed, info = check_rate_limit("org_test", 10, 100)
    assert allowed is True
    assert info is not None
    assert info["minute_remaining"] == 9
    assert info["day_remaining"] == 99


def test_rate_limiter_blocks_over_minute_limit():
    """Exhaust minute limit, next request is blocked."""
    org = "org_min"
    limit = 3
    for _ in range(limit):
        allowed, _ = check_rate_limit(org, limit_per_minute=limit, limit_per_day=1000)
        assert allowed is True

    allowed, info = check_rate_limit(org, limit_per_minute=limit, limit_per_day=1000)
    assert allowed is False
    assert info["error"] == "rate_limit_exceeded"
    assert "minute" in info["message"]


def test_rate_limiter_blocks_over_day_limit():
    """Exhaust day limit, next request is blocked."""
    org = "org_day"
    day_limit = 3
    for _ in range(day_limit):
        allowed, _ = check_rate_limit(org, limit_per_minute=1000, limit_per_day=day_limit)
        assert allowed is True

    allowed, info = check_rate_limit(org, limit_per_minute=1000, limit_per_day=day_limit)
    assert allowed is False
    assert info["error"] == "rate_limit_exceeded"
    assert "daily" in info["message"]


def test_rate_limiter_returns_retry_after():
    """Blocked response includes retry_after > 0."""
    org = "org_retry"
    # Exhaust minute limit
    for _ in range(2):
        check_rate_limit(org, limit_per_minute=2, limit_per_day=1000)

    allowed, info = check_rate_limit(org, limit_per_minute=2, limit_per_day=1000)
    assert allowed is False
    assert info["retry_after"] > 0
    assert info["reset_at"] > 0


def test_solve_endpoint_enforces_rate_limit(authenticated_client, test_organization, db_session):
    """Use authenticated_client to hit solve until 429."""
    # Set very low rate limit on the test org
    test_organization.rate_limit_per_minute = 2
    test_organization.rate_limit_per_day = 100
    db_session.commit()

    # Clear any prior counts for this org
    clear(test_organization.id)

    problem = {
        "name": "test",
        "objective": {"sense": "minimize", "expression": "x"},
        "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 10}],
        "constraints": [],
    }

    statuses = []
    for _ in range(4):
        resp = authenticated_client.post("/api/v2/solve", json=problem)
        statuses.append(resp.status_code)

    assert 429 in statuses, f"Expected at least one 429, got: {statuses}"


# 5b. Template solve endpoint enforces rate limit


def test_template_solve_endpoint_enforces_rate_limit(
    authenticated_client, test_organization, db_session
):
    """Use authenticated_client to hit template solve until 429."""
    # Set very low rate limit on the test org
    test_organization.rate_limit_per_minute = 2
    test_organization.rate_limit_per_day = 100
    db_session.commit()

    # Clear any prior counts for this org
    clear(test_organization.id)

    # Knapsack template input
    template_input = {
        "capacity": 50,
        "items": [
            {"name": "laptop", "value": 600, "weight": 10},
            {"name": "camera", "value": 500, "weight": 5},
        ],
    }

    statuses = []
    for _ in range(4):
        resp = authenticated_client.post(
            "/api/v2/solve/templates/knapsack/solve",
            json=template_input,
        )
        statuses.append(resp.status_code)

    assert 429 in statuses, f"Expected at least one 429, got: {statuses}"


def test_login_endpoint_enforces_rate_limit(client, db_session):
    """Hit login with wrong creds until 429."""
    # Drive the configurable login limit low so 12 attempts trip it deterministically.
    PSS.set(db_session, "AUTH_LOGIN_RATE_LIMIT_PER_MINUTE", "5")
    db_session.commit()
    clear()

    statuses = []
    for _ in range(12):
        resp = client.post("/api/v2/auth/login", json={"api_key": "fake_key_12345678"})
        statuses.append(resp.status_code)

    assert 429 in statuses, f"Expected at least one 429, got: {statuses}"


# 7. clear() resets counters


def test_rate_limiter_clear():
    """clear() resets counters so requests are allowed again."""
    org = "org_clear"
    # Exhaust limit
    for _ in range(2):
        check_rate_limit(org, limit_per_minute=2, limit_per_day=1000)

    allowed, _ = check_rate_limit(org, limit_per_minute=2, limit_per_day=1000)
    assert allowed is False

    clear(org)

    allowed, _ = check_rate_limit(org, limit_per_minute=2, limit_per_day=1000)
    assert allowed is True


def test_rate_limiter_fallback_mode():
    """When Redis unavailable, still works (in-memory)."""
    # init_redis with empty string => fallback
    result = init_redis("")
    assert result is False
    assert rl_module._fallback_mode is True

    allowed, info = check_rate_limit("org_fallback", 10, 100)
    assert allowed is True
    assert info["minute_remaining"] == 9


def test_rate_limiter_redis_backend_calls():
    """Mock the Redis client and verify sorted-set commands are called."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe2 = MagicMock()

    # Pipeline for the read phase
    mock_pipe.execute.return_value = [
        0,  # zremrangebyscore minute
        0,  # zremrangebyscore day
        0,  # zcard minute
        0,  # zcard day
    ]
    # Pipeline for the write phase
    mock_pipe2.execute.return_value = [True, True, True, True]

    # First call returns read pipeline, second returns write pipeline
    mock_redis.pipeline.side_effect = [mock_pipe, mock_pipe2]

    # Temporarily inject mock Redis client
    rl_module._redis_client = mock_redis
    rl_module._fallback_mode = False

    try:
        allowed, info = check_rate_limit("org_redis", 10, 100)
        assert allowed is True

        # Verify sorted-set commands were called on the read pipeline
        mock_pipe.zremrangebyscore.assert_called()
        mock_pipe.zcard.assert_called()
        mock_pipe.execute.assert_called_once()

        # Verify write pipeline recorded the request
        mock_pipe2.zadd.assert_called()
        mock_pipe2.expire.assert_called()
        mock_pipe2.execute.assert_called_once()
    finally:
        rl_module._redis_client = None
        rl_module._fallback_mode = True


def test_rate_limiter_different_orgs_isolated():
    """Different organizations have independent rate limit counters."""
    # Exhaust org1's minute limit
    for _ in range(2):
        check_rate_limit("org_iso_1", limit_per_minute=2, limit_per_day=1000)

    blocked, _ = check_rate_limit("org_iso_1", limit_per_minute=2, limit_per_day=1000)
    assert blocked is False

    # org2 should still be allowed
    allowed, _ = check_rate_limit("org_iso_2", limit_per_minute=2, limit_per_day=1000)
    assert allowed is True


# 11. init_redis with invalid URL falls back gracefully


def test_init_redis_bad_url():
    """init_redis with unreachable URL falls back gracefully."""
    result = init_redis("redis://localhost:19999/0")
    assert result is False
    assert rl_module._fallback_mode is True
