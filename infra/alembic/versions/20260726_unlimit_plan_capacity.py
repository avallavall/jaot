"""Drop the per-plan capacity ceilings on already-seeded installs (D-21).

JAOT was sold in tiers before ADR-008 removed billing, and the plan limits kept that
shape: a cap on model size, on solve time, on solves per day. On self-hosted open
source those numbers are ours to stop choosing — an operator running JAOT on their own
hardware decides what it can take. The registry defaults are now ``0`` (unlimited), but
the 20260327 seed runs ON CONFLICT DO NOTHING, so editing the registry alone never
reaches an install that has already been seeded. This is that UPDATE.

Capacity only. The per-plan RATE limits (requests/minute, requests/day) are deliberately
left alone: they bound frequency, not capacity, and they are what keeps a runaway client
from hammering an instance. An operator who wants those gone can zero them in the admin
panel — 0 now means unlimited there too, and no longer means "no requests allowed".

Data-only, and reversible: downgrade restores the values these settings shipped with.

Revision ID: 20260726_unlimit_capacity
Revises: 20260726_index_fks
Create Date: 2026-07-26
"""

from alembic import op
from sqlalchemy import text

revision = "20260726_unlimit_capacity"
down_revision = "20260726_index_fks"
branch_labels = None
depends_on = None

_PLANS = ("free", "starter", "pro", "business")

#: (field, old value per plan) — the caps as they were seeded before this migration.
_FIELDS: dict[str, dict[str, str]] = {
    "max_variables": {
        "free": "10000000",
        "starter": "100000",
        "pro": "1000000",
        "business": "10000000",
    },
    "max_solve_time_seconds": dict.fromkeys(_PLANS, "86400"),
    "max_daily_solves": dict.fromkeys(_PLANS, "100000"),
    "max_cron_schedules": {
        "free": "50",
        "starter": "5",
        "pro": "15",
        "business": "50",
    },
}


def _set(values: list[tuple[str, str]]) -> None:
    conn = op.get_bind()
    for key, value in values:
        conn.execute(
            text(
                "UPDATE platform_settings"
                " SET value = :value, updated_at = NOW(), updated_by = 'unlimit_capacity_oss'"
                " WHERE key = :key"
            ),
            {"key": key, "value": value},
        )


def upgrade() -> None:
    _set([(f"plan_{plan}_{field}", "0") for field in _FIELDS for plan in _PLANS])


def downgrade() -> None:
    _set([(f"plan_{plan}_{field}", old[plan]) for field, old in _FIELDS.items() for plan in _PLANS])
