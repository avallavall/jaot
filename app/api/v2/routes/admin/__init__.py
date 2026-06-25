"""Admin API routes - split into logical modules.

This package contains the admin API endpoints split into:
- organizations: Organization CRUD
- users: User CRUD
- api_keys: API Key management
- credits: Credit adjustments and transactions
- models: Model badge management

All admin routes require an authenticated user with admin role (is_admin=True).
Non-admin users receive HTTP 403.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v2.routes.admin.analytics import router as platform_analytics_router
from app.api.v2.routes.admin.api_keys import router as api_keys_router
from app.api.v2.routes.admin.credits import router as credits_router
from app.api.v2.routes.admin.feedback import router as feedback_router
from app.api.v2.routes.admin.marketplace import router as marketplace_router
from app.api.v2.routes.admin.models import router as models_router
from app.api.v2.routes.admin.organizations import router as organizations_router
from app.api.v2.routes.admin.scorecard import router as scorecard_router
from app.api.v2.routes.admin.settings import router as settings_router
from app.api.v2.routes.admin.users import router as users_router
from app.api.v2.routes.admin.withdrawals import router as withdrawals_router


async def get_admin_user(request: Request) -> Any:
    """Dependency that enforces admin-only access.

    Reads the user set by AuthMiddleware on request.state and verifies
    that the user has admin privileges (is_admin property).

    Raises:
        HTTPException: 403 if user is missing or not an admin.
    """
    user = getattr(request.state, "user", None)
    if not user or not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# Main router that combines all sub-routers — admin dependency gates everything
router = APIRouter(tags=["admin"], dependencies=[Depends(get_admin_user)])

router.include_router(organizations_router)
router.include_router(users_router)
router.include_router(api_keys_router)
router.include_router(credits_router)
router.include_router(feedback_router)
router.include_router(marketplace_router)
router.include_router(models_router)
router.include_router(scorecard_router)
router.include_router(settings_router)
router.include_router(withdrawals_router)
router.include_router(platform_analytics_router)

__all__ = ["router"]
