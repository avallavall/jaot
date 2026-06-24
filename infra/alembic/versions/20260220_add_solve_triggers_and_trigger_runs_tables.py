"""add solve_triggers and trigger_runs tables

Revision ID: d1e2f3a4b5c6
Revises: c9d2e3f4a5b6
Create Date: 2026-02-20 20:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c9d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create solve_triggers table
    op.create_table(
        'solve_triggers',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('document_id', sa.String(length=64), nullable=False),
        sa.Column('version_id', sa.String(length=64), nullable=False),
        sa.Column('trigger_secret', sa.String(length=128), nullable=False),
        sa.Column('override_schema', sa.JSON(), nullable=True),
        sa.Column('webhook_url', sa.String(length=500), nullable=False),
        sa.Column('webhook_secret', sa.String(length=255), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('total_runs', sa.Integer(), nullable=False),
        sa.Column('last_fired_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organizations.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['created_by'],
            ['users.id'],
        ),
        sa.ForeignKeyConstraint(
            ['document_id'],
            ['model_builder_documents.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['version_id'],
            ['model_version_snapshots.id'],
            # RESTRICT prevents deletion of the pinned version while referenced
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('solve_triggers', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_solve_triggers_organization_id'),
            ['organization_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_solve_triggers_document_id'),
            ['document_id'],
            unique=False,
        )

    # Create trigger_runs table
    op.create_table(
        'trigger_runs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('trigger_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False),
        sa.Column('override_data', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('execution_id', sa.String(length=64), nullable=True),
        sa.Column('result_data', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('credits_consumed', sa.Integer(), nullable=False),
        sa.Column('execution_time_ms', sa.Integer(), nullable=True),
        sa.Column('webhook_delivered', sa.Boolean(), nullable=True),
        sa.Column('webhook_attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['trigger_id'],
            ['solve_triggers.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organizations.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('trigger_runs', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_trigger_runs_trigger_id'),
            ['trigger_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_trigger_runs_organization_id'),
            ['organization_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_trigger_runs_status'),
            ['status'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_trigger_runs_created_at'),
            ['created_at'],
            unique=False,
        )


def downgrade() -> None:
    # Drop trigger_runs first (depends on solve_triggers)
    with op.batch_alter_table('trigger_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_trigger_runs_created_at'))
        batch_op.drop_index(batch_op.f('ix_trigger_runs_status'))
        batch_op.drop_index(batch_op.f('ix_trigger_runs_organization_id'))
        batch_op.drop_index(batch_op.f('ix_trigger_runs_trigger_id'))

    op.drop_table('trigger_runs')

    with op.batch_alter_table('solve_triggers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_solve_triggers_document_id'))
        batch_op.drop_index(batch_op.f('ix_solve_triggers_organization_id'))

    op.drop_table('solve_triggers')
