"""API v2 routes package.

Contains modular route definitions:
- models/: Model management, catalog, execution, favorites
"""

from app.api.v2.routes.models import router as models_router

__all__ = ["models_router"]
