"""add model_version_snapshots table

Revision ID: c9d2e3f4a5b6
Revises: b3c8d1e2f4a5
Create Date: 2026-02-20 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d2e3f4a5b6'
down_revision: Union[str, None] = 'b3c8d1e2f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'model_version_snapshots',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('document_id', sa.String(length=64), nullable=False),
        sa.Column('organization_id', sa.String(length=64), nullable=False),
        sa.Column('canvas_json', sa.JSON(), nullable=False),
        sa.Column('change_summary', sa.String(length=500), nullable=False),
        sa.Column('is_named', sa.Boolean(), nullable=False),
        sa.Column('version_name', sa.String(length=255), nullable=True),
        sa.Column('version_description', sa.Text(), nullable=True),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['document_id'],
            ['model_builder_documents.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organizations.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('model_version_snapshots', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_model_version_snapshots_document_id'),
            ['document_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_model_version_snapshots_organization_id'),
            ['organization_id'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('model_version_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_model_version_snapshots_organization_id'))
        batch_op.drop_index(batch_op.f('ix_model_version_snapshots_document_id'))

    op.drop_table('model_version_snapshots')
