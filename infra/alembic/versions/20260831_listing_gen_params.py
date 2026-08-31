"""Give a listing's generator facet the parameters the generator reads.

``ModelProjectListing`` carries the generator facet of an official card:
``generator_type``, ``input_schema``, ``input_fields`` and ``example_input``.
It never carried ``generator_params``, and the generator reads that on every
call. ``listing_to_template_dict`` therefore handed the engine a template with
no params, and the engine called ``generate(user_input, {})``.

Two routes go through that dict. Solving an official template by its
``official_`` id, which is the id the studio's template page uses, and solving
any project forked from an official listing, which is the whole "Use in studio"
flow. Seventeen of the hundred and two cards carry params. With them dropped,
six raise (five assignment cards lose their cost rules and cell_tower_placement
loses ``coverage_format``) and eleven build a different model and still report
optimal — property_portfolio loses its risk ceiling, max_flow stops maximising
flow, fleet_dispatch_mining stops being a max-flow model at all.

Additive and reversible: one nullable JSON column. The seeder writes it for
every official listing on the next boot, so no backfill runs here.

Revision ID: 20260831_listing_gen_params
Revises: 20260824_comparison_copies
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op

revision = "20260831_listing_gen_params"
down_revision = "20260824_comparison_copies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_project_listings",
        sa.Column("generator_params", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_project_listings", "generator_params")
