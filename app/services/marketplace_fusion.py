"""P1.5 marketplace-fusion — the listing → marketplace-wire mapper.

The marketplace serves from the unified ``ModelProjectListing`` facet. Its PK is
``model_project_id`` (the marketplace identity); this module maps a listing onto the
public ``ModelCatalogResponse`` wire shape the frontend + API/MCP consumers expect.
"""

from __future__ import annotations

from app.models import ModelProjectListing
from app.schemas.model import ModelCatalogResponse


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
