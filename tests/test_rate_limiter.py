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
    # D-23: the limit is an instance setting, not a column on the organization.
    PSS.bulk_set(
        db_session,
        {"instance_rate_limit_per_minute": "2", "instance_rate_limit_per_day": "100"},
        changed_by="test",
    )
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
    # D-23: the limit is an instance setting, not a column on the organization.
    PSS.bulk_set(
        db_session,
        {"instance_rate_limit_per_minute": "2", "instance_rate_limit_per_day": "100"},
        changed_by="test",
    )
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
    """The Redis path checks and records in ONE server-side script call.

    It was two pipelines (count, then add), which let requests arriving
    together all count the same free slots.
    """
    mock_redis = MagicMock()
    mock_redis.eval.return_value = [2, 0, 0]  # recorded; 0 in each window before

    rl_module._redis_client = mock_redis
    rl_module._fallback_mode = False

    try:
        allowed, info = check_rate_limit("org_redis", 10, 100)
        assert allowed is True
        assert mock_redis.eval.call_count == 1
        script, numkeys, minute_key, day_key = mock_redis.eval.call_args.args[:4]
        assert "ZCARD" in script and "ZADD" in script
        assert numkeys == 2
        assert (minute_key, day_key) == ("rl:org_redis:min", "rl:org_redis:day")
        mock_redis.pipeline.assert_not_called()
    finally:
        rl_module._redis_client = None
        rl_module._fallback_mode = True


def test_concurrent_requests_cannot_share_the_last_slots():
    """# CONTRACT-TEST: the Redis limiter admits exactly `limit` of a simultaneous burst.

    Runs against a real Redis when one is reachable (the dev stack has one; CI
    does not, and there the in-memory limiter is what runs).
    """
    import concurrent.futures
    import os

    import redis

    url = os.environ.get("RATE_LIMIT_TEST_REDIS_URL", "redis://jaot_redis:6379/15")
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=1)
        client.ping()
    except Exception:
        pytest.skip("no Redis reachable for the concurrency check")

    key = f"burst_{os.getpid()}"
    client.delete(f"rl:{key}:min", f"rl:{key}:day")
    rl_module._redis_client = client
    rl_module._fallback_mode = False
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
            verdicts = list(pool.map(lambda _: check_rate_limit(key, 1000, 10)[0], range(30)))
        assert verdicts.count(True) == 10
    finally:
        client.delete(f"rl:{key}:min", f"rl:{key}:day")
        rl_module._redis_client = None
        rl_module._fallback_mode = True


class TestCost:
    """One request that needs several slots takes all of them or none (D-30)."""

    def test_a_cost_takes_that_many_slots(self):
        allowed, info = check_rate_limit("org_cost", 10, 100, cost=4)
        assert allowed is True
        assert info["minute_remaining"] == 6
        assert info["day_remaining"] == 96

    def test_a_request_that_does_not_fit_is_refused(self):
        check_rate_limit("org_cost_full", limit_per_minute=10, limit_per_day=5, cost=3)

        allowed, info = check_rate_limit("org_cost_full", 10, 5, cost=3)
        assert allowed is False
        assert info["error"] == "rate_limit_exceeded"
        # What is left, not a flat zero: the caller writes it into the refusal.
        assert info["remaining"] == 2

    # CONTRACT-TEST: a refused request consumes nothing. The comparison endpoint
    # charged one slot per solver in a loop, so a rejection left the earlier
    # solvers' slots spent on a table that never ran.
    def test_a_refused_request_consumes_nothing(self):
        check_rate_limit("org_cost_intact", limit_per_minute=10, limit_per_day=5, cost=3)

        refused, _ = check_rate_limit("org_cost_intact", 10, 5, cost=3)
        assert refused is False

        # The two slots the day still had are still there.
        allowed, info = check_rate_limit("org_cost_intact", 10, 5, cost=2)
        assert allowed is True
        assert info["day_remaining"] == 0

    def test_a_cost_below_one_is_a_programming_error(self):
        with pytest.raises(ValueError):
            check_rate_limit("org_cost_zero", 10, 100, cost=0)


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


# Every token JAOT signs starts with the same base64 header. The reset and
# verification limits were keyed on the first 16 characters, which is exactly
# that header, so one bucket served every user: junk requests from anyone
# blocked every password reset and email verification on the instance.
_SHARED_JWT_PREFIX = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."


@pytest.mark.parametrize(
    ("path", "setting", "body"),
    [
        (
            "/api/v2/auth/reset-password",
            "AUTH_RESET_TOKEN_RATE_LIMIT_PER_MINUTE",
            {"password": "a-long-enough-password-1"},
        ),
        ("/api/v2/auth/verify-email", "AUTH_VERIFY_EMAIL_RATE_LIMIT_PER_MINUTE", {}),
    ],
)
def test_junk_tokens_do_not_spend_another_users_link(client, db_session, path, setting, body):
    PSS.set(db_session, setting, "3")
    db_session.commit()
    clear()

    junk = [
        client.post(path, json={**body, "token": f"{_SHARED_JWT_PREFIX}junk{i}.sig"}).status_code
        for i in range(6)
    ]
    assert 429 not in junk, f"distinct tokens shared one bucket: {junk}"

    same = [
        client.post(path, json={**body, "token": f"{_SHARED_JWT_PREFIX}again.sig"}).status_code
        for _ in range(5)
    ]
    assert same[-1] == 429, f"one token must still be limited: {same}"
