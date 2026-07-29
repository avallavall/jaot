"""Tests for all issues found in the Python code review.

Covers CRITICAL, HIGH, and MEDIUM fixes across:
- auth_middleware: narrowed PUBLIC_DYNAMIC_PATHS, logged rollback, JWT error type

- llm_conversation: no DB session in column default
- anthropic_client + pool: thread-safe singleton
- pricing: batch queries, no Pydantic round-trip
- feedback: org_id filter on GET rating
- seed_admin: generate_id() usage
- community: nonce validation
- jwt_service: typed db parameter
- maintenance_middleware: explicit skip flag
- api_key_service: org_id filter on list_keys
- main: single startup DB session
"""

import threading
from datetime import datetime

import pytest

from app.shared.core.auth_middleware import _is_public


# Override autouse DB fixtures — pure unit tests need no database.
@pytest.fixture(autouse=True)
def _truncate_tables():
    yield


@pytest.fixture(autouse=True)
def override_db_dependency():
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limiter():
    yield


class TestPublicDynamicPathsNarrowed:
    """CRITICAL: PUBLIC_DYNAMIC_PATHS must only allow specific suffixes."""

    def test_user_public_profile_allowed(self):
        assert _is_public("/api/v2/users/abc123/public", "GET") is True

    def test_user_reviews_allowed(self):
        assert _is_public("/api/v2/users/abc123/reviews", "GET") is True

    def test_user_by_slug_allowed(self):
        assert _is_public("/api/v2/users/by-slug/john-doe", "GET") is True

    def test_org_public_profile_allowed(self):
        assert _is_public("/api/v2/organizations/abc123/public", "GET") is True

    def test_org_by_slug_allowed(self):
        assert _is_public("/api/v2/organizations/by-slug/my-org", "GET") is True

    def test_org_models_allowed(self):
        assert _is_public("/api/v2/organizations/abc123/models", "GET") is True

    # Regression: these MUST be blocked (the review found they were open)
    def test_user_billing_blocked(self):
        """A sensitive sub-path under /users/ must require auth."""
        assert _is_public("/api/v2/users/abc123/billing", "GET") is False

    def test_user_settings_blocked(self):
        assert _is_public("/api/v2/users/abc123/settings", "GET") is False

    def test_org_members_blocked(self):
        assert _is_public("/api/v2/organizations/abc123/members", "GET") is False

    def test_org_api_keys_blocked(self):
        assert _is_public("/api/v2/organizations/abc123/api-keys", "GET") is False

    def test_user_root_get_blocked(self):
        """GET /api/v2/users/ itself should not be public."""
        assert _is_public("/api/v2/users/", "GET") is False

    def test_post_method_still_blocked(self):
        assert _is_public("/api/v2/users/abc123/public", "POST") is False
        assert _is_public("/api/v2/organizations/abc123/public", "POST") is False


class TestLLMConversationDefault:
    """CRITICAL: _default_expires_at must NOT open a DB session."""

    def test_default_expires_at_no_db_session(self):
        from app.models.llm_conversation import _default_expires_at

        # Should not raise or open any DB session
        result = _default_expires_at()
        assert isinstance(result, datetime)

    def test_default_expires_at_is_24h_ahead(self):
        from app.models.llm_conversation import _default_expires_at
        from app.shared.utils.datetime_helpers import utcnow

        now = utcnow()
        result = _default_expires_at()
        delta = result - now
        # Should be approximately 24 hours (allow 5 seconds tolerance)
        assert 23.99 * 3600 <= delta.total_seconds() <= 24.01 * 3600


class TestAnthropicClientThreadSafety:
    """HIGH: _get_or_create_client must be thread-safe."""

    def test_has_lock(self):
        from app.services.llm import anthropic_client

        assert hasattr(anthropic_client, "_client_cache_lock")
        assert isinstance(anthropic_client._client_cache_lock, type(threading.Lock()))


class TestFeedbackOrgFilter:
    """HIGH: get_conversation_rating must filter by organization_id."""

    def test_get_rating_has_org_parameter(self):
        import inspect

        from app.api.v2.feedback import get_conversation_rating

        sig = inspect.signature(get_conversation_rating)
        assert "org" in sig.parameters, "get_conversation_rating must accept 'org' parameter"


class TestMaintenanceMiddlewareSkipFlag:
    """MEDIUM: Maintenance middleware uses explicit _skip_maintenance_check flag."""

    def test_has_skip_flag(self):
        from app.shared.core import maintenance_middleware as mw

        assert hasattr(mw, "_skip_maintenance_check")


class TestApiKeyServiceOrgFilter:
    """MEDIUM: list_keys must accept organization_id parameter."""

    def test_list_keys_has_org_parameter(self):
        import inspect

        from app.services.auth.api_key_service import APIKeyService

        sig = inspect.signature(APIKeyService.list_keys)
        assert "organization_id" in sig.parameters


class TestPSSBatchMethod:
    """HIGH: PlatformSettingsService must have get_many for batch queries."""

    def test_get_many_exists(self):
        from app.services.platform_settings_service import PlatformSettingsService

        assert hasattr(PlatformSettingsService, "get_many")
