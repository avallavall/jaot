"""Index the foreign keys that had no index (backend audit D-14)

PostgreSQL does not index foreign keys automatically. Without an index whose FIRST
column is the FK column, two things degrade as tables grow:

  * every join on that column falls back to a scan;
  * every DELETE or UPDATE of a parent row scans the whole child table to enforce the
    constraint.

The audit (2026-07-26) found 23 such columns. Five are deliberately left alone
because they point at things that are already scheduled to disappear, and indexing
them would be work thrown away:

  * ``user_favorites.model_id`` and ``recent_models.model_id`` -> ``model_catalog``
  * ``llm_conversations.organization_model_id`` -> ``organization_models``
    (all three tables/columns are on the legacy DROP list)
  * ``usage_records.user_id`` and ``withdrawals.schedule_id`` -> orphans of the
    monetisation layer removed by ADR-008; no ORM model, no callers.

That leaves the 18 below, all on live paths -- ``users.organization_id`` alone is read
by every org-scoped user lookup in a multi-tenant system.

Additive-only, per the project's migration rule: this adds indexes and nothing else,
so a rollback to previous images is safe. Indexes are created CONCURRENTLY inside an
autocommit block so the migration never takes a write lock on a live table.

Revision ID: 20260726_index_fks
Revises: 20260725_scenario_analysis
Create Date: 2026-07-26
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260726_index_fks"
down_revision = "20260725_scenario_analysis"
branch_labels = None
depends_on = None


# (table, column) -> index name is derived as ix_{table}_{column}
FK_INDEXES: tuple[tuple[str, str], ...] = (
    ("api_keys", "user_id"),
    ("formulation_ratings", "organization_id"),
    ("formulation_ratings", "user_id"),
    ("model_builder_documents", "created_by"),
    ("model_executions", "executed_by_user_id"),
    ("model_project_datasets", "created_by"),
    ("model_project_listings", "pinned_version_id"),
    ("model_project_versions", "created_by"),
    ("model_projects", "created_by"),
    ("model_projects", "workspace_id"),
    ("organizations", "owner_user_id"),
    ("refresh_tokens", "user_id"),
    ("solve_triggers", "created_by"),
    ("solve_triggers", "version_id"),
    ("users", "organization_id"),
    ("verification_requests", "requested_by"),
    ("workspace_invites", "organization_id"),
    ("workspaces", "created_by"),
)


def upgrade() -> None:
    # CONCURRENTLY cannot run inside a transaction block, hence autocommit.
    # IF NOT EXISTS keeps the migration idempotent on an environment where an index
    # was already added by hand.
    with op.get_context().autocommit_block():
        for table, column in FK_INDEXES:
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_{table}_{column} "
                f"ON {table} ({column})"
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for table, column in FK_INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS ix_{table}_{column}")
