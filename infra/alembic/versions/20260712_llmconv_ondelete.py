"""Add ON DELETE SET NULL to llm_conversations.organization_model_id (P1.5 F0).

The FK was created without an ondelete rule, so deleting an ``OrganizationModel``
that still has conversations linked to it would RAISE (restrict) instead of
detaching them. P1.5 collapses ``OrganizationModel`` into ``ModelProject``; a
conversation's optional link must survive an org-model delete by nulling out,
not block it. Additive + backward-compatible: drop-and-recreate the SAME FK with
``ondelete=SET NULL`` (no column/table drop, no data change) — old code keeps
working (it never relied on the delete RAISING).

Revision ID: 20260712_llmconv_ondelete
Revises: 20260711_money_nullable
Create Date: 2026-07-12
"""

from alembic import op

revision = "20260712_llmconv_ondelete"
down_revision = "20260711_money_nullable"
branch_labels = None
depends_on = None

_TABLE = "llm_conversations"
_COLUMN = "organization_model_id"
# Postgres auto-names an unnamed column FK ``{table}_{column}_fkey``.
_OLD_FK = "llm_conversations_organization_model_id_fkey"
_NEW_FK = "fk_llm_conversations_organization_model_id"


def upgrade() -> None:
    # Drop the existing FK (auto-named, or a prior recreate) then add the SET NULL one.
    op.execute(f'ALTER TABLE "{_TABLE}" DROP CONSTRAINT IF EXISTS "{_OLD_FK}"')
    op.execute(f'ALTER TABLE "{_TABLE}" DROP CONSTRAINT IF EXISTS "{_NEW_FK}"')
    op.create_foreign_key(
        _NEW_FK,
        _TABLE,
        "organization_models",
        [_COLUMN],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.execute(f'ALTER TABLE "{_TABLE}" DROP CONSTRAINT IF EXISTS "{_NEW_FK}"')
    op.create_foreign_key(
        _OLD_FK,
        _TABLE,
        "organization_models",
        [_COLUMN],
        ["id"],
    )
