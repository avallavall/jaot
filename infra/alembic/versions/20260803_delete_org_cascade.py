"""Deleting an organization must not trip over its own children.

Revision ID: 20260803_delete_org_cascade
Revises: 20260802_unlist_empty_demos
Create Date: 2026-08-03

Measured against production (QA 2026-08-02): ``DELETE FROM organizations`` fails
with a foreign-key violation — ``api_keys.organization_id`` carries no ON DELETE
action — which would block an account deletion. Audited the live schema for every
foreign key reaching ``organizations`` or ``users`` with NO ACTION on delete:
eighteen, not one. Five sit on ledger tables whose ORM models are already gone
(credits removed by ADR-008, withdrawals legacy) but whose tables — and FKs —
remain.

The rule applied: rows that ARE the account's data die with it (CASCADE); rows
that merely name a person keep existing and lose the attribution (SET NULL —
exactly the three nullable ``created_by`` columns, matching the convention the
younger tables already follow).

Reversible: ``downgrade`` recreates every constraint with no delete action, as
before.
"""

from alembic import op

revision = "20260803_delete_org_cascade"
down_revision = "20260802_unlist_empty_demos"
branch_labels = None
depends_on = None

# (table, constraint name, column, referred table, ON DELETE action)
_FKS = [
    # The account's own data: dies with the organization…
    ("api_keys", "api_keys_organization_id_fkey", "organization_id", "organizations", "CASCADE"),
    ("users", "users_organization_id_fkey", "organization_id", "organizations", "CASCADE"),
    (
        "llm_conversations",
        "llm_conversations_organization_id_fkey",
        "organization_id",
        "organizations",
        "CASCADE",
    ),
    (
        "formulation_ratings",
        "formulation_ratings_organization_id_fkey",
        "organization_id",
        "organizations",
        "CASCADE",
    ),
    (
        "usage_records",
        "usage_records_organization_id_fkey",
        "organization_id",
        "organizations",
        "CASCADE",
    ),
    (
        "credit_transactions",
        "credit_transactions_organization_id_fkey",
        "organization_id",
        "organizations",
        "CASCADE",
    ),
    (
        "seller_tos_acceptances",
        "fk_seller_tos_org_id",
        "organization_id",
        "organizations",
        "CASCADE",
    ),
    ("withdrawals", "withdrawals_organization_id_fkey", "organization_id", "organizations", "CASCADE"),
    (
        "withdrawal_schedules",
        "withdrawal_schedules_organization_id_fkey",
        "organization_id",
        "organizations",
        "CASCADE",
    ),
    # …and with the user (users cascade from the organization).
    ("api_keys", "api_keys_user_id_fkey", "user_id", "users", "CASCADE"),
    ("llm_conversations", "llm_conversations_user_id_fkey", "user_id", "users", "CASCADE"),
    ("formulation_ratings", "formulation_ratings_user_id_fkey", "user_id", "users", "CASCADE"),
    ("refresh_tokens", "refresh_tokens_user_id_fkey", "user_id", "users", "CASCADE"),
    ("usage_records", "usage_records_user_id_fkey", "user_id", "users", "CASCADE"),
    (
        "verification_requests",
        "verification_requests_requested_by_fkey",
        "requested_by",
        "users",
        "CASCADE",
    ),
    # Attribution only: the row outlives the person who created it.
    (
        "model_builder_documents",
        "model_builder_documents_created_by_fkey",
        "created_by",
        "users",
        "SET NULL",
    ),
    ("solve_triggers", "solve_triggers_created_by_fkey", "created_by", "users", "SET NULL"),
    ("workspaces", "workspaces_created_by_fkey", "created_by", "users", "SET NULL"),
]


def upgrade() -> None:
    for table, name, column, referred, ondelete in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referred, [column], ["id"], ondelete=ondelete)


def downgrade() -> None:
    for table, name, column, referred, _ondelete in _FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referred, [column], ["id"])
