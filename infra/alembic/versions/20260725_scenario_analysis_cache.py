"""Cache the what-if scenario analysis (Sensitivity L2) on the execution.

Each scenario in the batch is a FULL re-solve of a perturbed model, so the
analysis is requested on demand and its result must survive a page reload rather
than being recomputed. The column holds the whole job envelope (status, task id,
timestamps, error, result) so a running batch is visible while it runs.

Its own column instead of a key inside ``result_data``: the solve writer owns
that blob, and an analysis writing into it would be racing the writer for no
reason.

Additive-only: one nullable JSON column, no backfill (a NULL simply means "never
analysed"), and old code ignores it.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260725_scenario_analysis"
down_revision = "20260725_llm_models_v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_executions",
        sa.Column("scenario_analysis", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_executions", "scenario_analysis")
