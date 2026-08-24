"""A column of a comparison stops carrying its own copy of the problem (D-32).

Every column of a solver comparison solves the parent's snapshot, byte for byte
— that is what makes the columns comparable. Each column stored that snapshot
again in its own ``input_data``. Measured on an assignment model the size the
owner runs (150x150, 22,500 binary variables): 3.8 MB as JSON, so one matrix row
of four solvers wrote about 19 MB of the same bytes. On the development database
the redundant copies came to **59 MB of a 216 MB table**.

New columns write ``{}`` and read through ``ModelExecution.problem_data``, which
falls back to the parent. This clears the copies already on disk.

**Only rows whose copy is byte-identical to the parent's snapshot are cleared.**
They are identical by construction — both are the same ``OptimizationProblem``
dumped twice in the same request — and that was confirmed by measurement before
this was written: 286 of 286 on the development database, 0 different. The
condition is in the statement anyway, so a row that somehow differs keeps its
own copy and ``problem_data`` keeps returning it.

**The table does not shrink when this runs.** Measured on the development
database: the columns went from 59 MB to 858 bytes, and
``pg_total_relation_size('model_executions')`` still read 216 MB, with 216 dead
tuples waiting. Postgres marks the old row versions dead and reuses the space
for new rows; the file only shrinks back to the operating system under
``VACUUM FULL``, which takes an exclusive lock. So: this frees the space for the
table to grow into, not for the disk. Check ``n_dead_tup`` in
``pg_stat_user_tables``, not the file size, or it looks like nothing happened.

The revision id is short on purpose: alembic's ``version_num`` column is
``varchar(32)``, and a longer one fails every test setup with
``StringDataRightTruncation`` rather than anything that names the cause.

Reversible: the down leg copies each parent's snapshot back onto its columns.
Nothing is lost either way, because the parent still holds the problem.

⚠️ Deploy note: like the migration before it, this changes what an OLD API
image reads. That image has no ``problem_data`` property and would show an
analysis page "no formulation" for a comparison column until the container is
replaced. It is a degradation rather than a 500, and the maintenance banner that
``20260824_drop_total_activations`` already requires covers this release too.

Revision ID: 20260824_comparison_copies
Revises: 20260824_drop_total_activations
Create Date: 2026-08-24
"""

from alembic import op

revision = "20260824_comparison_copies"
down_revision = "20260824_drop_total_activations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE model_executions e
        SET input_data = '{}'::json
        FROM solver_comparisons c
        WHERE e.comparison_id = c.id
          AND c.problem_data IS NOT NULL
          AND e.input_data::text = c.problem_data::text
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE model_executions e
        SET input_data = c.problem_data
        FROM solver_comparisons c
        WHERE e.comparison_id = c.id
          AND c.problem_data IS NOT NULL
          AND e.input_data::text = '{}'
        """
    )
