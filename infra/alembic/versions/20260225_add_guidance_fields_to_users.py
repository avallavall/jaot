"""Add guidance fields to users table.

Revision ID: j7k8l9m0n1o2
Revises: i6j7k8l9m0n1
Create Date: 2026-02-25 14:20:00.000000+00:00

GUIDE-02, GUIDE-03: Skill level and wizard state persistence for guidance system.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j7k8l9m0n1o2"
down_revision: Union[str, None] = "i6j7k8l9m0n1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("skill_level", sa.String(20), nullable=False, server_default="beginner"),
    )
    op.add_column(
        "users",
        sa.Column("guidance_state", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "guidance_state")
    op.drop_column("users", "skill_level")
