"""add origin and trigger_id to model_executions, make organization_model_id nullable

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-02-21 19:00:00.000000+00:00

Changes:
- model_executions.organization_model_id: NOT NULL -> nullable
- model_executions.origin: new String(16) column, server_default='manual'
- model_executions.trigger_id: new String(64) nullable column
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("model_executions") as batch_op:
        # Make organization_model_id nullable (triggered executions have no org model)
        batch_op.alter_column(
            "organization_model_id",
            existing_type=sa.String(64),
            nullable=True,
        )
        # Add origin column — existing rows get 'manual'
        batch_op.add_column(
            sa.Column(
                "origin",
                sa.String(16),
                nullable=False,
                server_default="manual",
            )
        )
        # Add trigger_id column — nullable, only set for triggered executions
        batch_op.add_column(
            sa.Column(
                "trigger_id",
                sa.String(64),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("model_executions") as batch_op:
        batch_op.drop_column("trigger_id")
        batch_op.drop_column("origin")
        # Restore organization_model_id to NOT NULL
        batch_op.alter_column(
            "organization_model_id",
            existing_type=sa.String(64),
            nullable=False,
        )
