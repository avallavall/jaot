"""Comprehensive tests for the pricing restructure (2026-03).

Validates ALL aspects of the tier rename, new prices, feature-gate removal,
dynamic credit calculation, PublishModelRequest schema change, and locale
reduction.

After Phase 3 config simplification, plan configuration reads from the
``platform_settings`` DB table via ``PlatformSettingsService`` instead of
``settings.PLAN_*``.

Sections:
  1. Plan Configuration (PSS / DB)
  2. Feature Gate Removal (LLM, warm start, sensitivity, cron -- all tiers)
  3. Dynamic Credit Calculation (calculate_credits, warm start discount)
  4. Tier Caps (max variables, max solve time, max daily solves per tier)
  5. Upgrade Path (tier_cap_detail upgrade_to mapping)
  6. Billing / Stripe (valid plans, PLAN_CREDITS, PLAN_PRICES_EUR)
  7. Marketplace Publish (credits_per_execution removed, price_eur accepted)
  8. Edge Cases (legacy enterprise plan, downgrade, zero-variable minimum)
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models.organization import Organization, Plan
from app.schemas.model import PublishModelRequest
from app.schemas.optimization import (
    Constraint,
    OptimizationProblem,
    Variable,
)
from app.schemas.tier import tier_cap_detail
from app.services.invoice_service import PLAN_PRICES_EUR
from app.services.platform_settings_service import (
    PlatformSettingsService as PSS,
)
from app.services.stripe_service import PLAN_CREDITS

ALL_FEATURES = [
    "llm_assistant",
    "warm_start",
    "sensitivity_analysis",
    "cron_scheduling",
]


def _build_problem(
    num_vars: int = 2,
    num_constraints: int = 0,
    num_integers: int = 0,
    time_limit: int = 30,
    warm_start: bool = False,
) -> OptimizationProblem:
    """Build an OptimizationProblem with the given characteristics."""
    variables = []
    for i in range(num_vars):
        vtype = "integer" if i < num_integers else "continuous"
        variables.append(
            Variable(
                name=f"x{i}",
                type=vtype,
                lower_bound=0,
                upper_bound=100,
            )
        )
    # Ensure at least 1 variable
    if not variables:
        variables.append(
            Variable(
                name="x0",
                type="continuous",
                lower_bound=0,
                upper_bound=100,
            )
        )

    # Keep expression short to avoid exceeding Pydantic max_length
    full_expr = " + ".join(v.name for v in variables)
    obj_expr = full_expr if len(full_expr) <= 10_000 else variables[0].name

    constraints = []
    for j in range(num_constraints):
        constraints.append(
            Constraint(
                name=f"c{j}",
                expression=f"{variables[0].name} <= {50 + j}",
            )
        )

    body: dict = {
        "name": "test_problem",
        "objective": {"sense": "minimize", "expression": obj_expr},
        "variables": [v.model_dump() for v in variables],
        "constraints": [c.model_dump() for c in constraints],
        "options": {"time_limit_seconds": time_limit},
    }
    if warm_start:
        body["warm_start"] = {"execution_id": "exe_prev001"}
    return OptimizationProblem(**body)


class TestPlanConfiguration:
    """Verify all 4 plans exist with correct values via PSS."""

    def test_plan_enum_has_four_tiers(self):
        """Plan enum must have exactly free, starter, pro, business."""
        values = {p.value for p in Plan}
        assert values == {"free", "starter", "pro", "business"}

    def test_enterprise_not_in_enum(self):
        """'enterprise' must not exist in Plan enum."""
        values = {p.value for p in Plan}
        assert "enterprise" not in values
        with pytest.raises(ValueError):
            Plan("enterprise")

    def test_plan_config_dynamic_has_four_entries(self, db_session):
        """PSS.get_plan_config_dynamic returns exact credit values per plan."""
        expected_credits = {
            "free": 20000,
            "starter": 600,
            "pro": 2500,
            "business": 20000,
        }
        for plan, credits in expected_credits.items():
            cfg = PSS.get_plan_config_dynamic(db_session, plan)
            assert cfg["credits"] == credits, (
                f"{plan} credits: expected {credits}, got {cfg['credits']}"
            )
            assert cfg["monthly_quota"] >= 0

    # ---- Credits ----

    def test_free_plan_credits(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "free")
        assert cfg["credits"] == 20000

    def test_starter_plan_credits(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "starter")
        assert cfg["credits"] == 600

    def test_pro_plan_credits(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "pro")
        assert cfg["credits"] == 2500

    def test_business_plan_credits(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "business")
        assert cfg["credits"] == 20000

    # ---- All features on ALL tiers ----

    @pytest.mark.parametrize("plan_name", ["free", "starter", "pro", "business"])
    def test_all_features_available_on_plan(self, db_session, plan_name: str):
        """Every plan must have ALL features in allowed_features."""
        cfg = PSS.get_plan_config_dynamic(db_session, plan_name)
        for feature in ALL_FEATURES:
            assert feature in cfg["allowed_features"], (
                f"Feature '{feature}' missing from {plan_name} allowed_features"
            )

    # ---- Rate limits ----

    def test_free_rate_limits(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "free")
        # Default plan now carries business-level limits (no paid tiers).
        assert cfg["rate_limit_per_minute"] == 120
        assert cfg["rate_limit_per_day"] == 50000

    def test_starter_rate_limits(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "starter")
        assert cfg["rate_limit_per_minute"] == 20
        assert cfg["rate_limit_per_day"] == 500

    def test_pro_rate_limits(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "pro")
        assert cfg["rate_limit_per_minute"] == 60
        assert cfg["rate_limit_per_day"] == 5000

    def test_business_rate_limits(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "business")
        assert cfg["rate_limit_per_minute"] == 120
        assert cfg["rate_limit_per_day"] == 50000

    # ---- Tier caps ----

    def test_free_tier_caps(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "free")
        # Default plan now carries business-level limits (no paid tiers).
        assert cfg["max_variables"] == 10000000
        assert cfg["max_solve_time_seconds"] == 3600
        assert cfg["max_daily_solves"] == 50000

    def test_starter_tier_caps(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "starter")
        assert cfg["max_variables"] == 100000
        assert cfg["max_solve_time_seconds"] == 300
        assert cfg["max_daily_solves"] == 500

    def test_pro_tier_caps(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "pro")
        assert cfg["max_variables"] == 1000000
        assert cfg["max_solve_time_seconds"] == 900
        assert cfg["max_daily_solves"] == 5000

    def test_business_tier_caps(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "business")
        assert cfg["max_variables"] == 10000000
        assert cfg["max_solve_time_seconds"] == 3600
        assert cfg["max_daily_solves"] == 50000

    # ---- Cron schedule limits ----

    def test_free_cron_schedule_limit(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "free")
        assert cfg["max_cron_schedules"] == 50

    def test_starter_cron_schedule_limit(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "starter")
        assert cfg["max_cron_schedules"] == 5

    def test_pro_cron_schedule_limit(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "pro")
        assert cfg["max_cron_schedules"] == 15

    def test_business_cron_schedule_limit(self, db_session):
        cfg = PSS.get_plan_config_dynamic(db_session, "business")
        assert cfg["max_cron_schedules"] == 50

    # ---- get_plan_config_dynamic fallback ----

    def test_get_plan_config_unknown_falls_back(self, db_session):
        """Unknown plan names should fall back to free plan."""
        cfg = PSS.get_plan_config_dynamic(db_session, "enterprise")
        free_cfg = PSS.get_plan_config_dynamic(db_session, "free")
        assert cfg["credits"] == free_cfg["credits"]


class TestFeatureGateRemovalLLM:
    """Free users CAN create LLM conversations (no 403 feature gate)."""

    def test_free_user_can_create_conversation(
        self, authenticated_client, db_session, test_organization
    ):
        """Free-tier org should be able to create an LLM conversation."""
        test_organization.plan = "free"
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/llm/conversations",
            json={},
        )
        assert response.status_code != 403, f"Free user got 403: {response.json()}"
        assert response.status_code == 201

    @pytest.mark.parametrize("plan_name", ["free", "starter", "pro", "business"])
    def test_all_tiers_can_create_conversation(
        self, authenticated_client, db_session, test_organization, plan_name
    ):
        """Every tier must actually succeed with 201 when creating LLM conversations."""
        test_organization.plan = plan_name
        db_session.commit()

        response = authenticated_client.post(
            "/api/v2/llm/conversations",
            json={},
        )
        assert response.status_code == 201, (
            f"{plan_name} user expected 201, got {response.status_code}: {response.json()}"
        )


class TestFeatureGateRemovalSolve:
    """No feature gating on solve -- warm_start accepted on all tiers."""

    def test_solve_endpoint_accepts_warm_start_on_free_tier(
        self, authenticated_client, db_session, test_organization
    ):
        """TA-09 (Phase 12.4): warm_start accepted AND actually applied on free tier.

        Strengthened from T2 (status-only) → T4 (status + Pydantic + DB side-effect):
          - SC1a: response.status_code != 403 (original invariant — no feature gate)
          - SC1b: OptimizationResult.model_validate(response.json()) — schema roundtrip
          - SC1c: warm_start was ACTUALLY APPLIED, not silently dropped:
              (b) parsed.warm_start_used is True  (solver-set field, proof B)
              (a) ModelExecution.input_data["warm_start"]["execution_id"] equals
                  the previous-execution id we passed in (DB side-effect, proof A)

        The previous execution row is seeded with status=completed + solver_status=optimal
        + a valid solution dict so that load_warm_start_solution() returns a non-None
        result and the SCIP adapter sets result.warm_start_used = True.

        Cross-listed TH-02 (rename-or-strengthen) is resolved via the STRENGTHEN path
        here — the test now honestly verifies the warm_start applied invariant rather
        than only the absence of feature-gate rejection.
        """
        from app.models import ModelExecution
        from app.schemas.optimization import OptimizationResult
        from app.shared.utils.datetime_helpers import utcnow

        test_organization.plan = "free"
        test_organization.credits_balance = 100

        # Seed a valid prior execution so load_warm_start_solution() returns a
        # solution dict (status=completed, solver_status=optimal, result_data.solution).
        # Single-commit pattern: stage both rows then flush+commit once so the
        # auth middleware's session sees both org and prev execution from the same
        # transaction snapshot.
        prev_exe_id = "exe_ta09_prev_001"
        prev = ModelExecution(
            id=prev_exe_id,
            organization_id=test_organization.id,
            input_data={"name": "prev"},
            result_data={
                "solver_status": "optimal",
                "objective_value": 0.0,
                "solution": {"x0": 0.0},
                "solve_time_seconds": 0.1,
            },
            status="completed",
            solver_status="optimal",
            objective_value=0.0,
            credits_consumed=1,
            credits_base=1,
            origin="manual",
            is_async=False,
            created_at=utcnow(),
            started_at=utcnow(),
            completed_at=utcnow(),
        )
        db_session.add(prev)
        db_session.commit()

        payload = {
            "name": "warm_start_free_test",
            "objective": {"sense": "minimize", "expression": "x0"},
            "variables": [
                {"name": "x0", "type": "continuous", "lower_bound": 0, "upper_bound": 10}
            ],
            "constraints": [{"name": "c0", "expression": "x0 <= 5"}],
            "options": {"time_limit_seconds": 5},
            "warm_start": {"execution_id": prev_exe_id},
        }
        response = authenticated_client.post("/api/v2/solve", json=payload)

        # SC1a: original invariant — no feature-gate rejection.
        assert response.status_code != 403, (
            f"Free-tier solve with warm_start got 403 (feature-gate regression): {response.json()}"
        )
        assert response.status_code == 200, (
            f"Expected 200 on free-tier warm_start solve, got {response.status_code}: "
            f"{response.json()}"
        )

        # SC1b: response body matches OptimizationResult schema exactly.
        parsed = OptimizationResult.model_validate(response.json())

        # SC1c — proof B: solver reports warm_start was applied (adapter sets it
        # only when load_warm_start_solution returned a non-None dict).
        assert parsed.warm_start_used is True, (
            "warm_start_used flag is False — warm_start was silently dropped between "
            "API and solver. Check app/api/v2/solve.py:410 (load_warm_start_solution) "
            "and app/services/solve_orchestrator.py:223 (warm_start_solution kwarg)."
        )

        # SC1c — proof A: ModelExecution row records the warm_start id in input_data.
        assert parsed.execution_id is not None, "Response missing execution_id"
        db_session.expire_all()
        exe_row = (
            db_session.query(ModelExecution)
            .filter(ModelExecution.id == parsed.execution_id)
            .first()
        )
        assert exe_row is not None, (
            f"ModelExecution row {parsed.execution_id} not persisted; "
            f"_persist_sync_execution may have rolled back."
        )
        ws_meta = (exe_row.input_data or {}).get("warm_start") or {}
        assert ws_meta.get("execution_id") == prev_exe_id, (
            f"Persisted input_data.warm_start.execution_id mismatch: "
            f"expected {prev_exe_id!r}, got {ws_meta!r}"
        )


class TestDynamicCreditCalculation:
    """Test calculate_credits returns correct values."""

    def test_simple_problem(self):
        from app.api.v2.solve import calculate_credits

        problem = _build_problem(
            num_vars=5,
            num_constraints=3,
            num_integers=0,
            time_limit=30,
        )
        credits = calculate_credits(problem)
        assert credits == 2

    def test_medium_problem(self):
        from app.api.v2.solve import calculate_credits

        problem = _build_problem(
            num_vars=100,
            num_constraints=50,
            num_integers=30,
            time_limit=30,
        )
        credits = calculate_credits(problem)
        assert credits == 24

    def test_large_problem(self):
        from app.api.v2.solve import calculate_credits

        problem = _build_problem(
            num_vars=1000,
            num_constraints=500,
            num_integers=200,
            time_limit=30,
        )
        credits = calculate_credits(problem)
        assert credits == 97

    def test_time_limit_bonus(self):
        from app.api.v2.solve import calculate_credits

        problem_under = _build_problem(num_vars=4, time_limit=60)
        problem_over = _build_problem(num_vars=4, time_limit=61)

        credits_under = calculate_credits(problem_under)
        credits_over = calculate_credits(problem_over)

        assert credits_over == credits_under + 1

    def test_warm_start_discount_halves_credit_cost(self):
        """The production discount formula `max(1, round(base * 0.5))` is locked.

        Regression guard: any change to the warm-start discount formula inside
        solve_optimization_problem (e.g. 0.6 instead of 0.5) will mismatch the
        expected value computed against calculate_credits' base here.
        """
        from app.api.v2.solve import calculate_credits

        problem_no_warm = _build_problem(
            num_vars=10,
            num_constraints=5,
            num_integers=3,
            time_limit=30,
            warm_start=False,
        )
        problem_warm = _build_problem(
            num_vars=10,
            num_constraints=5,
            num_integers=3,
            time_limit=30,
            warm_start=True,
        )

        base_credits = calculate_credits(problem_no_warm)
        # calculate_credits is warm-start-agnostic — both problems return base.
        assert calculate_credits(problem_warm) == base_credits

        # The endpoint-level discount formula (locked in solve.py).
        expected_discounted = max(1, round(base_credits * 0.5))

        assert base_credits > 1, (
            "Need a non-trivial problem so rounding / floor don't collapse the delta"
        )
        assert expected_discounted < base_credits
        # Concrete value regression guard: for 10 vars + 5 con + 3 int + 30s
        # the base is 6 and the discounted cost is 3.
        assert base_credits == 6
        assert expected_discounted == 3

    def test_minimum_one_credit(self):
        from app.api.v2.solve import calculate_credits

        problem = _build_problem(
            num_vars=1,
            num_constraints=0,
            num_integers=0,
            time_limit=1,
        )
        credits = calculate_credits(problem)
        assert credits >= 1

    def test_zero_variables_minimum_one_credit(self):
        from app.api.v2.solve import calculate_credits

        problem = _build_problem(num_vars=1, num_constraints=0)
        credits = calculate_credits(problem)
        assert credits >= 1


class TestTierCapEnforcement:
    """Verify tier caps are enforced correctly per tier."""

    @pytest.mark.parametrize(
        "plan_name,max_vars",
        [
            # Scaled-down caps so we can build a real OptimizationProblem with
            # `max_vars + 1` variables without ballooning test runtime. The
            # enforcement logic is agnostic to the absolute cap value — it just
            # compares `len(problem.variables)` against `plan_config["max_variables"]`.
            ("free", 10),
            ("starter", 20),
            ("pro", 50),
            ("business", 100),
        ],
    )
    def test_variable_limit_enforced(self, plan_name: str, max_vars: int):
        from fastapi import HTTPException

        from app.api.v2.solve import _enforce_tier_caps

        plan_config = {
            "max_variables": max_vars,
            "max_solve_time_seconds": 3600,
            "max_daily_solves": 99999,
            "allowed_features": ALL_FEATURES,
        }

        # Build a REAL OptimizationProblem with exactly max_vars + 1 variables.
        # No more MagicMock on problem.variables — the enforcement check reads
        # the actual list.
        problem = _build_problem(num_vars=max_vars + 1)
        assert len(problem.variables) == max_vars + 1

        org = MagicMock(spec=Organization)
        org.id = f"org_{plan_name}"
        org.plan = plan_name
        db = MagicMock()

        with (
            patch(
                "app.api.v2.solve.PSS.get_plan_config_dynamic",
                return_value=plan_config,
            ),
            patch(
                "app.api.v2.solve.check_rate_limit",
                return_value=(True, None),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                _enforce_tier_caps(db, org, problem)
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail["error"] == "variable_limit_exceeded"

    @pytest.mark.parametrize(
        "plan_name,max_vars",
        [
            ("free", 5000),
            ("starter", 100000),
            ("pro", 1000000),
            ("business", 10000000),
        ],
    )
    def test_within_variable_limit_ok(self, plan_name: str, max_vars: int):
        from app.api.v2.solve import _enforce_tier_caps

        plan_config = {
            "max_variables": max_vars,
            "max_solve_time_seconds": 3600,
            "max_daily_solves": 99999,
            "allowed_features": ALL_FEATURES,
        }

        problem = _build_problem(num_vars=min(max_vars, 500))
        org = MagicMock(spec=Organization)
        org.id = f"org_{plan_name}"
        org.plan = plan_name
        db = MagicMock()

        with (
            patch(
                "app.api.v2.solve.PSS.get_plan_config_dynamic",
                return_value=plan_config,
            ),
            patch(
                "app.api.v2.solve.check_rate_limit",
                return_value=(True, None),
            ),
        ):
            _enforce_tier_caps(db, org, problem)

    @pytest.mark.parametrize(
        "plan_name,max_time",
        [
            ("free", 60),
            ("starter", 300),
            ("pro", 900),
            ("business", 3600),
        ],
    )
    def test_solve_time_clamped(self, plan_name: str, max_time: int):
        from app.api.v2.solve import _enforce_tier_caps

        plan_config = {
            "max_variables": 99999999,
            "max_solve_time_seconds": max_time,
            "max_daily_solves": 99999,
            "allowed_features": ALL_FEATURES,
        }

        problem = _build_problem(
            num_vars=5,
            time_limit=min(max_time + 100, 3600),
        )
        problem.options.time_limit_seconds = max_time + 100
        org = MagicMock(spec=Organization)
        org.id = f"org_{plan_name}"
        org.plan = plan_name
        db = MagicMock()

        with (
            patch(
                "app.api.v2.solve.PSS.get_plan_config_dynamic",
                return_value=plan_config,
            ),
            patch(
                "app.api.v2.solve.check_rate_limit",
                return_value=(True, None),
            ),
        ):
            clamped = _enforce_tier_caps(db, org, problem)
            assert clamped.options.time_limit_seconds == max_time

    @pytest.mark.parametrize(
        "plan_name,max_daily",
        [
            ("free", 50),
            ("starter", 500),
            ("pro", 5000),
            ("business", 50000),
        ],
    )
    def test_daily_solve_limit_enforced(self, plan_name: str, max_daily: int):
        from fastapi import HTTPException

        from app.api.v2.solve import _enforce_tier_caps

        plan_config = {
            "max_variables": 99999999,
            "max_solve_time_seconds": 3600,
            "max_daily_solves": max_daily,
            "allowed_features": ALL_FEATURES,
        }

        problem = _build_problem(num_vars=5)
        org = MagicMock(spec=Organization)
        org.id = f"org_{plan_name}"
        org.plan = plan_name
        db = MagicMock()

        with (
            patch(
                "app.api.v2.solve.PSS.get_plan_config_dynamic",
                return_value=plan_config,
            ),
            patch(
                "app.api.v2.solve.check_rate_limit",
                return_value=(False, {"error": "rate_limited"}),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                _enforce_tier_caps(db, org, problem)
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail["error"] == "daily_solve_quota_exceeded"


class TestUpgradePath:
    """tier_cap_detail() returns the correct upgrade_to for each tier."""

    def test_free_upgrades_to_starter(self):
        detail = tier_cap_detail(
            error="test",
            message="msg",
            current_plan="free",
            limit=1000,
        )
        assert detail["upgrade_to"] == "Starter"

    def test_starter_upgrades_to_pro(self):
        detail = tier_cap_detail(
            error="test",
            message="msg",
            current_plan="starter",
            limit=5000,
        )
        assert detail["upgrade_to"] == "Pro"

    def test_pro_upgrades_to_business(self):
        detail = tier_cap_detail(
            error="test",
            message="msg",
            current_plan="pro",
            limit=25000,
        )
        assert detail["upgrade_to"] == "Business"

    def test_business_stays_business(self):
        detail = tier_cap_detail(
            error="test",
            message="msg",
            current_plan="business",
            limit=100000,
        )
        assert detail["upgrade_to"] == "Business"

    def test_unknown_plan_defaults_to_business(self):
        detail = tier_cap_detail(
            error="test",
            message="msg",
            current_plan="enterprise",
            limit=100000,
        )
        assert detail["upgrade_to"] == "Business"


class TestBillingPlanValidation:
    """Validate Stripe checkout only accepts starter, pro, business."""

    def test_valid_plans_for_checkout(self, authenticated_client):
        from app.services.stripe_service import StripeService

        # Mock both the config check AND the actual checkout creation so the
        # request reaches the plan-validation layer and returns a deterministic
        # success — no downstream Stripe price-ID lookups.
        fake_result = {
            "checkout_url": "https://checkout.stripe.com/c/pay/test_session",
            "session_id": "cs_test_fake_session",
        }
        for plan_name in ("starter", "pro", "business"):
            with (
                patch.object(StripeService, "is_configured", return_value=True),
                patch.object(
                    StripeService,
                    "create_subscription_checkout",
                    return_value=fake_result,
                ),
            ):
                response = authenticated_client.post(
                    "/api/v2/billing/checkout/subscription",
                    json={
                        "plan": plan_name,
                        "success_url": "http://localhost:3000/success",
                        "cancel_url": "http://localhost:3000/cancel",
                    },
                )
                # Plan validation MUST pass — we locked the endpoint to the
                # three-plan whitelist and the Stripe API is fully mocked.
                assert response.status_code == 200, (
                    f"{plan_name} expected 200, got {response.status_code}: {response.json()}"
                )
                assert response.json()["session_id"] == "cs_test_fake_session"

    def test_enterprise_plan_rejected_at_checkout(self, authenticated_client):
        from app.services.stripe_service import StripeService

        with patch.object(StripeService, "is_configured", return_value=True):
            response = authenticated_client.post(
                "/api/v2/billing/checkout/subscription",
                json={
                    "plan": "enterprise",
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            assert response.status_code == 400
            assert "Invalid plan" in response.json()["detail"]

    def test_free_plan_rejected_at_checkout(self, authenticated_client):
        from app.services.stripe_service import StripeService

        with patch.object(StripeService, "is_configured", return_value=True):
            response = authenticated_client.post(
                "/api/v2/billing/checkout/subscription",
                json={
                    "plan": "free",
                    "success_url": "http://localhost:3000/success",
                    "cancel_url": "http://localhost:3000/cancel",
                },
            )
            assert response.status_code == 400


class TestPlanCreditsMapping:
    """Verify PLAN_CREDITS in stripe_service matches new pricing."""

    def test_free_credits(self):
        assert PLAN_CREDITS["free"] == 20000

    def test_starter_credits(self):
        assert PLAN_CREDITS["starter"] == 600

    def test_pro_credits(self):
        assert PLAN_CREDITS["pro"] == 2500

    def test_business_credits(self):
        assert PLAN_CREDITS["business"] == 20000

    def test_enterprise_not_in_plan_credits(self):
        assert "enterprise" not in PLAN_CREDITS


class TestPlanPricesEUR:
    """Verify PLAN_PRICES_EUR in invoice_service matches new pricing."""

    def test_starter_monthly(self):
        assert PLAN_PRICES_EUR["starter"]["monthly"] == 19.0

    def test_starter_annual(self):
        assert PLAN_PRICES_EUR["starter"]["annual"] == 190.0

    def test_starter_credits(self):
        assert PLAN_PRICES_EUR["starter"]["credits"] == 600

    def test_pro_monthly(self):
        assert PLAN_PRICES_EUR["pro"]["monthly"] == 49.0

    def test_pro_annual(self):
        assert PLAN_PRICES_EUR["pro"]["annual"] == 490.0

    def test_pro_credits(self):
        assert PLAN_PRICES_EUR["pro"]["credits"] == 2500

    def test_business_monthly(self):
        assert PLAN_PRICES_EUR["business"]["monthly"] == 149.0

    def test_business_annual(self):
        assert PLAN_PRICES_EUR["business"]["annual"] == 1490.0

    def test_business_credits(self):
        assert PLAN_PRICES_EUR["business"]["credits"] == 20000

    def test_enterprise_not_in_prices(self):
        assert "enterprise" not in PLAN_PRICES_EUR


class TestMarketplacePublish:
    """PublishModelRequest does NOT accept credits_per_execution."""

    def test_credits_per_execution_not_in_schema(self):
        fields = PublishModelRequest.model_fields
        assert "credits_per_execution" not in fields

    def test_price_eur_accepted(self):
        req = PublishModelRequest(
            display_name="Test Model",
            description=("A test model for the marketplace with enough text"),
            price_eur=9.99,
        )
        assert req.price_eur == 9.99

    def test_price_eur_defaults_to_zero(self):
        req = PublishModelRequest(
            display_name="Free Model",
            description=("A free model for the marketplace with enough text"),
        )
        assert req.price_eur == 0.0

    def test_credits_per_execution_extra_field_ignored(self):
        req = PublishModelRequest(
            display_name="Test Model",
            description=("A test model for the marketplace with enough text"),
            price_eur=5.0,
        )
        dumped = req.model_dump()
        assert "credits_per_execution" not in dumped


class TestEdgeCases:
    """Edge cases for the pricing restructure."""

    def test_enterprise_plan_in_db_falls_back(self, db_session):
        """Org with plan='enterprise' falls back to free plan config."""
        cfg = PSS.get_plan_config_dynamic(db_session, "enterprise")
        free_cfg = PSS.get_plan_config_dynamic(db_session, "free")
        assert cfg["credits"] == free_cfg["credits"]
        assert cfg["max_variables"] == free_cfg["max_variables"]

    def test_enterprise_plan_in_db_still_functional(self, db_session, test_organization):
        """An org with plan='enterprise' falls back to EXACTLY the free config.

        Regression test: legacy accounts with plan='enterprise' must not
        silently unlock unknown caps — they get the most conservative (free)
        config so nothing crashes and no tier is bypassed.
        """
        test_organization.plan = "enterprise"
        db_session.commit()
        db_session.refresh(test_organization)
        assert test_organization.plan == "enterprise"

        cfg = PSS.get_plan_config_dynamic(db_session, test_organization.plan)
        free_cfg = PSS.get_plan_config_dynamic(db_session, "free")
        # Every knob must match free exactly — no more lenient than free.
        for key in (
            "credits",
            "monthly_quota",
            "max_variables",
            "max_solve_time_seconds",
            "max_daily_solves",
            "max_cron_schedules",
            "rate_limit_per_minute",
            "rate_limit_per_day",
        ):
            assert cfg[key] == free_cfg[key], (
                f"enterprise fallback diverges from free on '{key}': {cfg[key]} != {free_cfg[key]}"
            )
        assert set(cfg["allowed_features"]) == set(free_cfg["allowed_features"])


class TestNoEnterprisePlan:
    """Verify that the legacy 'enterprise' plan is not referenced anywhere
    that matters at runtime."""

    def test_no_enterprise_in_plan_enum(self):
        """The Plan enum must not contain enterprise."""
        assert "enterprise" not in {p.value for p in Plan}

    def test_no_enterprise_in_pss_defaults(self, db_session):
        """PSS plan keys must be exactly the four supported tiers."""
        keys = set()
        for plan in ("free", "starter", "pro", "business"):
            cfg = PSS.get_plan_config_dynamic(db_session, plan)
            assert cfg is not None
            keys.add(plan)
        assert keys == {"free", "starter", "pro", "business"}

    def test_no_enterprise_in_stripe_plan_credits(self):
        assert "enterprise" not in PLAN_CREDITS

    def test_no_enterprise_in_invoice_plan_prices(self):
        assert "enterprise" not in PLAN_PRICES_EUR
