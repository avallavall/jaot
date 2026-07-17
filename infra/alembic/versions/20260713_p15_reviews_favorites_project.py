"""P1.5 G4 — key reviews / favorites / recents on the unified Model (model_project_id).

The fusion serves the marketplace from ``model_project_listings``; a community model
published from the studio has NO ``model_catalog`` row, so a review / favorite / recent
can no longer require a legacy catalog FK. Make ``model_reviews.catalog_id``,
``user_favorites.model_id`` and ``recent_models.model_id`` NULLABLE (additive) and swap
the favorites/recents uniqueness onto ``(user_id, model_project_id)`` — the backfill
already filled ``model_project_id`` on every existing row, so the new unique index has no
NULLs to worry about. The legacy columns + their old unique constraints stay inert until
the contract release drops them.

Revision ID: 20260713_p15_reviews_fav
Revises: 20260713_p15_view_events
Create Date: 2026-07-13
"""

from alembic import op

revision = "20260713_p15_reviews_fav"
down_revision = "20260713_p15_view_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("model_reviews", "catalog_id", nullable=True)

    op.alter_column("user_favorites", "model_id", nullable=True)
    op.drop_constraint("uq_user_model_favorite", "user_favorites", type_="unique")
    op.create_index(
        "uq_user_project_favorite",
        "user_favorites",
        ["user_id", "model_project_id"],
        unique=True,
    )

    op.alter_column("recent_models", "model_id", nullable=True)
    op.drop_constraint("uq_user_model_recent", "recent_models", type_="unique")
    op.create_index(
        "uq_user_project_recent",
        "recent_models",
        ["user_id", "model_project_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_user_project_recent", table_name="recent_models")
    op.create_unique_constraint("uq_user_model_recent", "recent_models", ["user_id", "model_id"])
    op.alter_column("recent_models", "model_id", nullable=False)

    op.drop_index("uq_user_project_favorite", table_name="user_favorites")
    op.create_unique_constraint("uq_user_model_favorite", "user_favorites", ["user_id", "model_id"])
    op.alter_column("user_favorites", "model_id", nullable=False)

    op.execute('ALTER TABLE "model_reviews" ALTER COLUMN catalog_id SET NOT NULL')
