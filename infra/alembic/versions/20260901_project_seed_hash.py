"""Record the draft hash a project was seeded with.

A generator-backed fork stores a model rendered once, at fork time, while the
solve path re-renders from the source card. When the card is corrected the two
stop agreeing: the studio shows one model and the API solves another, for the
same project id, and neither side says so. 17 cards carry generator_params, so
every project forked from one of them before 3.8.0 is in that state.

``seed_content_hash`` says what the draft looked like when the project was
created. While it still equals ``draft_content_hash`` nobody has edited the
model by hand and the draft can be refreshed from the card. Once they differ
the user's own model wins on every path — the draft endpoint has never refused
an edit to a generator-backed project, and the solve path was discarding those
edits.

Deliberately no backfill. An existing row keeps NULL, which reads as "edited",
so its draft is left exactly as it is. We cannot tell whether somebody wrote
that model by hand, and keeping a model the user may have authored beats
overwriting it to match a card.

Additive and reversible: the downgrade drops a column nothing else reads.

Revision ID: 20260901_project_seed_hash
Revises: 20260831_listing_gen_params
"""

import sqlalchemy as sa
from alembic import op

revision = "20260901_project_seed_hash"
down_revision = "20260831_listing_gen_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_projects",
        sa.Column("seed_content_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_projects", "seed_content_hash")
