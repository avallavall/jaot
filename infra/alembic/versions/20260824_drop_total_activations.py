"""Drop the stored adoption counter; the number is counted now.

``model_project_listings.total_activations`` was bumped when somebody forked a
listing and nothing ever recomputed it. On the development database it read 66
against the 6 that the query defining an adoption returns, and the stored one
was the number a marketplace card showed a visitor. Every screen reads
``adoption_counts`` now, which counts the fork rows themselves.

That count joins ``model_projects.source_ref`` to the listing id and filters
``source_type``, on routes that need no account — the catalogue list, a model
page, an author profile. This adds the index for it in the same revision, so the
read that replaces the column is never a sequential scan of every project on the
platform.

⚠️ **THIS RELEASE CANNOT USE THE PLAIN RESTART PATH.** ``deploy/deploy.sh`` runs
migrations while the OLD API container is still serving ("Migrate BEFORE
restarting API"). The old image's ORM still maps ``total_activations``, so from
the moment this commits until that container is replaced, every request that
loads a listing answers 500 with ``UndefinedColumn`` — on the public
marketplace. Deploy it through ``standard_rotate``, which raises the maintenance
banner first.

⚠️ **IRREVERSIBLE FOR THE SEEDED VALUES.** The down leg puts the column back with
a default of 0, so the shape is restored but the numbers are not: the values in
it came from the P1.5 backfill, not from any event, and nothing can reproduce
them. Take a backup before running this, per the repo rule on irreversible
migrations.

Revision ID: 20260824_drop_total_activations
Revises: 20260820_review_reports
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260824_drop_total_activations"
down_revision = "20260820_review_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_model_projects_source", "model_projects", ["source_type", "source_ref"])
    op.drop_column("model_project_listings", "total_activations")


def downgrade() -> None:
    # Shape only. Every row comes back at 0 — see the warning above.
    op.add_column(
        "model_project_listings",
        sa.Column("total_activations", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_index("ix_model_projects_source", table_name="model_projects")
