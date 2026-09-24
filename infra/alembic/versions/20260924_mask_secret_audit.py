"""Mask secret values already written to the settings audit trail.

``bulk_set`` and ``reset_to_default`` stored the old and new value of every
setting in ``platform_setting_audit`` without looking at ``is_secret``, so each
rotation of the Anthropic key, the SMTP password or the JWT secret sat there in
plain text, was returned by ``GET /admin/settings/audit`` and was printed on the
Audit tab. The code now writes ``****``. This rewrites the rows that exist.

The key list is spelled out rather than read from the registry: a migration
must mean the same thing whenever it runs.

Not reversible, on purpose: the downgrade cannot bring a secret back, and it
should not. The deploy takes a database backup before migrating, and that
backup still holds the old rows.

Revision ID: 20260924_mask_secret_audit
Revises: 20260901_project_seed_hash
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_mask_secret_audit"
down_revision = "20260901_project_seed_hash"
branch_labels = None
depends_on = None

_SECRET_KEYS = (
    "JWT_SECRET",
    "ANTHROPIC_API_KEY",
    "SMTP_PASSWORD",
    "DISCOURSE_SSO_SECRET",
    "STORAGE_ACCESS_KEY",
    "STORAGE_SECRET_KEY",
)


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE platform_setting_audit SET "
            "old_value = CASE WHEN old_value IS NULL OR old_value = '' "
            "THEN old_value ELSE '****' END, "
            "new_value = CASE WHEN new_value IS NULL OR new_value = '' "
            "THEN new_value ELSE '****' END "
            "WHERE setting_key IN :keys"
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(_SECRET_KEYS)},
    )


def downgrade() -> None:
    # A masked secret cannot be restored. Nothing reads the old values.
    pass
