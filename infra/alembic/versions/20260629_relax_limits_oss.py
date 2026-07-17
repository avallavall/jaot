"""Relax business/usage limits for open-source self-hosted deployments.

Data-only migration. The platform is no longer a commercial SaaS, so the
per-solver credit multipliers and the time/usage caps that existed to meter
paid usage are relaxed. Updates the already-seeded ``platform_settings`` rows
to the new registry defaults (the 20260327 seed runs ON CONFLICT DO NOTHING,
so editing the registry default alone never reaches existing installs).

Changes (new <- old):
  - pricing.solver_multiplier.highs:        1.0  <- 1.2
  - pricing.solver_multiplier.hexaly:       1.0  <- 5.0   (SCIP already 1.0)
  - SOLVER_TIMEOUT_SECONDS (sync wall-clock): 120 <- 30
  - hexaly_default_time_limit_seconds:      300  <- 60
  - EXECUTION_REAPER_RUNNING_MAX_SECONDS:   172800 <- 7200
  - plan_*_max_solve_time_seconds:          86400 (24h) <- 3600/900/300
  - plan_*_max_daily_solves:                100000 <- 50000/5000/500
  - LLM_RATE_LIMIT_PER_MINUTE:              300  <- 60
  - LLM_RATE_LIMIT_PER_DAY:                 5000 <- 500
  - LLM_MONTHLY_BUDGET_EUR:                 50.0 <- 20.0

The schema-level solve time limit (default 60s -> 300s, cap 3600s -> 86400s)
and the body/import/attachment size caps live in code (not platform_settings)
and ship with the same release; they need no data migration.

Revision ID: 20260629_relax_limits
Revises: 20260629_model_projects
Create Date: 2026-06-29
"""

from alembic import op
from sqlalchemy import text

revision = "20260629_relax_limits"
down_revision = "20260629_model_projects"
branch_labels = None
depends_on = None

# (key, new_value, old_value)
_CHANGES: list[tuple[str, str, str]] = [
    ("pricing.solver_multiplier.highs", "1.0", "1.2"),
    ("pricing.solver_multiplier.hexaly", "1.0", "5.0"),
    ("SOLVER_TIMEOUT_SECONDS", "120", "30"),
    ("hexaly_default_time_limit_seconds", "300", "60"),
    ("EXECUTION_REAPER_RUNNING_MAX_SECONDS", "172800", "7200"),
    ("plan_free_max_solve_time_seconds", "86400", "3600"),
    ("plan_starter_max_solve_time_seconds", "86400", "300"),
    ("plan_pro_max_solve_time_seconds", "86400", "900"),
    ("plan_business_max_solve_time_seconds", "86400", "3600"),
    ("plan_free_max_daily_solves", "100000", "50000"),
    ("plan_starter_max_daily_solves", "100000", "500"),
    ("plan_pro_max_daily_solves", "100000", "5000"),
    ("plan_business_max_daily_solves", "100000", "50000"),
    ("LLM_RATE_LIMIT_PER_MINUTE", "300", "60"),
    ("LLM_RATE_LIMIT_PER_DAY", "5000", "500"),
    ("LLM_MONTHLY_BUDGET_EUR", "50.0", "20.0"),
]


def _apply(values: list[tuple[str, str]]) -> None:
    conn = op.get_bind()
    for key, value in values:
        conn.execute(
            text(
                "UPDATE platform_settings"
                " SET value = :value, updated_at = NOW(), updated_by = 'limit_relax_oss'"
                " WHERE key = :key"
            ),
            {"key": key, "value": value},
        )


def upgrade() -> None:
    _apply([(key, new) for key, new, _old in _CHANGES])


def downgrade() -> None:
    _apply([(key, old) for key, _new, old in _CHANGES])
