"""P1.5 F3 — idempotent backfill: legacy marketplace rows → unified ``ModelProject``.

Pure SQLAlchemy-Core (no ORM, no domains → import-contract-clean) so the alembic
migration and its test share ONE implementation. Structural-only: it creates the
shadow ``ModelProject`` (+ ``ModelProjectListing`` for catalog rows) and links the
forward FKs, PRESERVING ids (a catalog/org-model id becomes the project id — ADR-006).
It does NOT materialize generators or move model content; the legacy tables stay for
dual-read during the F4 transition.

Idempotent: every INSERT is guarded by ``NOT EXISTS`` on the preserved id and every
UPDATE by ``... IS NULL``, so re-running is a no-op. Because ids are preserved, the
four forward-FK columns are a straight id copy (every catalog id referenced by a
review/favorite/recent/impression has a project with the same id after the catalog
pass).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.shared.utils.datetime_helpers import utcnow

#: The synthetic org that owns official catalog models (they have no author org).
SYSTEM_ORG_ID = "org_jaot_official"
SYSTEM_ORG_NAME = "JAOT Official"


def _ensure_system_org(bind: Any) -> None:
    """Create the officials-owning org if absent (idempotent).

    Only the NOT-NULL columns without a server default are set explicitly; the
    money columns are nullable / server-defaulted after ADR-008 so they are omitted.
    """
    bind.execute(
        text(
            """
            INSERT INTO organizations (
                id, name, plan, rate_limit_per_minute, rate_limit_per_day,
                is_active, max_private_plugins, ai_builder_enabled,
                is_verified, is_public_profile, created_at
            )
            VALUES (
                :id, :name, 'free', 60, 2000,
                true, 5, false,
                false, false, :now
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": SYSTEM_ORG_ID, "name": SYSTEM_ORG_NAME, "now": utcnow()},
    )


