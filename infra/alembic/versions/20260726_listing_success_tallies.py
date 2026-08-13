"""Give marketplace listings the tallies their success rate is computed from.

``model_project_listings`` has carried ``success_rate`` and ``avg_execution_time_ms``
since the catalog rollup they were mirrored from, but after the P1.5 fusion nothing
wrote them: the solve task bumped ``total_executions`` and stopped. Both columns
stayed NULL for every listing, so the marketplace showed a dash for a model with
fourteen recorded runs.

Adds the raw counters the two figures are derived from. ``total_executions`` was only
ever incremented on success, so backfilling ``successful_executions`` from it is the
truth about the rows already there — the rate reads 100% for historic listings because
every run they counted did complete.

``timed_executions`` starts at zero rather than matching the successes: those runs
carry no stored duration, and dividing accumulated milliseconds by the larger count
would report an average several times too fast. The average stays NULL until real
timings accumulate.

Additive: three new columns with server defaults, no drops, no renames.

Revision ID: 20260726_listing_tallies
Revises: 20260726_unlimit_capacity
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "20260726_listing_tallies"
down_revision = "20260726_unlimit_capacity"
branch_labels = None
depends_on = None

_TABLE = "model_project_listings"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("successful_executions", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        _TABLE,
        sa.Column("timed_executions", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        _TABLE,
        sa.Column("total_execution_time_ms", sa.Float(), nullable=False, server_default="0"),
    )

    # Every run the old counter recorded was a success, so it IS the success tally.
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET successful_executions = total_executions "  # noqa: S608
            "WHERE total_executions > 0"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET success_rate = 1.0 "  # noqa: S608
            "WHERE total_executions > 0 AND success_rate IS NULL"
        )
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "total_execution_time_ms")
    op.drop_column(_TABLE, "timed_executions")
    op.drop_column(_TABLE, "successful_executions")
    op.execute(
        sa.text(f"UPDATE {_TABLE} SET success_rate = NULL")  # noqa: S608
    )
