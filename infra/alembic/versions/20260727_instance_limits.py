"""Collapse the four plan tiers into one instance limit profile (1.9 panel review).

JAOT was sold in tiers before ADR-008 removed billing. What survived was four
LIMIT profiles — free / starter / pro / business, seven fields each — and after
D-21 relaxed the caps they were identical apart from the rate limits. A
self-hosted instance has one operator and one machine, so it has one set of
limits. The admin panel rendered all 28 keys TWICE, once as a tier table and
once as loose fields.

The registry now declares seven ``instance_*`` settings, and the startup
self-heal would seed them with the shipped defaults. That would silently
discard an operator's own numbers, so this migration carries them across.

**Which tier wins:** for each field, the value that restricts NO existing
organization — 0 (unlimited) if any tier in use has it, otherwise the largest.
``allowed_features`` takes the union, so no organization loses a feature it
could use yesterday. Only tiers actually referenced by an organization count;
a fresh install falls back to ``free``, the plan every signup got.

Additive and data-only: the ``plan_*`` rows are left untouched for the rollback
window (images roll back, schema does not). Removing them belongs to the
contract-release pass. Downgrade deletes only the rows this migration created.

Revision ID: 20260727_instance_limits
Revises: 20260726_listing_tallies
Create Date: 2026-07-27
"""

import json

from alembic import op
from sqlalchemy import text

revision = "20260727_instance_limits"
down_revision = "20260726_listing_tallies"
branch_labels = None
depends_on = None

_NUMERIC_FIELDS = (
    "rate_limit_per_minute",
    "rate_limit_per_day",
    "max_solve_time_seconds",
    "max_variables",
    "max_daily_solves",
    "max_cron_schedules",
)
_ALL_FIELDS = (*_NUMERIC_FIELDS, "allowed_features")

_KNOWN_TIERS = ("free", "starter", "pro", "business")

#: Registry defaults, used when an install has no plan_* row for a field at all.
_FALLBACKS = {
    "rate_limit_per_minute": "120",
    "rate_limit_per_day": "50000",
    "max_solve_time_seconds": "0",
    "max_variables": "0",
    "max_daily_solves": "0",
    "max_cron_schedules": "0",
    "allowed_features": '["llm_assistant","warm_start","sensitivity_analysis","cron_scheduling"]',
}


def _tiers_in_use(conn) -> list[str]:
    """Plans that at least one organization is on; ``free`` if the table is empty."""
    rows = conn.execute(text("SELECT DISTINCT plan FROM organizations WHERE plan IS NOT NULL"))
    tiers = [r[0].lower() for r in rows if r[0] and r[0].lower() in _KNOWN_TIERS]
    return tiers or ["free"]


def _most_permissive_numeric(values: list[str]) -> str | None:
    """0 beats everything (unlimited); otherwise the largest cap."""
    numbers = []
    for raw in values:
        try:
            numbers.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not numbers:
        return None
    if any(n <= 0 for n in numbers):
        return "0"
    return str(max(numbers))


def _union_features(values: list[str]) -> str | None:
    """Union of every tier's feature list, order-stable for a readable diff."""
    merged: list[str] = []
    for raw in values:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, list):
            continue
        for feature in parsed:
            if isinstance(feature, str) and feature not in merged:
                merged.append(feature)
    return json.dumps(merged, separators=(",", ":")) if merged else None


def upgrade() -> None:
    conn = op.get_bind()
    tiers = _tiers_in_use(conn)

    for field in _ALL_FIELDS:
        keys = [f"plan_{tier}_{field}" for tier in tiers]
        rows = conn.execute(
            text("SELECT value FROM platform_settings WHERE key = ANY(:keys)"),
            {"keys": keys},
        )
        existing = [r[0] for r in rows if r[0] is not None]

        if field == "allowed_features":
            value = _union_features(existing)
        else:
            value = _most_permissive_numeric(existing)

        conn.execute(
            text(
                "INSERT INTO platform_settings (key, value, updated_at, updated_by)"
                " VALUES (:key, :value, NOW(), 'instance_limits_migration')"
                " ON CONFLICT (key) DO NOTHING"
            ),
            {"key": f"instance_{field}", "value": value or _FALLBACKS[field]},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text("DELETE FROM platform_settings WHERE key = ANY(:keys)"),
        {"keys": [f"instance_{field}" for field in _ALL_FIELDS]},
    )
