"""Unlist marketplace cards that carry no model at all.

Revision ID: 20260802_unlist_empty_demos
Revises: 20260802_drop_dsl_flag
Create Date: 2026-08-02

A "generic" listing contributes no model of its own: the whole problem travels in
the input. Three cards seeded on 2026-06-25 have no example input, no input schema,
no input fields and no pinned version — so there is nothing to render and nothing a
reader could fill in either. Pressing "use this model" returned ``422 Missing
'variables' field``. Measured 2026-08-02 by rendering every visible card the way
adoption does: 107 visible, 104 fine, these 3 broken.

The state can no longer be created: ``publish_listing`` has required a committed
HEAD since P1.5, and these three never went through it (``published_at`` is NULL).
So this is a one-off cleanup of rows that predate the guard, written structurally
rather than by id so it also finds them wherever else they were seeded.

All four emptiness checks are needed together: a generic card with a schema or
fields but no example is perfectly usable, because ``POST /projects/from-marketplace``
takes the reader's own input.

Reversible: ``downgrade`` republishes exactly the rows this touched, matched by the
same condition.
"""

from alembic import op

revision = "20260802_unlist_empty_demos"
down_revision = "20260802_drop_dsl_flag"
branch_labels = None
depends_on = None

# `example_input` and `input_schema` are `json`, not `jsonb` — no equality operator,
# so compare the text form. An absent value reads as NULL, `{}`/`[]` or a JSON `null`.
_EMPTY_GENERIC = """
    generator_type = 'generic'
    AND pinned_version_id IS NULL
    AND (example_input IS NULL OR example_input::text IN ('{}', 'null'))
    AND (input_schema IS NULL OR input_schema::text IN ('{}', 'null'))
    AND (input_fields IS NULL OR input_fields::text IN ('[]', 'null'))
"""


def upgrade() -> None:
    op.execute(f"UPDATE model_project_listings SET is_public = false WHERE {_EMPTY_GENERIC}")


def downgrade() -> None:
    op.execute(f"UPDATE model_project_listings SET is_public = true WHERE {_EMPTY_GENERIC}")
