"""add workspace_id to solve_triggers

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-02-23 13:00:00.000000+00:00

Adds workspace_id (String(64), nullable, FK to workspaces.id with SET NULL)
and an index on solve_triggers.workspace_id.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("solve_triggers") as batch_op:
        batch_op.add_column(sa.Column("workspace_id", sa.String(64), nullable=True))
        batch_op.create_index("ix_solve_triggers_workspace_id", ["workspace_id"])
        batch_op.create_foreign_key(
            "fk_solve_triggers_workspace_id",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("solve_triggers") as batch_op:
        batch_op.drop_index("ix_solve_triggers_workspace_id")
        batch_op.drop_constraint("fk_solve_triggers_workspace_id", type_="foreignkey")
        batch_op.drop_column("workspace_id")
