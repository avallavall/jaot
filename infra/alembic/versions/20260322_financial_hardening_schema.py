"""Financial hardening schema: Stripe Connect, anti-fraud, holding period, invoice sequence

Revision ID: b4c5d6e7f8g9
Revises: a3b4c5d6e7f8
Create Date: 2026-03-22

Changes:
- Organization: add stripe_connect_account_id, stripe_connect_onboarding_complete,
  is_frozen, chargeback_count; drop bank_iban, bank_swift, bank_holder_name
- CreditTransaction: add available_at, commission_rate
- Withdrawal: add stripe_transfer_id; drop bank_iban, bank_swift, bank_holder_name
- New table: seller_tos_acceptances
- New sequence: invoice_number_seq
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b4c5d6e7f8g9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- Invoice number sequence (race-condition-free numbering, per D-21) --
    op.execute("CREATE SEQUENCE IF NOT EXISTS invoice_number_seq START 1 INCREMENT 1")

    # -- Organization: add Stripe Connect and anti-fraud columns --
    op.add_column(
        "organizations",
        sa.Column("stripe_connect_account_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "stripe_connect_onboarding_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "is_frozen", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "chargeback_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.create_index(
        "ix_organizations_stripe_connect_account_id",
        "organizations",
        ["stripe_connect_account_id"],
        unique=False,
    )

    # Organization: drop legacy bank fields (D-01 -- Stripe Connect replaces bank transfers)
    op.drop_column("organizations", "bank_iban")
    op.drop_column("organizations", "bank_swift")
    op.drop_column("organizations", "bank_holder_name")

    # -- CreditTransaction: add holding period and commission audit columns --
    op.add_column(
        "credit_transactions",
        sa.Column("available_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "credit_transactions",
        sa.Column("commission_rate", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_credit_transactions_available_at",
        "credit_transactions",
        ["available_at"],
        unique=False,
    )

    # -- Withdrawal: add Stripe transfer reference, drop bank fields --
    op.add_column(
        "withdrawals",
        sa.Column("stripe_transfer_id", sa.String(255), nullable=True),
    )
    op.drop_column("withdrawals", "bank_iban")
    op.drop_column("withdrawals", "bank_swift")
    op.drop_column("withdrawals", "bank_holder_name")

    # -- New table: seller_tos_acceptances (D-16) --
    op.create_table(
        "seller_tos_acceptances",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("tos_version", sa.String(50), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_by_user_id", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name="fk_seller_tos_org_id"
        ),
    )
    op.create_index(
        "ix_seller_tos_acceptances_organization_id",
        "seller_tos_acceptances",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    # -- Drop seller_tos_acceptances --
    op.drop_index(
        "ix_seller_tos_acceptances_organization_id",
        table_name="seller_tos_acceptances",
    )
    op.drop_table("seller_tos_acceptances")

    # -- Withdrawal: restore bank fields, drop stripe_transfer_id --
    op.add_column(
        "withdrawals",
        sa.Column("bank_holder_name", sa.String(), nullable=True),
    )
    op.add_column(
        "withdrawals",
        sa.Column("bank_swift", sa.String(), nullable=True),
    )
    op.add_column(
        "withdrawals",
        sa.Column("bank_iban", sa.String(), nullable=True),
    )
    op.drop_column("withdrawals", "stripe_transfer_id")

    # -- CreditTransaction: drop available_at, commission_rate --
    op.drop_index(
        "ix_credit_transactions_available_at",
        table_name="credit_transactions",
    )
    op.drop_column("credit_transactions", "commission_rate")
    op.drop_column("credit_transactions", "available_at")

    # -- Organization: restore bank fields, drop new columns --
    op.add_column(
        "organizations",
        sa.Column("bank_holder_name", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("bank_swift", sa.String(), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("bank_iban", sa.String(), nullable=True),
    )
    op.drop_index(
        "ix_organizations_stripe_connect_account_id",
        table_name="organizations",
    )
    op.drop_column("organizations", "chargeback_count")
    op.drop_column("organizations", "is_frozen")
    op.drop_column("organizations", "stripe_connect_onboarding_complete")
    op.drop_column("organizations", "stripe_connect_account_id")

    # -- Drop invoice number sequence --
    op.execute("DROP SEQUENCE IF EXISTS invoice_number_seq")
