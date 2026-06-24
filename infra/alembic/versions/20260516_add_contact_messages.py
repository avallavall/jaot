"""Add contact_messages table (Phase 9 D-03: durable trail for /contact submissions)

Implements the contact-form design decisions:
- D-03: durable DB trail before async email send
- D-05: 4 visible fields stored (name, email, subject, message → body)
- D-06: nullable user_id/organization_id (anonymous-friendly; no FK constraints)
- D-07: no recipient column — PSS-driven at task time (CONTACT_RECIPIENT)
- D-09: locale column stored verbatim so the email body can include `Locale: <code>`

Additive-only per root CLAUDE.md "Migrations" rule — single CREATE TABLE,
no DROP / RENAME / type changes to existing schema. No FK constraints
because anonymous submissions must not cascade against users/organizations.

Revision ID: 20260516_add_contact_messages
Revises: 20260424c_phase74_byol_teardown
Create Date: 2026-05-16
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260516_add_contact_messages"
down_revision = "20260424c_phase74_byol_teardown"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_messages",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # Composite index for admin/audit + retry-sweep queries on (status, created_at).
    op.create_index(
        "ix_contact_messages_status_created",
        "contact_messages",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("contact_messages")
