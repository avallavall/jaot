"""Delete the SOLVER_POOL_SIZE setting row — nothing has ever acted on it.

The setting configured a solver thread pool that no code path builds. Its only
reader was ``app/domains/solver/services/pool.py``, a lazily-created
``ThreadPoolExecutor`` for "all synchronous solve paths" — and ADR-007 removed
every in-request solve, leaving the module with no callers at all. The panel
offered the control, and its help text even explained when a change would take
effect ("when the API restarts"), for a pool that is never constructed.

Same shape as ``20260728_prune_orphan_settings``: the key leaves the registry,
so this deletes the row it would otherwise leave behind. Rolling back re-seeds
it from the older image's own registry, where it is equally inert.

Revision ID: 20260729_drop_solver_pool_size
Revises: 20260728_prune_orphan_settings
Create Date: 2026-07-29
"""

from alembic import op
from sqlalchemy import text

revision = "20260729_drop_solver_pool_size"
down_revision = "20260728_prune_orphan_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        text("DELETE FROM platform_settings WHERE key = :key"),
        {"key": "SOLVER_POOL_SIZE"},
    )


def downgrade() -> None:
    """No-op: whichever image a rollback lands on re-seeds the keys its own
    registry declares, on the next boot."""
