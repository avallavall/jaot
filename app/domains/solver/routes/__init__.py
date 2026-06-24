"""Solve sub-router package.

Contains extracted endpoint modules:
- templates: Template listing, detail, and template-based solve endpoints
- file_io: File import (MPS, LP, CIP, JSON) upload and solve endpoints
- file_export: File export (MPS, LP, CIP, SOL, CSV, JSON) download endpoints
- insights: Auto-generated result analysis and insights
- analytics: Cross-execution aggregation, trends, and comparison

These endpoints are mounted under /solve by the parent router in router.py.
"""

from fastapi import APIRouter

from app.domains.solver.routes.analytics import router as analytics_router
from app.domains.solver.routes.file_export import router as file_export_router
from app.domains.solver.routes.file_io import router as file_io_router
from app.domains.solver.routes.insights import router as insights_router
from app.domains.solver.routes.templates import router as templates_router

router = APIRouter()
router.include_router(templates_router)
router.include_router(file_io_router)
router.include_router(file_export_router)
router.include_router(insights_router)
router.include_router(analytics_router)

__all__ = ["router"]
