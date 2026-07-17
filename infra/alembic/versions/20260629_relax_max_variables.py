"""Relax plan max_variables to the OSS registry default (companion to 20260629_relax_limits).

The relax-limits migration synced most plan caps to the open-source registry
defaults but omitted ``plan_*_max_variables``, so existing installs stayed at the
old commercial cap (free = 5,000 variables) even though the registry default is
now 10,000,000. On a self-hosted deployment a free plan should not be capped at
5k variables — a modest assignment model is already tens of thousands. Data-only;
the 20260327 seed runs ON CONFLICT DO NOTHING, so editing the registry default
alone never reaches an already-seeded install.

Only ``plan_free_max_variables`` actually changes; the others already match the
registry default and are left untouched.

Revision ID: 20260629_relax_max_vars
Revises: 20260629_relax_limits
Create Date: 2026-06-29
"""

from alembic import op
from sqlalchemy import text

revision = "20260629_relax_max_vars"
down_revision = "20260629_relax_limits"
branch_labels = None
depends_on = None

# (key, new_value, old_value)
_CHANGES: list[tuple[str, str, str]] = [
    ("plan_free_max_variables", "10000000", "5000"),
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
