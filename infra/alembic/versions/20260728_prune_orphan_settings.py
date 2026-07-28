"""Delete the platform_settings rows no code reads any more (D-22).

Three waves of change left rows behind, because the additive-only rule stops
code from reading a setting but nothing ever deleted the row:

* **ADR-008 removed billing and credits** — Stripe price ids, the credit
  economy, the marketplace commission and the featured-placement price list.
* **D-21 removed the capacity caps**, and the **1.9 panel review** collapsed the
  four ``plan_*`` tiers into one ``instance_*`` profile and retired the settings
  the runtime reads from ``.env`` (HOST/PORT/WORKERS, the three CELERY_*,
  DATABASE_URL) or read nowhere at all.

98 rows on the reference install. They are invisible in the admin panel — it
renders the registry, not the table — so this is housekeeping, not a fix.

**Why this is not the contract-release work it was deferred to.** That window
exists for schema ``DROP``s: rollback restores container images, not schema, so
an image that still selects a dropped column crashes. Deleting *rows* has no
such failure mode. An older image that declares any of these keys re-seeds it
from its own registry on the next boot (``_ensure_settings_seeded`` in
``app/main.py``), and the numbers that mattered — an operator's own plan limits
— were already carried into ``instance_*`` by ``20260727_instance_limits``.
What a rollback loses is a customised value on a row nothing reads; that is a
cost worth naming, and it is not the crash the deferral was protecting against.

Revision ID: 20260728_prune_orphan_settings
Revises: 20260727_instance_limits
Create Date: 2026-07-28
"""

from alembic import op
from sqlalchemy import text

revision = "20260728_prune_orphan_settings"
down_revision = "20260727_instance_limits"
branch_labels = None
depends_on = None

#: The four paid tiers, seven limit fields each, plus the price and credit
#: fields. Replaced by the seven ``instance_*`` keys.
_TIER_KEYS = (
    "plan_business_allowed_features",
    "plan_business_annual_price",
    "plan_business_credits",
    "plan_business_max_cron_schedules",
    "plan_business_max_daily_solves",
    "plan_business_max_solve_time_seconds",
    "plan_business_max_variables",
    "plan_business_monthly_price",
    "plan_business_monthly_quota",
    "plan_business_rate_limit_per_day",
    "plan_business_rate_limit_per_minute",
    "plan_free_allowed_features",
    "plan_free_credits",
    "plan_free_max_cron_schedules",
    "plan_free_max_daily_solves",
    "plan_free_max_solve_time_seconds",
    "plan_free_max_variables",
    "plan_free_monthly_price",
    "plan_free_monthly_quota",
    "plan_free_rate_limit_per_day",
    "plan_free_rate_limit_per_minute",
    "plan_pro_allowed_features",
    "plan_pro_annual_price",
    "plan_pro_credits",
    "plan_pro_max_cron_schedules",
    "plan_pro_max_daily_solves",
    "plan_pro_max_solve_time_seconds",
    "plan_pro_max_variables",
    "plan_pro_monthly_price",
    "plan_pro_monthly_quota",
    "plan_pro_rate_limit_per_day",
    "plan_pro_rate_limit_per_minute",
    "plan_starter_allowed_features",
    "plan_starter_annual_price",
    "plan_starter_credits",
    "plan_starter_max_cron_schedules",
    "plan_starter_max_daily_solves",
    "plan_starter_max_solve_time_seconds",
    "plan_starter_max_variables",
    "plan_starter_monthly_price",
    "plan_starter_monthly_quota",
    "plan_starter_rate_limit_per_day",
    "plan_starter_rate_limit_per_minute",
)

#: Billing, credits and paid marketplace placement — all removed by ADR-008.
_BILLING_KEYS = (
    "CRON_DEFAULT_CREDIT_ESTIMATE",
    "HOLDING_PERIOD_DAYS",
    "LLM_CREDIT_COST_PER_MESSAGE",
    "LOW_CREDITS_THRESHOLD_PCT",
    "MONETIZATION_ENABLED",
    "PROBLEM_TYPE_MANUAL_CREDIT_ADDITION",
    "STRIPE_PRICE_BUSINESS_MONTHLY",
    "STRIPE_PRICE_PRO_MONTHLY",
    "STRIPE_PRICE_STARTER_MONTHLY",
    "STRIPE_PRICE_TOPUP_2000",
    "STRIPE_PRICE_TOPUP_20000",
    "STRIPE_PRICE_TOPUP_500",
    "STRIPE_PRICE_TOPUP_5000",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "featured_placement_category_spotlight_14d",
    "featured_placement_category_spotlight_30d",
    "featured_placement_category_spotlight_7d",
    "featured_placement_homepage_carousel_14d",
    "featured_placement_homepage_carousel_30d",
    "featured_placement_homepage_carousel_7d",
    "featured_placement_promoted_badge_14d",
    "featured_placement_promoted_badge_30d",
    "featured_placement_promoted_badge_7d",
    "featured_placement_search_boost_14d",
    "featured_placement_search_boost_30d",
    "featured_placement_search_boost_7d",
    "marketplace_commission_rate",
    "pricing.solver_multiplier.hexaly",
    "pricing.solver_multiplier.highs",
    "pricing.solver_multiplier.scip",
)

#: Retired by the 1.9 panel review: either nothing read them, or the runtime
#: reads the value from the environment before a DB session exists, so the
#: panel was offering an edit that could not take effect.
_RETIRED_KEYS = (
    "API_DESCRIPTION",
    "API_KEY_ACTIVE_BY_DEFAULT",
    "API_KEY_DEFAULT_EXPIRY_DAYS",
    "CELERY_DEFAULT_RETRY_DELAY",
    "CELERY_MAX_RETRIES",
    "CELERY_RESULT_EXPIRES",
    "DATABASE_URL",
    "DEFAULT_PLAN",
    "DEFAULT_USER_ROLE",
    "GZIP_MINIMUM_SIZE",
    "HOST",
    "ID_PREFIX_API_KEY",
    "ID_PREFIX_RATE_LIMIT_EVENT",
    "ID_PREFIX_USAGE_RECORD",
    "LLM_THINKING_BUDGET_TOKENS",
    "METRICS_DEFAULT_RECENT_LIMIT",
    "METRICS_MAX_RECENT_REQUESTS",
    "PORT",
    "RAG_AB_TEST_PERCENTAGE",
    "RATE_LIMIT_DAILY_WINDOW_SECONDS",
    "RATE_LIMIT_WINDOW_SECONDS",
    "SOLVER_TIMEOUT_SECONDS",
    "SOLVER_VIOLATION_TOLERANCE",
    "WORKERS",
)

ORPHAN_KEYS = (*_TIER_KEYS, *_BILLING_KEYS, *_RETIRED_KEYS)


def upgrade() -> None:
    conn = op.get_bind()
    # An explicit list, not "everything the registry does not declare": the
    # registry is code that keeps changing, so a blanket delete would mean this
    # migration removes a different set of rows depending on when it runs.
    conn.execute(
        text("DELETE FROM platform_settings WHERE key = ANY(:keys)"),
        {"keys": list(ORPHAN_KEYS)},
    )


def downgrade() -> None:
    """Deliberately a no-op.

    The values are gone and inventing defaults here would be worse than the
    gap: whichever image the rollback lands on re-seeds every key its own
    registry declares, with that release's defaults, on the next boot. Rows no
    release declares stay absent, which is exactly what this migration was for.
    """
