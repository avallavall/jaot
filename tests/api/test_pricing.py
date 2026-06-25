"""Tests for the public pricing API endpoint.

Verifies:
- GET /api/v2/pricing returns 200 without authentication
- Response structure contains tiers array
- Each tier has all required fields
- All four tiers (free, starter, pro, business) are present
- Values match registry defaults
- Cache-Control header is set to 5-minute public cache
"""

import pytest


class TestPricingEndpoint:
    """Tests for GET /api/v2/pricing."""

    @pytest.fixture(autouse=True)
    def _enable_monetization(self, enable_monetization):
        """The pricing endpoint is paid-only (404 in free mode); enable monetization."""

    def test_four_tiers_present(self, client):
        """All four plan tiers are returned."""
        response = client.get("/api/v2/pricing")
        tiers = response.json()["tiers"]
        slugs = [t["slug"] for t in tiers]
        assert slugs == ["free", "starter", "pro", "business"]

    def test_tier_names(self, client):
        """Each tier has the correct display name."""
        response = client.get("/api/v2/pricing")
        tiers = response.json()["tiers"]
        names = {t["slug"]: t["name"] for t in tiers}
        assert names == {
            "free": "Free",
            "starter": "Starter",
            "pro": "Pro",
            "business": "Business",
        }

    @pytest.mark.parametrize(
        "field,expected_type",
        [
            ("slug", str),
            ("name", str),
            ("monthly_price", int),
            ("annual_price", int),
            ("credits", int),
            ("monthly_quota", int),
            ("rate_limit_per_minute", int),
            ("rate_limit_per_day", int),
            ("max_variables", int),
            ("max_solve_time_seconds", int),
            ("max_daily_solves", int),
            ("max_cron_schedules", int),
            ("allowed_features", list),
        ],
    )
    def test_tier_has_required_field(self, client, field, expected_type):
        """Every tier object contains all required fields, non-null, of the expected type."""
        response = client.get("/api/v2/pricing")
        tiers = response.json()["tiers"]
        assert len(tiers) == 4
        for tier in tiers:
            assert field in tier, f"Tier '{tier.get('slug', '?')}' missing field '{field}'"
            value = tier[field]
            assert value is not None, f"Tier '{tier['slug']}' field '{field}' is None"
            assert isinstance(value, expected_type), (
                f"Tier '{tier['slug']}' field '{field}' is {type(value).__name__}, "
                f"expected {expected_type.__name__}"
            )

    def test_free_tier_values(self, client):
        """Default ("free") plan values match registry defaults.

        No paid tiers anymore: the default plan carries full business-level
        limits (see settings_registry _PLAN_DEFAULTS). Price stays 0.
        """
        response = client.get("/api/v2/pricing")
        free = next(t for t in response.json()["tiers"] if t["slug"] == "free")
        assert free["monthly_price"] == 0
        assert free["annual_price"] == 0
        assert free["credits"] == 20000
        assert free["monthly_quota"] == 20000
        assert free["max_variables"] == 10000000
        assert free["max_solve_time_seconds"] == 3600
        assert free["max_cron_schedules"] == 50

    def test_starter_tier_values(self, client):
        """Starter tier values match registry defaults."""
        response = client.get("/api/v2/pricing")
        starter = next(t for t in response.json()["tiers"] if t["slug"] == "starter")
        assert starter["monthly_price"] == 19
        assert starter["annual_price"] == 190
        assert starter["credits"] == 600
        assert starter["max_variables"] == 100000
        assert starter["max_solve_time_seconds"] == 300

    def test_pro_tier_values(self, client):
        """Pro tier values match registry defaults."""
        response = client.get("/api/v2/pricing")
        pro = next(t for t in response.json()["tiers"] if t["slug"] == "pro")
        assert pro["monthly_price"] == 49
        assert pro["annual_price"] == 490
        assert pro["credits"] == 2500
        assert pro["max_variables"] == 1000000
        assert pro["max_solve_time_seconds"] == 900

    def test_business_tier_values(self, client):
        """Business tier values match registry defaults."""
        response = client.get("/api/v2/pricing")
        business = next(t for t in response.json()["tiers"] if t["slug"] == "business")
        assert business["monthly_price"] == 149
        assert business["annual_price"] == 1490
        assert business["credits"] == 20000
        assert business["max_variables"] == 10000000
        assert business["max_solve_time_seconds"] == 3600

    def test_no_auth_required(self, client):
        """Endpoint works without any Authorization header."""
        # client fixture is unauthenticated by default
        response = client.get("/api/v2/pricing")
        assert response.status_code == 200

    def test_cache_control_header(self, client):
        """Response includes Cache-Control: public, max-age=300."""
        response = client.get("/api/v2/pricing")
        cache_control = response.headers.get("cache-control")
        assert cache_control is not None, "Missing Cache-Control header"
        assert "public" in cache_control
        assert "max-age=300" in cache_control


class TestPricingEndpointEdgeCases:
    """Edge case tests for the pricing endpoint."""

    @pytest.fixture(autouse=True)
    def _enable_monetization(self, enable_monetization):
        """The pricing endpoint is paid-only (404 in free mode); enable monetization."""

    def test_tiers_ordered_by_price(self, client):
        """Tiers are ordered by ascending monthly price."""
        response = client.get("/api/v2/pricing")
        tiers = response.json()["tiers"]
        prices = [t["monthly_price"] for t in tiers]
        assert prices == sorted(prices)
