"""Remove the two Beat entries the billing layer left behind.

``process_scheduled_withdrawals`` and ``run_balance_reconciliation`` went with
the money layer (ADR-008). Their rows in ``celery_periodictask`` stayed
enabled, so Beat sent each task once a day and the worker logged "Received
unregistered task" with a KeyError, twice a day, on every instance.

The table belongs to sqlalchemy-celery-beat, which creates it when Beat first
starts, so a fresh database may not have it yet.

The rows pointed at tasks no worker has, so removing them changes nothing that
runs. The downgrade does not put them back.

Revision ID: 20260924_drop_billing_beat
Revises: 20260924_onboarding_last_day
"""

import sqlalchemy as sa
from alembic import op

revision = "20260924_drop_billing_beat"
down_revision = "20260924_onboarding_last_day"
branch_labels = None
depends_on = None

#: Tasks that no longer exist anywhere in the code.
DEAD_TASKS = ("process_scheduled_withdrawals", "run_balance_reconciliation")


def delete_dead_beat_entries(conn: sa.engine.Connection) -> int:
    """Delete the Beat rows of the removed billing tasks. Returns how many went."""
    if conn.execute(sa.text("SELECT to_regclass('public.celery_periodictask')")).scalar() is None:
        return 0
    deleted = conn.execute(
        sa.text("DELETE FROM public.celery_periodictask WHERE task IN :tasks").bindparams(
            sa.bindparam("tasks", expanding=True)
        ),
        {"tasks": list(DEAD_TASKS)},
    ).rowcount
    changed = conn.execute(
        sa.text("SELECT to_regclass('public.celery_periodictaskchanged')")
    ).scalar()
    if deleted and changed is not None:
        # A running Beat reloads its schedule when this timestamp moves.
        conn.execute(sa.text("UPDATE public.celery_periodictaskchanged SET last_update = now()"))
    return deleted


def upgrade() -> None:
    delete_dead_beat_entries(op.get_bind())


def downgrade() -> None:
    pass
