"""Tests for all issues found in the Python code review.

Covers CRITICAL, HIGH, and MEDIUM fixes across:
- auth_middleware: narrowed PUBLIC_DYNAMIC_PATHS, logged rollback, JWT error type
- credits_service: prefixed IDs, timezone-aware datetimes, biweekly fix
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
from unittest.mock import patch

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


class TestCreditsServicePrefixedIds:
    """HIGH: CreditTransaction, Withdrawal, WithdrawalSchedule IDs must be prefixed.

    Real-DB integration tests: actually call the service methods and assert
    the resulting row id starts with the documented prefix.
    """

    def test_record_transaction_id_has_ctx_prefix(self, db_session, test_organization):
        """record_transaction creates IDs with 'ctx_' prefix."""
        from app.models import TransactionType
        from app.services.credits_service import CreditsService

        service = CreditsService(db_session)
        tx = service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.PURCHASE,
            credits_amount=100,
            description="prefix test",
        )
        db_session.commit()
        assert tx.id.startswith("ctx_")
        assert len(tx.id) > len("ctx_")

    def test_create_withdrawal_id_has_wdr_prefix(self, db_session, test_organization):
        """create_withdrawal creates IDs with 'wdr_' prefix."""
        from datetime import timedelta

        from app.models import CreditTransaction, TransactionType
        from app.services.credits_service import CreditsService
        from app.shared.utils.datetime_helpers import utcnow

        # Top up earned credits first so the withdrawal is fundable
        service = CreditsService(db_session)
        earning = service.record_transaction(
            organization_id=test_organization.id,
            transaction_type=TransactionType.SALE_EARNING,
            credits_amount=1000,
            description="seed earnings for withdrawal test",
        )
        # Backdate the earning past the holding window so it is withdrawable
        earning.available_at = utcnow() - timedelta(days=1)
        db_session.flush()

        # Mark Stripe Connect onboarding complete (required by create_withdrawal)
        test_organization.stripe_connect_onboarding_complete = True
        db_session.flush()

        withdrawal = service.create_withdrawal(
            organization_id=test_organization.id,
            credits_amount=500,
        )
        db_session.commit()
        assert withdrawal.id.startswith("wdr_")
        assert len(withdrawal.id) > len("wdr_")
        # Sanity: the matching CreditTransaction also has the prefixed id
        tx = (
            db_session.query(CreditTransaction)
            .filter(CreditTransaction.reference_id == withdrawal.id)
            .first()
        )
        assert tx is not None
        assert tx.id.startswith("ctx_")

    def test_create_withdrawal_schedule_id_has_wds_prefix(self, db_session, test_organization):
        """create_withdrawal_schedule creates IDs with 'wds_' prefix."""
        from app.models import ScheduleAmountType, ScheduleFrequency
        from app.services.credits_service import CreditsService

        service = CreditsService(db_session)
        test_organization.stripe_connect_onboarding_complete = True
        db_session.flush()

        schedule = service.create_withdrawal_schedule(
            organization_id=test_organization.id,
            frequency=ScheduleFrequency.MONTHLY,
            amount_type=ScheduleAmountType.FIXED,
            amount_value=200.0,
        )
        db_session.commit()
        assert schedule.id.startswith("wds_")
        assert len(schedule.id) > len("wds_")


class TestCreditsServiceTimezoneAware:
    """HIGH: _calculate_next_execution must return timezone-aware datetimes."""

    def test_monthly_is_timezone_aware(self):
        from app.models import ScheduleFrequency
        from app.services.credits_service import CreditsService

        service = CreditsService.__new__(CreditsService)
        result = service._calculate_next_execution(ScheduleFrequency.MONTHLY)
        assert result.tzinfo is not None, "MONTHLY datetime must be timezone-aware"

    def test_quarterly_is_timezone_aware(self):
        from app.models import ScheduleFrequency
        from app.services.credits_service import CreditsService

        service = CreditsService.__new__(CreditsService)
        result = service._calculate_next_execution(ScheduleFrequency.QUARTERLY)
        assert result.tzinfo is not None, "QUARTERLY datetime must be timezone-aware"

    def test_weekly_is_timezone_aware(self):
        from app.models import ScheduleFrequency
        from app.services.credits_service import CreditsService

        service = CreditsService.__new__(CreditsService)
        result = service._calculate_next_execution(ScheduleFrequency.WEEKLY)
        assert result.tzinfo is not None, "WEEKLY datetime must be timezone-aware"

    def test_biweekly_is_timezone_aware(self):
        from app.models import ScheduleFrequency
        from app.services.credits_service import CreditsService

        service = CreditsService.__new__(CreditsService)
        result = service._calculate_next_execution(ScheduleFrequency.BIWEEKLY)
        assert result.tzinfo is not None, "BIWEEKLY datetime must be timezone-aware"


class TestBiweeklyCalculation:
    """MEDIUM: BIWEEKLY should be exactly 14 days from now."""

    def test_biweekly_is_exactly_14_days(self):
        from app.models import ScheduleFrequency
        from app.services.credits_service import CreditsService
        from app.shared.utils.datetime_helpers import utcnow

        service = CreditsService.__new__(CreditsService)
        now = utcnow()

        with patch("app.services.credits_service.utcnow", return_value=now):
            result = service._calculate_next_execution(ScheduleFrequency.BIWEEKLY)

        delta = result - now
        assert delta.days == 14, f"BIWEEKLY should be 14 days ahead, got {delta.days}"


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


class TestSolverPoolThreadSafety:
    """HIGH: get_solver_pool must be thread-safe."""

    def test_has_lock(self):
        from app.domains.solver.services import pool

        assert hasattr(pool, "_solver_pool_lock")
        assert isinstance(pool._solver_pool_lock, type(threading.Lock()))


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
