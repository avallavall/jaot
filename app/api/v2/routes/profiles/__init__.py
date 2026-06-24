"""Profiles API routes - split into logical modules.

This package contains the profiles API endpoints split into:
- organizations: Organization public profiles
- users: User public profiles
- reviews: Model reviews and ratings
- admin: Admin profile management
"""

from fastapi import APIRouter

from app.api.v2.routes.profiles.admin import router as admin_router
from app.api.v2.routes.profiles.organizations import router as organizations_router
from app.api.v2.routes.profiles.reviews import router as reviews_router
from app.api.v2.routes.profiles.users import router as users_router

# Main router that combines all sub-routers
router = APIRouter(tags=["profiles"])

router.include_router(organizations_router)
router.include_router(users_router)
router.include_router(reviews_router)
router.include_router(admin_router)

__all__ = ["router"]
