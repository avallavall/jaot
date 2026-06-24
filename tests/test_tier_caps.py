"""Tests for tier cap enforcement on solve and LLM endpoints.

Updated for pricing restructure (2026-03):
- _enforce_tier_caps now takes (db, org, problem) and uses PSS.get_plan_config_dynamic
- Feature gating removed: all features available on all tiers
- No more warm_start rejection on free tier
- No more LLM feature_not_available on free tier
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import status

from app.models import Organization
from app.schemas.optimization import (
    OptimizationProblem,
)
from app.schemas.tier import TierCapError, tier_cap_detail


class TestTierCapDetail:
    """Tests for the tier_cap_detail helper."""

    def test_builds_correct_detail(self):
        detail = tier_cap_detail(
            error="variable_limit_exceeded",
            message="Too many variables",
            current_plan="free",
            limit=1000,
            current_value=1500,
        )
        assert detail["error"] == "variable_limit_exceeded"
        assert detail["message"] == "Too many variables"
        assert detail["current_plan"] == "free"
        assert detail["limit"] == 1000
        assert detail["current_value"] == 1500
        assert detail["upgrade_to"] == "Starter"
        assert detail["upgrade_url"] == "/billing"

    def test_upgrade_map_starter(self):
        detail = tier_cap_detail(error="test", message="msg", current_plan="starter", limit=5000)
        assert detail["upgrade_to"] == "Pro"

    def test_upgrade_map_pro(self):
        detail = tier_cap_detail(error="test", message="msg", current_plan="pro", limit=25000)
        assert detail["upgrade_to"] == "Business"

    def test_upgrade_map_business(self):
        detail = tier_cap_detail(error="test", message="msg", current_plan="business", limit=100000)
        assert detail["upgrade_to"] == "Business"

    def test_schema_validation(self):
        """TierCapError validates correctly."""
        err = TierCapError(
            error="variable_limit_exceeded",
            message="msg",
            current_plan="free",
            limit=1000,
            upgrade_to="Starter",
        )
        assert err.current_value is None
        assert err.upgrade_url == "/billing"


FREE_PLAN_CONFIG = {
    "credits": 50,
    "monthly_quota": 50,
    "rate_limit_per_minute": 5,
    "rate_limit_per_day": 50,
    "max_solve_time_seconds": 60,
    "max_variables": 5000,
    "max_daily_solves": 50,
    "max_cron_schedules": 1,
    "allowed_features": [
        "llm_assistant",
        "warm_start",
        "sensitivity_analysis",
        "cron_scheduling",
    ],
}

STARTER_PLAN_CONFIG = {
    "credits": 600,
    "monthly_quota": 600,
    "rate_limit_per_minute": 20,
    "rate_limit_per_day": 500,
    "max_solve_time_seconds": 300,
    "max_variables": 100000,
    "max_daily_solves": 500,
    "max_cron_schedules": 5,
    "allowed_features": [
        "llm_assistant",
        "warm_start",
        "sensitivity_analysis",
        "cron_scheduling",
    ],
}


def _make_org(plan: str = "free") -> Organization:
    """Create a minimal Organization-like object for testing."""
    org = MagicMock(spec=Organization)
    org.id = "org_test001"
    org.plan = plan
    org.rate_limit_per_minute = 2
    org.rate_limit_per_day = 10
    org.credits_balance = 1000
    return org


def _make_problem(num_vars: int = 2, time_limit: int = 30, warm_start: bool = False) -> dict:
    """Build a minimal solve request body."""
    variables = [
        {"name": f"x{i}", "type": "continuous", "lower_bound": 0, "upper_bound": 100}
        for i in range(num_vars)
    ]
    # Cap expression length to stay within schema limit (10,000 chars)
    obj_expr = " + ".join(f"x{i}" for i in range(min(num_vars, 500)))
    body: dict = {
        "name": "test_problem",
        "objective": {"sense": "minimize", "expression": obj_expr},
        "variables": variables,
        "constraints": [],
        "options": {"time_limit_seconds": time_limit},
    }
    if warm_start:
        body["warm_start"] = {"execution_id": "exe_prev001"}
    return body


class TestEnforceTierCapsUnit:
    """Unit tests for the _enforce_tier_caps function.

    _enforce_tier_caps(db, org, problem) uses PSS.get_plan_config_dynamic.
    """

    @patch("app.api.v2.solve.PSS.get_plan_config_dynamic", return_value=FREE_PLAN_CONFIG)
    @patch("app.api.v2.solve.check_rate_limit", return_value=(True, None))
    def test_variable_limit_exceeded_free(self, mock_rl, mock_pss):
        from app.api.v2.solve import _enforce_tier_caps

        db = MagicMock()
        org = _make_org("free")
        problem = OptimizationProblem(**_make_problem(num_vars=5500))

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _enforce_tier_caps(db, org, problem)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"] == "variable_limit_exceeded"
        assert exc_info.value.detail["current_plan"] == "free"
        assert exc_info.value.detail["limit"] == 5000
        assert exc_info.value.detail["current_value"] == 5500

    @patch("app.api.v2.solve.PSS.get_plan_config_dynamic", return_value=FREE_PLAN_CONFIG)
    @patch("app.api.v2.solve.check_rate_limit", return_value=(True, None))
    def test_variable_limit_ok_free(self, mock_rl, mock_pss):
        from app.api.v2.solve import _enforce_tier_caps

        db = MagicMock()
        org = _make_org("free")
        problem = OptimizationProblem(**_make_problem(num_vars=500))

        # Should not raise
        _enforce_tier_caps(db, org, problem)

    @patch("app.api.v2.solve.PSS.get_plan_config_dynamic", return_value=FREE_PLAN_CONFIG)
    @patch("app.api.v2.solve.check_rate_limit", return_value=(True, None))
    def test_time_limit_clamped_free(self, mock_rl, mock_pss):
        from app.api.v2.solve import _enforce_tier_caps

        db = MagicMock()
        org = _make_org("free")
        problem = OptimizationProblem(**_make_problem(time_limit=120))

        clamped = _enforce_tier_caps(db, org, problem)
        assert clamped.options.time_limit_seconds == 60

    @patch("app.api.v2.solve.PSS.get_plan_config_dynamic", return_value=FREE_PLAN_CONFIG)
    @patch("app.api.v2.solve.check_rate_limit", return_value=(True, None))
    def test_time_limit_not_clamped_when_under(self, mock_rl, mock_pss):
        from app.api.v2.solve import _enforce_tier_caps

        db = MagicMock()
        org = _make_org("free")
        problem = OptimizationProblem(**_make_problem(time_limit=20))

        result = _enforce_tier_caps(db, org, problem)
        assert result.options.time_limit_seconds == 20

    @patch("app.api.v2.solve.PSS.get_plan_config_dynamic", return_value=FREE_PLAN_CONFIG)
    @patch("app.api.v2.solve.check_rate_limit", return_value=(False, {"error": "rate limited"}))
    def test_daily_solve_quota_exceeded(self, mock_rl, mock_pss):
        from app.api.v2.solve import _enforce_tier_caps

        db = MagicMock()
        org = _make_org("free")
        problem = OptimizationProblem(**_make_problem())

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _enforce_tier_caps(db, org, problem)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"] == "daily_solve_quota_exceeded"

    @patch("app.api.v2.solve.PSS.get_plan_config_dynamic", return_value=FREE_PLAN_CONFIG)
    @patch("app.api.v2.solve.check_rate_limit", return_value=(True, None))
    def test_warm_start_accepted_free(self, mock_rl, mock_pss):
        """Post-restructure: warm_start is accepted on free tier (no feature gating).

        Asserts:
          - The call returns normally (no exception)
          - warm_start metadata is preserved on the problem
          - time_limit_seconds is clamped to the free cap (60s) since we passed 30s
            (no change expected because 30 < 60)
        """
        from app.api.v2.solve import _enforce_tier_caps

        db = MagicMock()
        org = _make_org("free")
        problem = OptimizationProblem(**_make_problem(time_limit=30, warm_start=True))
        original_warm_start_id = problem.warm_start.execution_id

        # Should NOT raise -- feature gating was removed
        result = _enforce_tier_caps(db, org, problem)

        # warm_start preserved
        assert result.warm_start is not None
        assert result.warm_start.execution_id == original_warm_start_id
        # 30 < 60 cap -> time limit unchanged
        assert result.options.time_limit_seconds == 30

    @patch("app.api.v2.solve.PSS.get_plan_config_dynamic", return_value=STARTER_PLAN_CONFIG)
    @patch("app.api.v2.solve.check_rate_limit", return_value=(True, None))
    def test_warm_start_allowed_starter(self, mock_rl, mock_pss):
        """Starter plan accepts warm_start (no feature gating).

        Asserts warm_start survives the call and time_limit_seconds is NOT
        clamped (we pass 120s, starter cap is 300s).
        """
        from app.api.v2.solve import _enforce_tier_caps

        db = MagicMock()
        org = _make_org("starter")
        problem = OptimizationProblem(**_make_problem(time_limit=120, warm_start=True))

        result = _enforce_tier_caps(db, org, problem)

        assert result.warm_start is not None
        assert result.warm_start.execution_id == "exe_prev001"
        # 120 < 300 cap -> time limit unchanged
        assert result.options.time_limit_seconds == 120


class TestLLMFeatureGateRemoved:
    """Verify LLM endpoints no longer feature-gate free users.

    Post-restructure: all features are available on all tiers.
    Free users CAN create conversations (201, not 403).
    """

    def test_create_conversation_allowed_free(
        self, authenticated_client, test_organization, db_session
    ):
        test_organization.plan = "free"
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/llm/conversations",
            json={},
        )
        # Must NOT be 403 feature_not_available
        assert response.status_code != status.HTTP_403_FORBIDDEN
        assert response.status_code == status.HTTP_201_CREATED


class TestErrorResponseSchema:
    """Verify all tier cap errors match the TierCapError schema."""

    def test_variable_limit_error_has_all_fields(self):
        detail = tier_cap_detail(
            error="variable_limit_exceeded",
            message="Too many variables",
            current_plan="free",
            limit=1000,
            current_value=1500,
        )
        # Validate against TierCapError schema
        parsed = TierCapError(**detail)
        assert parsed.error == "variable_limit_exceeded"
        assert parsed.message == "Too many variables"
        assert parsed.current_plan == "free"
        assert parsed.limit == 1000
        assert parsed.current_value == 1500
        assert parsed.upgrade_to == "Starter"
        assert parsed.upgrade_url == "/billing"

    def test_feature_gate_error_has_all_fields(self):
        detail = tier_cap_detail(
            error="feature_not_available",
            message="Feature not available",
            current_plan="free",
            limit="llm_assistant",
        )
        parsed = TierCapError(**detail)
        assert parsed.error == "feature_not_available"
        assert parsed.limit == "llm_assistant"
        assert parsed.current_value is None


# PlanSettings is gone; plan config lives in platform_settings DB table.
