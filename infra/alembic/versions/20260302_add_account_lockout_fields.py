"""Add account lockout fields to users table.

Revision ID: p1q2r3s4t5u6
Revises: n0o1p2q3r4s5
Create Date: 2026-03-02 10:00:00.000000+00:00

Phase 39: Security audit — failed_login_attempts and locked_until columns
for brute-force protection via account lockout after 5 failed attempts.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "p1q2r3s4t5u6"
down_revision = "n0o1p2q3r4s5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
