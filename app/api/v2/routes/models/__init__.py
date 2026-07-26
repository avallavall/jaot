"""Models API routes - split into logical modules.

This package contains the models API endpoints split into:
- favorites: Favorites and recents management
- catalog: Marketplace catalog browsing
- execution: Model execution and history
- analysis: Post-solve analysis of an execution (exact + what-if batch)
- media: Listing media management (logo, screenshots, sections)

P1.5 fusion: the legacy my-models CRUD (OrganizationModel) and the legacy
publish flow are retired — the single model entity is ModelProject, managed
via /api/v2/projects (publishing = POST /projects/{id}/publish).
"""

from fastapi import APIRouter

from app.api.v2.routes.models.analysis import router as analysis_router
from app.api.v2.routes.models.catalog import router as catalog_router
from app.api.v2.routes.models.execution import router as execution_router
from app.api.v2.routes.models.favorites import router as favorites_router
from app.api.v2.routes.models.media import router as media_router


def create_models_router() -> APIRouter:
    """Create and configure the models router with all sub-routers.

    Returns:
        Configured APIRouter with prefix="/models"
    """
    router = APIRouter(prefix="/models", tags=["models"])

    # Include sub-routers (order matters for route matching)
    # Static routes first, then dynamic /{model_id} routes
    router.include_router(favorites_router)  # /favorites, /recents
    router.include_router(catalog_router)  # /catalog, /catalog/{id}
    router.include_router(execution_router)  # /async/{id}, /executions/all
    # AFTER execution: its /executions/all must keep matching before this module's
    # /executions/{execution_id}/… routes.
    router.include_router(analysis_router)  # /executions/{id}/exact-analysis, …
    router.include_router(
        media_router
    )  # /catalog/{id}/logo, /catalog/{id}/screenshots, /catalog/{id}/sections

    return router


router = create_models_router()

__all__ = ["router", "create_models_router"]
