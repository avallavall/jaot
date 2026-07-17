"""P1.5 F3 — backfill legacy marketplace rows into unified ModelProjects.

Data migration (additive): creates the shadow ``ModelProject`` (+ ``ModelProjectListing``
for catalog rows) for every ``model_catalog`` / ``organization_models`` row, preserving
ids, and copies the forward-FK columns added in F2. Idempotent + count-verified — the
logic lives in ``app.shared.db.p15_backfill`` so it is unit-tested against real seed data.
The legacy tables are UNTOUCHED (kept for dual-read through the F4 cutover).

Revision ID: 20260712_p15_backfill
Revises: 20260712_p15_listings
Create Date: 2026-07-12
"""

import logging

from alembic import op

from app.shared.db.p15_backfill import revert_backfill, run_backfill

revision = "20260712_p15_backfill"
down_revision = "20260712_p15_listings"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    counts = run_backfill(op.get_bind())
    logger.info("P1.5 backfill complete: %s", counts)


def downgrade() -> None:
    revert_backfill(op.get_bind())
