"""Seed platform_settings with registry defaults.

Data-only migration: inserts default values from SETTINGS_REGISTRY
into platform_settings for every entry with a non-None default_value.
Uses ON CONFLICT (key) DO NOTHING to preserve existing values in
deployed environments.

Revision ID: 20260327_seed_settings
Revises: 20260326_credit_pools
Create Date: 2026-03-27
"""

from alembic import op
from sqlalchemy import text

revision = "20260327_seed_settings"
down_revision = "20260326_credit_pools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    from app.services.settings_registry import SETTINGS_REGISTRY

    for defn in SETTINGS_REGISTRY:
        if defn.default_value is None:
            continue
        conn.execute(
            text(
                "INSERT INTO platform_settings"
                " (key, value, description, updated_at, updated_by)"
                " VALUES (:key, :value, :desc, NOW(), 'system_seed')"
                " ON CONFLICT (key) DO NOTHING"
            ),
            {
                "key": defn.key,
                "value": defn.default_value,
                "desc": defn.description,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()

    from app.services.settings_registry import SETTINGS_REGISTRY

    keys = [defn.key for defn in SETTINGS_REGISTRY if defn.default_value is not None]
    if keys:
        conn.execute(
            text(
                "DELETE FROM platform_settings"
                " WHERE key = ANY(:keys)"
                " AND updated_by = 'system_seed'"
            ),
            {"keys": keys},
        )
