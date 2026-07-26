"""P1.5 marketplace-fusion — the listing → marketplace-wire mapper.

The marketplace serves from the unified ``ModelProjectListing`` facet. Its PK is
``model_project_id`` (the marketplace identity); this module maps a listing onto the
public ``ModelCatalogResponse`` wire shape the frontend + API/MCP consumers expect.
"""

from __future__ import annotations

from sqlalchemy import Float, case, cast
from sqlalchemy.orm import Session

from app.models import ModelProjectListing
from app.schemas.model import ModelCatalogResponse


def record_listing_execution(
    db: Session,
    listing_id: str,
    *,
    succeeded: bool,
    execution_time_ms: float | None,
) -> None:
    """Roll one execution onto a listing's public statistics.

    Both outcomes count: the run tally used to be bumped only on success, which
    left ``success_rate`` with no denominator to work from — it stayed NULL
    forever and the marketplace rendered a dash next to a model with fourteen
    recorded runs.

    Written as a single UPDATE of SQL expressions so parallel workers finishing
    solves for the same listing cannot lose an increment.

    ``timed_executions`` is counted apart from ``successful_executions`` on
    purpose: rows recorded before any timing was kept are backfilled as
    successes (which they were — only successes were ever tallied) but carry no
    duration, and dividing accumulated time by that larger count would report an
    average several times too fast. The average stays NULL until timed runs exist.
    """
    timed = execution_time_ms is not None and succeeded
    total = ModelProjectListing.total_executions + 1
    successful = ModelProjectListing.successful_executions + (1 if succeeded else 0)
    timed_count = ModelProjectListing.timed_executions + (1 if timed else 0)
    elapsed = ModelProjectListing.total_execution_time_ms + (execution_time_ms if timed else 0.0)

    db.query(ModelProjectListing).filter(ModelProjectListing.model_project_id == listing_id).update(
        {
            ModelProjectListing.total_executions: total,
            ModelProjectListing.successful_executions: successful,
            ModelProjectListing.timed_executions: timed_count,
            ModelProjectListing.total_execution_time_ms: elapsed,
            ModelProjectListing.success_rate: cast(successful, Float) / cast(total, Float),
            ModelProjectListing.avg_execution_time_ms: case(
                (timed_count > 0, cast(elapsed, Float) / cast(timed_count, Float)),
                else_=None,
            ),
        },
        synchronize_session=False,
    )


def listing_to_catalog_response(listing: ModelProjectListing) -> ModelCatalogResponse:
    """Map a listing to the exact ``ModelCatalogResponse`` wire shape (id = project id).

    ``author_name`` / ``author_verified`` stay at their defaults; the endpoint fills them
    from the author org just as it does for a catalog row.
    """
    return ModelCatalogResponse(
        id=listing.model_project_id,
        # "Use in studio" needs something to materialize: a pinned committed
        # version (community), a real generator, or — for officials — the
        # template YAML fallback (their 'generic' rows render from it, verified
        # live: official generic → 201). Community 'generic' rows backfilled
        # without content have none of these and 422 on materialize.
        can_open_in_studio=bool(
            listing.pinned_version_id
            or (listing.generator_type and listing.generator_type != "generic")
            or (listing.generator_type and listing.is_official)
        ),
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
