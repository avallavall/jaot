"""Admin-specific schemas.

Extended versions with stats and admin fields for CRUD operations.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrganizationCreate(BaseModel):
    """Create organization request.

    D-23: no per-organization request limits. One instance means one set of
    limits, read from settings on every request — the same decision that retired
    the four plan tiers.
    """

    name: str
    ai_builder_enabled: bool = False
    max_private_plugins: int = 5


class OrganizationUpdate(BaseModel):
    """Update organization request."""

    name: str | None = None
    ai_builder_enabled: bool | None = None
    max_private_plugins: int | None = None
    is_active: bool | None = None
    is_verified: bool | None = None


class OrganizationResponse(BaseModel):
    """Organization response with stats."""

    id: str
    name: str
    ai_builder_enabled: bool
    max_private_plugins: int
    is_active: bool
    is_verified: bool = False
    created_at: datetime

    # Stats
    user_count: int | None = None
    api_key_count: int | None = None
    model_count: int | None = None

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    """Create user request."""

    organization_id: str
    name: str
    email: str | None = None
    is_admin: bool = False
    can_build_plugins: bool = False


class UserUpdate(BaseModel):
    """Update user request."""

    name: str | None = None
    email: str | None = None
    is_admin: bool | None = None
    can_build_plugins: bool | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    """User response."""

    id: str
    organization_id: str
    name: str
    email: str | None
    is_admin: bool
    can_build_plugins: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class APIKeyCreate(BaseModel):
    """Create API key request."""

    organization_id: str
    user_id: str
    name: str
    description: str | None = None


class APIKeyResponse(BaseModel):
    """API key response."""

    id: str
    organization_id: str
    user_id: str
    name: str
    description: str | None
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    # Only returned on creation
    full_key: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CreditAdjustment(BaseModel):
    """Credit adjustment request."""

    organization_id: str
    amount: int = Field(..., description="Positive to add, negative to subtract")
    reason: str


class AdminPaginatedResponse(BaseModel):
    """Paginated response for admin endpoints."""

    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


class UpdateModelBadgesRequest(BaseModel):
    """Request to update model badges."""

    is_official: bool | None = None
    is_featured: bool | None = None
    is_public: bool | None = None


# --- Organization overview (read-only admin detail view) ---


class OrgOwnerSummary(BaseModel):
    """The user that owns an organization."""

    id: str
    name: str
    email: str | None = None


class OrgDetail(BaseModel):
    """Full organization detail for the admin overview (read-only)."""

    id: str
    name: str
    ai_builder_enabled: bool
    # True when the org has its own Anthropic key configured (BYOK). The key
    # itself is never exposed — only whether one exists.
    byok_configured: bool = False
    max_private_plugins: int
    is_active: bool
    is_verified: bool
    is_public_profile: bool
    slug: str | None = None
    website_url: str | None = None
    created_at: datetime
    owner_user_id: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrgCounts(BaseModel):
    """Aggregate counts for an organization."""

    users: int
    active_users: int
    api_keys: int
    active_api_keys: int
    models: int
    executions: int


class OrgExecutionStats(BaseModel):
    """Execution outcome breakdown for an organization."""

    total: int
    completed: int
    failed: int
    running: int


class OrgModelSummary(BaseModel):
    """A model that belongs to an organization."""

    id: str
    display_name: str
    catalog_id: str | None = None
    source: str  # "marketplace" | "custom"
    is_active: bool
    total_executions: int
    last_executed_at: datetime | None = None
    created_at: datetime


class OrgExecutionSummary(BaseModel):
    """A recent solve execution for an organization."""

    id: str
    status: str
    solver_name: str | None = None
    execution_time_ms: int | None = None
    objective_value: float | None = None
    model_display_name: str | None = None
    executed_by_user_id: str | None = None
    created_at: datetime


class OrganizationOverviewResponse(BaseModel):
    """Rich read-only overview of one organization for platform admins."""

    organization: OrgDetail
    owner: OrgOwnerSummary | None = None
    counts: OrgCounts
    execution_stats: OrgExecutionStats
    users: list[UserResponse]
    api_keys: list[APIKeyResponse]
    models: list[OrgModelSummary]
    recent_executions: list[OrgExecutionSummary]


class AdminCountPair(BaseModel):
    """Total vs. active count of one resource on the admin dashboard."""

    total: int
    active: int


class AdminModelCounts(BaseModel):
    """Marketplace counts. ``activated_total`` counts fork projects seeded from a listing."""

    catalog_total: int
    catalog_public: int
    activated_total: int


class AdminStatsResponse(BaseModel):
    """Admin dashboard headline numbers."""

    organizations: AdminCountPair
    users: AdminCountPair
    api_keys: AdminCountPair
    models: AdminModelCounts


class ModelVisibilityResponse(BaseModel):
    """Outcome of flipping a listing's public visibility."""

    success: bool
    is_public: bool


class ModelBadgesResponse(BaseModel):
    """The listing's badge state after an update."""

    success: bool
    id: str
    is_official: bool
    is_featured: bool
    is_public: bool


class ScorecardCategoryScore(BaseModel):
    """One scoring dimension of a template, with the notes that justify it."""

    name: str
    score: int
    max_score: int
    notes: list[str] = Field(default_factory=list)


class ScorecardTemplateScore(BaseModel):
    """A single template's quality score."""

    template_id: str
    template_name: str
    category: str
    generator_type: str
    total: int
    max_total: int
    grade: str
    categories: list[ScorecardCategoryScore]


class TemplateScorecardResponse(BaseModel):
    """Automated quality scoring across all YAML templates.

    ``filtered_count`` rides only when the request narrowed the report; the
    aggregates always describe the FULL run, not the filtered subset.
    """

    total_templates: int
    average_score: float
    grade_distribution: dict[str, int]
    by_generator_type: dict[str, float]
    top_5: list[str]
    bottom_5: list[str]
    templates: list[ScorecardTemplateScore]
    filtered_count: int | None = None


class SettingResetResponse(BaseModel):
    """Outcome of resetting one platform setting to its registry default.

    ``reset=False`` carries ``reason`` instead of a value — the key is unknown
    or readonly, which is not an error the caller should retry.
    """

    key: str
    reset: bool
    default_value: Any = None
    reason: str | None = None
