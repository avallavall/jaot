"""Delete the three Featurebase rows the D-22 prune could not see.

Featurebase was the hosted feedback board, replaced by GitHub Issues. Its code
and its settings entries went with it, but three rows stayed in
``platform_settings`` on installs that had configured it — including a JWT secret
for a service this platform no longer talks to, which then sits in every
subsequent database backup.

They were missed rather than deferred: ``20260728_prune_orphan_settings`` was
built from an inventory of the development environment, which had never had
Featurebase configured, so the keys were absent from the list. The reference
install shows it plainly — 90 rows against 87 declared by the registry, and the
difference is exactly these three.

Same reasoning as that migration for why deleting rows needs no schema window:
an older image that declared any of these re-seeds it from its own registry on
the next boot (``_ensure_settings_seeded`` in ``app/main.py``), and no release
still standing declares them.

Revision ID: 20260731_prune_featurebase
Revises: 20260729_drop_solver_pool_size
Create Date: 2026-07-31

(The id stops at "featurebase" because ``alembic_version.version_num`` is
VARCHAR(32) — a longer one fails on insert, not on generation.)
"""

import logging

from alembic import op
from sqlalchemy import text

logger = logging.getLogger("alembic.runtime.migration")

revision = "20260731_prune_featurebase"
down_revision = "20260729_drop_solver_pool_size"
branch_labels = None
depends_on = None

#: Configuration for the retired hosted feedback board. The community feedback
#: URL now lives in the frontend as a constant, so nothing reads these.
ORPHAN_KEYS = (
    "FEATUREBASE_DEFAULT_BOARD",
    "FEATUREBASE_JWT_SECRET",
    "FEATUREBASE_ORG",
)


def upgrade() -> None:
    conn = op.get_bind()
    # An explicit list, for the same reason as the D-22 prune: "everything the
    # registry does not declare" would delete a different set of rows depending
    # on when the migration runs.
    result = conn.execute(
        text("DELETE FROM platform_settings WHERE key = ANY(:keys)"),
        {"keys": list(ORPHAN_KEYS)},
    )
    # Say what was deleted. `key` matches exactly, so an install that spelled or
    # cased these differently would delete nothing and still report success —
    # and the point of the migration is that a stale secret stops being stored.
    # The count in the log is what tells an operator which of the two happened.
    logger.info(
        "Featurebase settings prune: deleted %d of %d candidate rows (%s)",
        result.rowcount,
        len(ORPHAN_KEYS),
        ", ".join(ORPHAN_KEYS),
    )
    if result.rowcount == 0:
        # No args, so logging does no %-substitution here and the LIKE pattern
        # must not be escaped — it is meant to be copied out of the log as-is.
        logger.info(
            "No Featurebase rows found. Expected on an install that never "
            "configured it; if this instance did, check for a different spelling: "
            "SELECT key FROM platform_settings WHERE key ILIKE '%featurebase%';"
        )


def downgrade() -> None:
    """Deliberately a no-op, as in ``20260728_prune_orphan_settings``.

    Re-inserting a JWT secret this migration deleted is not something a
    downgrade can do, and no image worth rolling back to reads these keys.
    """
