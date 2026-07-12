"""P1.5 marketplace-fusion read cutover, behind ``MARKETPLACE_FUSION_ENABLED``.

When the flag is on, the marketplace read endpoints serve from the unified
``ModelProjectListing`` facet instead of the legacy ``ModelCatalog`` table. The two
share column names (category / name / is_official / avg_rating / status / is_public /
…), so callers only need to swap the queried class and map the id: a listing's PK is
``model_project_id`` and the backfill PRESERVED ids, so ``model_project_id`` equals the
original catalog id — every downstream reference (impressions, detail links, activation)
keeps working unchanged.
"""

from __future__ import annotations

from typing import Any

from app.models import ModelProjectListing
from app.schemas.model import ModelCatalogResponse
from app.services.platform_settings_service import PlatformSettingsService as PSS


def is_fusion_enabled(db: Any) -> bool:
    """Whether the marketplace serves from the fused entities (flag, cached in PSS)."""
    return PSS.get_bool(db, "MARKETPLACE_FUSION_ENABLED")


def listing_to_catalog_response(listing: ModelProjectListing) -> ModelCatalogResponse:
    """Map a listing to the exact ``ModelCatalogResponse`` wire shape (id = project id).

    ``author_name`` / ``author_verified`` stay at their defaults; the endpoint fills them
    from the author org just as it does for a catalog row.
    """
    return ModelCatalogResponse(
        id=listing.model_project_id,
        name=listing.name,
        display_name=listing.display_name,
        description=listing.description,
        short_description=listing.short_description,
        scenario_description=listing.scenario_description,
        category=listing.category,
        tags=listing.tags,
        version=listing.version,
        is_official=listing.is_official,
        is_featured=listing.is_featured,
        total_activations=listing.total_activations,
        total_executions=listing.total_executions,
        avg_execution_time_ms=listing.avg_execution_time_ms,
        success_rate=listing.success_rate,
        avg_rating=listing.avg_rating,
        author_organization_id=listing.author_organization_id,
        logo_url=listing.logo_url,
        screenshot_urls=listing.screenshot_urls,
        section_overview=listing.section_overview,
        section_features=listing.section_features,
        section_how_it_works=listing.section_how_it_works,
        section_example_io=listing.section_example_io,
        section_changelog=listing.section_changelog,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
    )
