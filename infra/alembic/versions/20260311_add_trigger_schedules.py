"""Add trigger_schedules table and source column to trigger_runs

Revision ID: d5e6f7g8h9i0
Revises: c3d4e5f6g7h8
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d5e6f7g8h9i0"
down_revision = "c3d4e5f6g7h8"
branch_labels = None
depends_on = None

# NOTE: sqlalchemy-celery-beat creates its own tables automatically on Beat
# startup (celery_periodic_task, celery_crontab_schedule,
# celery_periodic_task_changed). Do NOT include them in Alembic migrations.


def upgrade() -> None:
    op.create_table(
        "trigger_schedules",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "trigger_id",
            sa.String(64),
            sa.ForeignKey("solve_triggers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "organization_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("beat_task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_trigger_schedules_trigger_id", "trigger_schedules", ["trigger_id"]
    )
    op.create_index(
        "ix_trigger_schedules_organization_id",
        "trigger_schedules",
        ["organization_id"],
    )

    # Add source column to trigger_runs (manual | cron | rerun)
    op.add_column(
        "trigger_runs",
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
    )


def downgrade() -> None:
    op.drop_column("trigger_runs", "source")
    op.drop_table("trigger_schedules")
