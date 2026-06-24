"""Add password auth columns to users and create refresh_tokens table.

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-02-28 20:00:00.000000+00:00

Phase 36: Email/password authentication — password_hash, email_verified,
email_verified_at on users; refresh_tokens table for JWT revocation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n0o1p2q3r4s5"
down_revision: Union[str, None] = "m9n0o1p2q3r4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add password auth columns to users
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
    )

    # Create refresh_tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("jti", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "revoked",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_jti", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "password_hash")
