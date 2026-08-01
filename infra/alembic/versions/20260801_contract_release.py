"""Contract release (D-26): retire the pre-fusion marketplace schema.

The P1.5 fusion made ``ModelProject`` own a model's lifecycle and
``ModelProjectListing`` its marketplace facet. The tables it replaced —
``model_catalog`` and ``organization_models`` — and the six forward-FK columns
that pointed at them have been dual-written-then-unused ever since. Every one of
those columns is NULL for all rows written after the fusion, and no application
code reads them any more.

This is the release that removes them, so ``alembic --autogenerate`` produces
reliable diffs again instead of proposing to re-drop the same legacy every time.

**This migration is not rollback-safe, by nature rather than by omission.** A
rollback restores container images, not schema. ``downgrade()`` below rebuilds
the tables and columns so the schema shape returns, but the *rows* are gone —
the legacy marketplace content is not recoverable from here. Restore from backup
if that data is ever needed again.

Two things it fixes on the way out:

* **Reviews had lost their uniqueness guarantee.** ``ix_model_review_user_catalog``
  was UNIQUE on (user_id, catalog_id), but every review written since the fusion
  leaves catalog_id NULL, and Postgres does not treat two NULLs as equal — so the
  index admitted unlimited duplicates. ``create_review`` checks for an existing
  review in Python first, but that is a read-then-write with no lock: two
  concurrent posts could both pass it. The replacement index is UNIQUE on
  (user_id, model_project_id), which is what the rule always meant.

* **``recent_models.access_count`` was a String holding a number**, so every
  increment cast to integer and back.

``model_executions.organization_model_id`` is deliberately KEPT (its foreign key
is dropped, the column stays). 55 historic runs in the reference install carry it
and it is the only model identity they have: the GDPR export falls back to it,
platform analytics separates legacy from project runs by it, and the execution
detail endpoint returns it. It becomes an opaque id, like ``source_id``.

Revision ID: 20260801_contract_release
Revises: 20260731_prune_featurebase
Create Date: 2026-08-01
"""

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision = "20260801_contract_release"
down_revision = "20260731_prune_featurebase"
branch_labels = None
depends_on = None


# (table, column) pairs whose only purpose was to point at the legacy tables.
_LEGACY_FK_COLUMNS = [
    ("model_reviews", "catalog_id"),
    ("user_favorites", "model_id"),
    ("recent_models", "model_id"),
    ("model_view_events", "catalog_model_id"),
    ("featured_placements", "catalog_model_id"),
    ("llm_conversations", "organization_model_id"),
]

# ADR-008 removed billing; these columns on `organizations` have been unmapped
# since, kept only by the additive-only rule.
_CREDIT_COLUMNS = [
    "credits_balance",
    "credits_used_month",
    "credits_earned",
    "low_credits_notified",
    "credits_subscription",
    "credits_purchased",
]


