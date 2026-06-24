"""Utility functions and helpers.

Modules:
- datetime_helpers: UTC time, expiration checks
- db_helpers: Database query shortcuts
- id_generator: ID and API key generation
- pagination: Query pagination utilities
- query_helpers: Generic query filters and sorting
- responses: Standard API response builders
- slug: URL slug generation
"""

from app.shared.utils.datetime_helpers import is_expired, utcnow
from app.shared.utils.id_generator import generate_api_key, generate_id, hash_api_key
from app.shared.utils.pagination import (
    PaginatedResponse,
    PaginationParams,
    create_paginated_response,
    paginate_query,
)
from app.shared.utils.query_helpers import (
    apply_filters,
    apply_search,
    apply_sorting,
    exists,
    get_or_404,
    get_or_none,
)
from app.shared.utils.responses import (
    created_response,
    deleted_response,
    error_response,
    success_response,
    updated_response,
)
from app.shared.utils.slug import generate_unique_slug, is_valid_slug, slugify

# Note: build_org_model_response is intentionally NOT re-exported here.
# It imports from app.models which creates a circular dependency when
# app.models imports app.utils. Import directly from app.shared.utils.model_helpers:
#   from app.shared.utils.model_helpers import build_org_model_response

__all__ = [
    "utcnow",
    "is_expired",
    "generate_id",
    "generate_api_key",
    "hash_api_key",
    "PaginationParams",
    "PaginatedResponse",
    "paginate_query",
    "create_paginated_response",
    "get_or_404",
    "get_or_none",
    "apply_sorting",
    "apply_search",
    "apply_filters",
    "exists",
    "success_response",
    "error_response",
    "deleted_response",
    "updated_response",
    "created_response",
    "slugify",
    "generate_unique_slug",
    "is_valid_slug",
]
