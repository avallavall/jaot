"""One ledger conversation per (org, user, sentinel) — partial unique index.

B3's standalone-spend ledger (``record_standalone_llm_spend``) get-or-creates a
hidden "sys:"-tagged conversation per (org, user); two concurrent first spends
could both miss the SELECT and create two ledgers (benign for the budget SUM —
it sums every message — but the duplicates are unbounded and untidy). Merge any
existing duplicates into the earliest row, then enforce uniqueness with a
partial index so the service's create can race safely (IntegrityError → adopt
the winner's row).

Additive-only: a new index; the data step only touches duplicate "sys:" rows.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260720_llmconv_ledger_uq"
down_revision = "20260713_p15_reviews_fav"
branch_labels = None
depends_on = None

_RANKED = """
    SELECT id,
           first_value(id) OVER (
               PARTITION BY organization_id, user_id, model_id
               ORDER BY created_at, id
           ) AS keeper
    FROM llm_conversations
    WHERE model_id LIKE 'sys:%'
"""


def upgrade() -> None:
    # 1) Re-home the messages of duplicate ledgers onto the earliest row…
    op.execute(
        f"""
        WITH ranked AS ({_RANKED})
        UPDATE llm_messages m
        SET conversation_id = r.keeper
        FROM ranked r
        WHERE m.conversation_id = r.id AND r.id <> r.keeper
        """
    )
    # 2) …drop the now-empty duplicate ledger rows…
    op.execute(
        f"""
        WITH ranked AS ({_RANKED})
        DELETE FROM llm_conversations c
        USING ranked r
        WHERE c.id = r.id AND r.id <> r.keeper
        """
    )
    # 3) …and make the invariant hold from here on.
    op.create_index(
        "uq_llm_conversations_sys_ledger",
        "llm_conversations",
        ["organization_id", "user_id", "model_id"],
        unique=True,
        postgresql_where=sa.text("model_id LIKE 'sys:%'"),
    )


def downgrade() -> None:
    op.drop_index("uq_llm_conversations_sys_ledger", table_name="llm_conversations")