def _table_exists(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _column_exists(bind, table: str, column: str) -> bool:
    if not _table_exists(bind, table):
        return False
    return any(c["name"] == column for c in sa.inspect(bind).get_columns(table))


def _index_exists(bind, table: str, name: str) -> bool:
    if not _table_exists(bind, table):
        return False
    return any(i["name"] == name for i in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. Reviews: restore the uniqueness the fusion silently removed -------
    #
    # Deduplicate first: the unique index cannot be created over existing
    # duplicates, and this migration must not fail halfway through on an install
    # that accumulated some while the guarantee was off. Keeps the newest review
    # per (user, model) — the one the author most recently meant to say.
    if _column_exists(bind, "model_reviews", "model_project_id"):
        removed = bind.execute(
            sa.text(
                """
                DELETE FROM model_reviews
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, row_number() OVER (
                            PARTITION BY user_id, model_project_id
                            ORDER BY created_at DESC, id DESC
                        ) AS rn
                        FROM model_reviews
                        WHERE model_project_id IS NOT NULL
                    ) ranked
                    WHERE rn > 1
                )
                """
            )
        ).rowcount
        if removed:
            logger.warning(
                "Removed %d duplicate review(s) before enforcing one-per-user-per-model",
                removed,
            )

    for stale_index in (
        "ix_model_review_catalog_rating",
        "ix_model_review_user_catalog",
        "ix_model_reviews_catalog_id",
    ):
        if _index_exists(bind, "model_reviews", stale_index):
            op.drop_index(stale_index, table_name="model_reviews")

    if not _index_exists(bind, "model_reviews", "ix_model_review_project_rating"):
        op.create_index(
            "ix_model_review_project_rating",
            "model_reviews",
            ["model_project_id", "rating"],
        )
    if not _index_exists(bind, "model_reviews", "ix_model_review_user_project"):
        op.create_index(
            "ix_model_review_user_project",
            "model_reviews",
            ["user_id", "model_project_id"],
            unique=True,
        )

    # --- 2. View events: index first, then the column it covers ---------------
    if _index_exists(bind, "model_view_events", "ix_mve_model_type_created"):
        op.drop_index("ix_mve_model_type_created", table_name="model_view_events")

    # --- 3. Drop the forward-FK columns --------------------------------------
    for table, column in _LEGACY_FK_COLUMNS:
        if _column_exists(bind, table, column):
            op.drop_column(table, column)

    # --- 4. Executions keep their id, lose the constraint --------------------
    #
    # Dropping the parent table would take the FK with it, but naming it makes
    # the intent explicit: the column survives on purpose.
    if _table_exists(bind, "model_executions"):
        for fk in sa.inspect(bind).get_foreign_keys("model_executions"):
            if fk["referred_table"] == "organization_models" and fk["name"]:
                op.drop_constraint(fk["name"], "model_executions", type_="foreignkey")

    # --- 5. The legacy tables themselves -------------------------------------
    # organization_models first: it has an FK into model_catalog.
    for table in ("organization_models", "model_catalog"):
        if _table_exists(bind, table):
            op.drop_table(table)

    # --- 6. access_count becomes the integer it always was --------------------
    #
    # Runs last on purpose, and defensively: by this point steps 3-5 have already
    # dropped columns and tables, so a failure here leaves a half-applied release
    # with no forward path. Two cases the naive cast gets wrong:
    #
    #   * the column is ALREADY integer — `Base.metadata.create_all` (the
    #     bootstrap path in app/shared/db/init_db.py) builds it from the current
    #     ORM, where it is Integer, and `NULLIF(integer, '')` is a type error;
    #   * the text is non-numeric — '', '  ', or anything else a decade of rows
    #     might hold. `regexp` + `NULLIF` turns those into the 1 they mean.
    if _column_exists(bind, "recent_models", "access_count"):
        current_type = next(
            c["type"]
            for c in sa.inspect(bind).get_columns("recent_models")
            if c["name"] == "access_count"
        )
        if not isinstance(current_type, sa.Integer):
            op.execute(
                "ALTER TABLE recent_models "
                "ALTER COLUMN access_count TYPE INTEGER "
                "USING COALESCE("
                "  NULLIF(regexp_replace(COALESCE(access_count, ''), '\\D', '', 'g'), '')::INTEGER,"
                "  1"
                ")"
            )
        op.execute("ALTER TABLE recent_models ALTER COLUMN access_count SET DEFAULT 1")

    # --- 7. The money-era columns ADR-008 left behind -------------------------
    for column in _CREDIT_COLUMNS:
        if _column_exists(bind, "organizations", column):
            op.drop_column("organizations", column)


def downgrade() -> None:
    """Rebuild the schema shape. The rows are NOT recoverable — restore a backup."""
    bind = op.get_bind()

    for column in _CREDIT_COLUMNS:
        if not _column_exists(bind, "organizations", column):
            col_type = sa.Boolean() if column == "low_credits_notified" else sa.Integer()
            default = "false" if column == "low_credits_notified" else "0"
            op.add_column(
                "organizations",
                sa.Column(column, col_type, nullable=True, server_default=default),
            )

    if _column_exists(bind, "recent_models", "access_count"):
        op.execute("ALTER TABLE recent_models ALTER COLUMN access_count DROP DEFAULT")
        op.execute(
            "ALTER TABLE recent_models "
            "ALTER COLUMN access_count TYPE VARCHAR "
            "USING access_count::VARCHAR"
        )
        op.execute("ALTER TABLE recent_models ALTER COLUMN access_count SET DEFAULT '1'")

    if not _table_exists(bind, "model_catalog"):
        op.create_table(
            "model_catalog",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("short_description", sa.String(500), nullable=True),
            sa.Column("scenario_description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(64), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("generator_type", sa.String(64), nullable=False),
            sa.Column("input_schema", sa.JSON(), nullable=False),
            sa.Column("input_fields", sa.JSON(), nullable=False),
            sa.Column("example_input", sa.JSON(), nullable=False),
            sa.Column("version", sa.String(16), nullable=True),
            sa.Column("status", sa.String(32), nullable=True),
            sa.Column("author_organization_id", sa.String(64), nullable=True),
            sa.Column("is_official", sa.Boolean(), nullable=True),
            sa.Column("total_activations", sa.Integer(), nullable=True),
            sa.Column("total_executions", sa.Integer(), nullable=True),
            sa.Column("avg_execution_time_ms", sa.Float(), nullable=True),
            sa.Column("success_rate", sa.Float(), nullable=True),
            sa.Column("avg_rating", sa.Float(), nullable=True),
            sa.Column("is_featured", sa.Boolean(), nullable=True),
            sa.Column("is_public", sa.Boolean(), nullable=True),
            sa.Column("logo_url", sa.String(500), nullable=True),
            sa.Column("screenshot_urls", sa.JSON(), nullable=True),
            sa.Column("section_overview", sa.Text(), nullable=True),
            sa.Column("section_features", sa.Text(), nullable=True),
            sa.Column("section_how_it_works", sa.Text(), nullable=True),
            sa.Column("section_example_io", sa.Text(), nullable=True),
            sa.Column("section_changelog", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["author_organization_id"], ["organizations.id"], ondelete="SET NULL"
            ),
        )

    if not _table_exists(bind, "organization_models"):
        op.create_table(
            "organization_models",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("catalog_id", sa.String(64), nullable=True),
            sa.Column("custom_name", sa.String(255), nullable=True),
            sa.Column("custom_config", sa.JSON(), nullable=True),
            sa.Column("private_definition", sa.JSON(), nullable=True),
            sa.Column("source_model_project_id", sa.String(64), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("is_favorite", sa.Boolean(), nullable=True),
            sa.Column("total_executions", sa.Integer(), nullable=True),
            sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["catalog_id"], ["model_catalog.id"], ondelete="SET NULL"),
        )

    for table, column in _LEGACY_FK_COLUMNS:
        if _table_exists(bind, table) and not _column_exists(bind, table, column):
            op.add_column(table, sa.Column(column, sa.String(64), nullable=True))

    if _index_exists(bind, "model_reviews", "ix_model_review_user_project"):
        op.drop_index("ix_model_review_user_project", table_name="model_reviews")
    if _index_exists(bind, "model_reviews", "ix_model_review_project_rating"):
        op.drop_index("ix_model_review_project_rating", table_name="model_reviews")

    if _column_exists(bind, "model_reviews", "catalog_id"):
        op.create_index("ix_model_reviews_catalog_id", "model_reviews", ["catalog_id"])
        op.create_index("ix_model_review_catalog_rating", "model_reviews", ["catalog_id", "rating"])
        op.create_index(
            "ix_model_review_user_catalog",
            "model_reviews",
            ["user_id", "catalog_id"],
            unique=True,
        )

    if _column_exists(bind, "model_view_events", "catalog_model_id"):
        op.create_index(
            "ix_mve_model_type_created",
            "model_view_events",
            ["catalog_model_id", "event_type", "created_at"],
        )
