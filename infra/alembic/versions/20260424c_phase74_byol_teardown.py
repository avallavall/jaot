"""Phase 7.4 BYOL teardown — drop solver_licenses, purge audit_logs, add auto_route_reason.

============================================================================
CLAUDE.md EXCEPTION — DESTRUCTIVE MIGRATION
============================================================================
This migration violates the project's standing "additive-only" rule
(see CLAUDE.md "Migrations: additive-only"). The exception is explicitly
authorized by Phase 7.4 decisions D-04 (DROP TABLE solver_licenses) and
D-09 (DELETE audit_logs rows with action LIKE 'solver_license_%').

Justification: Pre-launch greenfield. Zero BYOL customers in production
confirmed. The platform pivots from BYOL Hexaly to a single platform-wide
license held at /etc/jaot/hexaly.lic (D-01); the entire BYOL surface is
removed in Plans 02-08 of Phase 7.4. This migration removes the now-orphan
schema state.

Forward-only per D-05. Safety net: pg_dump pre-deploy step in
deploy/deploy.sh::standard-rotate (Plan 07.4-10) writes
/home/jaot/backups-manual/pre-phase-7.4-{timestamp}.sql.gz before this
migration runs in production. Rollback procedure: restore the dump manually
+ git revert + rebuild image.

D-13 absorption (INT-01 from superseded Phase 7.2): adds the
auto_route_reason column to model_executions so the auto-routing telemetry
introduced in Plan 07.4-05 has a place to land. The column is nullable —
solves with explicit solver_name (no auto-routing) leave it NULL.

Note re: organizations.has_hexaly_license — RESEARCH Area 9 verified the
column does NOT exist in the codebase (zero grep hits in app/, infra/).
The CONTEXT.md D-04 mention of "drops any legacy has_hexaly_license column
if present" is therefore a no-op here; an information_schema probe is added
defensively just in case staging or local DBs picked it up from an early
prototype.

Revision ID: 20260424c_phase74_byol_teardown
Revises: 20260424b_audit_log_ref_id
Create Date: 2026-04-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260424c_phase74_byol_teardown"
down_revision = "20260424b_audit_log_ref_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # D-09: purge BYOL audit_logs rows BEFORE dropping the table they
    # reference (in this case there is no FK from audit_logs to
    # solver_licenses, but the atomic ordering keeps the runbook simple).
    # The ``action`` column on audit_logs is the AuditAction enum value
    # — the 5 values were 'solver_license_uploaded', '..._validated',
    # '..._rotated', '..._expired', '..._deleted' (deleted from the enum
    # in Plan 07.4-07; rows deleted here).
    # ------------------------------------------------------------------
    op.execute("DELETE FROM audit_logs WHERE action LIKE 'solver_license_%'")

    # ------------------------------------------------------------------
    # D-04: drop solver_licenses. The table has FKs INTO organizations.id
    # and users.id (RESEARCH Area 9) — those are FROM solver_licenses TO
    # the parent tables, so dropping the child table requires no parent-
    # side action.
    # ------------------------------------------------------------------
    op.drop_table("solver_licenses")

    # ------------------------------------------------------------------
    # Defensive cleanup of legacy has_hexaly_license column on
    # organizations. RESEARCH Area 9 verified this column does NOT exist
    # in the canonical schema, but staging snapshots may have inherited
    # it from an early prototype. Drop conditionally via information_schema.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'organizations'
                  AND column_name = 'has_hexaly_license'
            ) THEN
                ALTER TABLE organizations DROP COLUMN has_hexaly_license;
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------
    # D-13 (INT-01 absorbed): additive column for auto-routing telemetry.
    # Slugs from app/domains/solver/services/auto_router.py:
    # lp_routed_to_highs | quadratic_routed_to_hexaly |
    # hexaly_unavailable_fallback | milp_routed_to_scip.
    # The longest slug is 32 chars; String(64) leaves headroom for future
    # reason additions.
    # ------------------------------------------------------------------
    op.add_column(
        "model_executions",
        sa.Column("auto_route_reason", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Forward-only per D-05 — no rollback path.

    Phase 7.4 is destructive (DROP TABLE solver_licenses + DELETE BYOL
    audit_logs rows). The original `pass` body silently "succeeded" on
    `alembic downgrade -1` while leaving the schema in the upgraded state,
    masking destructive accidents. Per D-05 the migration is forward-only;
    rollback requires manual restoration from the pre-deploy pg_dump
    written by `deploy/deploy.sh::standard-rotate` plus a git revert.
    """
    raise NotImplementedError(
        "Phase 7.4 migration is forward-only (D-05). "
        "Restore from /home/jaot/backups-manual/pre-phase-7.4-*.sql.gz "
        "manually and git revert the Phase 7.4 commit set."
    )