def run_backfill(bind: Any, *, system_org_id: str = SYSTEM_ORG_ID) -> dict[str, int]:
    """Backfill legacy marketplace rows into ModelProjects. Returns row counts.

    Order matters: catalog → projects+listings FIRST (so every catalog id has a
    project), THEN org-models → projects, THEN the forward-FK id copies, THEN a
    count check that raises if any legacy row was left unmapped.
    """
    _ensure_system_org(bind)

    # 1. Catalog rows → ModelProject (id preserved; officials → system org).
    r_cat_proj = bind.execute(
        text(
            """
            INSERT INTO model_projects (
                id, organization_id, name, description, status, source_type,
                committed_count, draft_lock_version, created_at, updated_at
            )
            SELECT
                c.id,
                COALESCE(c.author_organization_id, :sys_org),
                c.display_name,
                c.description,
                'active',
                'marketplace',
                0, 0,
                c.created_at, c.updated_at
            FROM model_catalog c
            WHERE NOT EXISTS (SELECT 1 FROM model_projects p WHERE p.id = c.id)
            """
        ),
        {"sys_org": system_org_id},
    )

    # 2. Catalog rows → ModelProjectListing (the marketplace facet; near-direct copy).
    r_cat_listing = bind.execute(
        text(
            """
            INSERT INTO model_project_listings (
                model_project_id, name, display_name, description, short_description,
                scenario_description, category, tags, generator_type, input_schema,
                input_fields, example_input, version, status, author_organization_id,
                is_official, total_activations, total_executions, avg_execution_time_ms,
                success_rate, avg_rating, is_featured, is_public, logo_url, screenshot_urls,
                section_overview, section_features, section_how_it_works, section_example_io,
                section_changelog, created_at, updated_at, published_at
            )
            SELECT
                c.id, c.name, c.display_name, c.description, c.short_description,
                c.scenario_description, c.category, c.tags, c.generator_type, c.input_schema,
                c.input_fields, c.example_input, c.version, c.status, c.author_organization_id,
                c.is_official, c.total_activations, c.total_executions, c.avg_execution_time_ms,
                c.success_rate, c.avg_rating, c.is_featured, c.is_public, c.logo_url,
                c.screenshot_urls, c.section_overview, c.section_features, c.section_how_it_works,
                c.section_example_io, c.section_changelog, c.created_at, c.updated_at,
                c.published_at
            FROM model_catalog c
            WHERE NOT EXISTS (
                SELECT 1 FROM model_project_listings l WHERE l.model_project_id = c.id
            )
            """
        )
    )

    # 3. OrganizationModel rows → ModelProject (id preserved, own org kept). These are
    #    activations/private models, NOT marketplace listings — no listing row. The
    #    legacy row stays for dual-read; its content is resolved in F4.
    r_org_proj = bind.execute(
        text(
            """
            INSERT INTO model_projects (
                id, organization_id, name, status, source_type, source_ref,
                committed_count, draft_lock_version, created_at, updated_at, archived_at
            )
            SELECT
                o.id, o.organization_id,
                COALESCE(
                    o.custom_name, c.display_name, o.private_definition->>'name', 'Activated Model'
                ),
                CASE WHEN o.is_active THEN 'active' ELSE 'archived' END,
                CASE WHEN o.catalog_id IS NOT NULL THEN 'marketplace' ELSE 'import' END,
                o.catalog_id,
                0, 0,
                o.created_at, o.updated_at,
                CASE WHEN o.is_active THEN NULL ELSE o.updated_at END
            FROM organization_models o
            LEFT JOIN model_catalog c ON c.id = o.catalog_id
            WHERE NOT EXISTS (SELECT 1 FROM model_projects p WHERE p.id = o.id)
            """
        )
    )

    # 4. Stamp the forward link on the legacy org-model row (id preserved → self).
    bind.execute(
        text(
            """
            UPDATE organization_models
            SET source_model_project_id = id
            WHERE source_model_project_id IS NULL
            """
        )
    )

    # 5. Forward-FK id copies (every referenced catalog id now has a project).
    r_reviews = bind.execute(
        text(
            "UPDATE model_reviews SET model_project_id = catalog_id WHERE model_project_id IS NULL"
        )
    )
    r_favorites = bind.execute(
        text("UPDATE user_favorites SET model_project_id = model_id WHERE model_project_id IS NULL")
    )
    r_recents = bind.execute(
        text("UPDATE recent_models SET model_project_id = model_id WHERE model_project_id IS NULL")
    )
    r_views = bind.execute(
        text(
            "UPDATE model_view_events SET model_project_id = catalog_model_id "
            "WHERE model_project_id IS NULL"
        )
    )

    # 6. Count verification — every legacy catalog/org-model row must now map to a
    #    project, and every catalog row must have a listing. A mismatch aborts the
    #    (transactional) migration rather than shipping a half-fused schema.
    unmapped_catalog = bind.execute(
        text(
            "SELECT count(*) FROM model_catalog c "
            "WHERE NOT EXISTS (SELECT 1 FROM model_projects p WHERE p.id = c.id)"
        )
    ).scalar_one()
    unmapped_orgmodels = bind.execute(
        text(
            "SELECT count(*) FROM organization_models o "
            "WHERE NOT EXISTS (SELECT 1 FROM model_projects p WHERE p.id = o.id)"
        )
    ).scalar_one()
    catalog_without_listing = bind.execute(
        text(
            "SELECT count(*) FROM model_catalog c "
            "WHERE NOT EXISTS (SELECT 1 FROM model_project_listings l "
            "WHERE l.model_project_id = c.id)"
        )
    ).scalar_one()
    if unmapped_catalog or unmapped_orgmodels or catalog_without_listing:
        raise RuntimeError(
            "P1.5 backfill count mismatch: "
            f"unmapped_catalog={unmapped_catalog}, "
            f"unmapped_orgmodels={unmapped_orgmodels}, "
            f"catalog_without_listing={catalog_without_listing}"
        )

    return {
        "projects_from_catalog": r_cat_proj.rowcount or 0,
        "listings": r_cat_listing.rowcount or 0,
        "projects_from_org_models": r_org_proj.rowcount or 0,
        "reviews_linked": r_reviews.rowcount or 0,
        "favorites_linked": r_favorites.rowcount or 0,
        "recents_linked": r_recents.rowcount or 0,
        "views_linked": r_views.rowcount or 0,
    }


def revert_backfill(bind: Any, *, system_org_id: str = SYSTEM_ORG_ID) -> None:
    """Best-effort reverse of ``run_backfill`` (for the migration downgrade).

    Deletes the shadow projects/listings whose ids came from the legacy tables and
    nulls the forward-FK columns. Safe because backfilled projects share their id
    with a still-present catalog/org-model row.
    """
    for table in ("model_reviews", "user_favorites", "recent_models", "model_view_events"):
        bind.execute(text(f"UPDATE {table} SET model_project_id = NULL"))  # noqa: S608 — fixed names

    bind.execute(
        text(
            "UPDATE organization_models SET source_model_project_id = NULL "
            "WHERE source_model_project_id = id"
        )
    )
    # Listings first (FK to projects), then the shadow projects, then the system org.
    bind.execute(
        text(
            "DELETE FROM model_project_listings "
            "WHERE model_project_id IN (SELECT id FROM model_catalog)"
        )
    )
    bind.execute(
        text(
            "DELETE FROM model_projects WHERE id IN ("
            "  SELECT id FROM model_catalog UNION SELECT id FROM organization_models"
            ")"
        )
    )
    bind.execute(
        text(
            "DELETE FROM organizations WHERE id = :sys_org "
            "AND NOT EXISTS (SELECT 1 FROM model_projects p WHERE p.organization_id = :sys_org)"
        ),
        {"sys_org": system_org_id},
    )
