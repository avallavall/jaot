"""Drop the JAOT_DSL platform setting — JModel is not optional any more.

Revision ID: 20260802_drop_dsl_flag
Revises: 20260801_triggers_studio
Create Date: 2026-08-02

JModel shipped behind a flag while its compiler was a fresh spike behind a
STOP-gate. The gate passed on 2026-07-01, the feature has been on in production
since, and 301 tests cover it — but the flag stayed, defaulting to OFF, so every
NEW install still started with no Datasets tab and no scenarios and nothing on
screen to say why. The owner removed the flag entirely (2026-08-02).

The row is deleted rather than left behind: the admin panel renders from the
registry, and a setting with no definition is one nobody can explain or edit.

Data-only, and reversible in the sense that matters — ``downgrade`` puts the row
back with its old default. It cannot put back the code that read it.
"""

from alembic import op

revision = "20260802_drop_dsl_flag"
down_revision = "20260801_triggers_studio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM platform_settings WHERE key = 'JAOT_DSL'")


def downgrade() -> None:
    # `updated_at` is NOT NULL with no server default — omitting it fails the insert.
    op.execute(
        """
        INSERT INTO platform_settings (key, value, updated_at)
        VALUES ('JAOT_DSL', 'false', NOW())
        ON CONFLICT (key) DO NOTHING
        """
    )
