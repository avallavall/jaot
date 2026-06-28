"""Optimization model schemas (catalog, organization models, executions)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelCatalogResponse(BaseModel):
    """Response for a model in the catalog."""

    id: str
    name: str
    display_name: str
    description: str
    short_description: str | None = None
    scenario_description: str | None = None
    category: str
    tags: list[str] | None = None
    version: str
    is_official: bool
    is_featured: bool
    price_eur: float
    credits_per_execution: int
    total_activations: int
    total_executions: int
    avg_execution_time_ms: float | None = None
    success_rate: float | None = None
    avg_rating: float | None = None
    author_organization_id: str | None = None
    author_name: str | None = None
    author_verified: bool = False
    # Media
    logo_url: str | None = None
    screenshot_urls: list[str] | None = None
    # Rich description sections
    section_overview: str | None = None
    section_features: str | None = None
    section_how_it_works: str | None = None
    section_example_io: str | None = None
    section_changelog: str | None = None
    created_at: datetime
    updated_at: datetime  # D-06: exposes ORM column for sitemap lastModified

    model_config = ConfigDict(from_attributes=True)


class ModelCatalogListResponse(BaseModel):
    """Paginated list of catalog models."""

    items: list[ModelCatalogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class OrganizationModelResponse(BaseModel):
    """Response for an organization's activated model."""

    id: str
    organization_id: str
    catalog_id: str | None = None
    custom_name: str | None = None
    display_name: str
    description: str | None = None
    category: str | None = None
    generator_type: str | None = None
    is_active: bool
    is_favorite: bool
    total_executions: int
    total_credits_used: int
    last_executed_at: datetime | None = None
    credits_per_execution: int
    created_at: datetime
    is_official: bool | None = None
    tags: list[str] | None = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationModelListResponse(BaseModel):
    """Paginated list of organization models."""

    items: list[OrganizationModelResponse]
    total: int
    page: int
    page_size: int


class ActivateModelRequest(BaseModel):
    """Request to activate a model from the catalog."""

    custom_name: str | None = None


class CreatePrivateModelRequest(BaseModel):
    """Request to create a private model."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    category: str = "general"
    generator_type: str = Field(
        ..., description="Type: budget_allocation, knapsack, fertilizer, etc."
    )
    input_schema: dict[str, Any] = Field(default_factory=dict)
    input_fields: list[dict[str, Any]] = Field(default_factory=list)
    example_input: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] | None = None


class UpdateModelRequest(BaseModel):
    """Request to update an organization model."""

    custom_name: str | None = None
    custom_config: dict[str, Any] | None = None
    is_active: bool | None = None
    is_favorite: bool | None = None


class PublishModelRequest(BaseModel):
    """Request to publish a model to the marketplace."""

    display_name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=10)
    short_description: str | None = Field(None, max_length=500)
    category: str = "general"
    tags: list[str] | None = None
    price_eur: float = 0.0
    is_public: bool = True
    # Rich description sections
    section_overview: str | None = None
    section_features: str | None = None
    section_how_it_works: str | None = None
    section_example_io: str | None = None
    section_changelog: str | None = None


class UpdateCatalogSectionsRequest(BaseModel):
    """Request to update rich description sections on a published model."""

    section_overview: str | None = None
    section_features: str | None = None
    section_how_it_works: str | None = None
    section_example_io: str | None = None
    section_changelog: str | None = None


class ExecuteModelRequest(BaseModel):
    """Request to execute a model."""

    input_data: dict[str, Any]
    async_mode: bool = False


class ModelExecutionResponse(BaseModel):
    """Response for a model execution."""

    id: str
    organization_model_id: str | None = None
    status: str
    input_data: dict[str, Any]
    result_data: dict[str, Any] | None = None
    error_message: str | None = None
    execution_time_ms: int | None = None
    solver_status: str | None = None
    objective_value: float | None = None
    credits_consumed: int
    origin: str | None = None
    trigger_id: str | None = None
    # Provenance: the object this execution traces back to (builder_document,
    # llm_conversation, template, organization_model, trigger, imported_file).
    source_kind: str | None = None
    source_id: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ExecutionListResponse(BaseModel):
    """Paginated list of executions."""

    items: list[ModelExecutionResponse]
    total: int
    page: int
    page_size: int


class AsyncExecutionResponse(BaseModel):
    """Response for async execution start."""

    id: str
    execution_id: str
    task_id: str
    status: str = "pending"
    message: str = "Execution started"


class ExecutionStatusResponse(BaseModel):
    """Response for execution status check."""

    execution_id: str
    status: str
    progress: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class FavoriteResponse(BaseModel):
    """Response for favorite status."""

    model_id: str
    is_favorite: bool


class ReviewCreate(BaseModel):
    """Request to create a review."""

    rating: int = Field(..., ge=1, le=5)
    title: str | None = Field(None, max_length=200)
    comment: str | None = None


class ReviewResponse(BaseModel):
    """Response for a model review."""

    id: str
    catalog_id: str
    user_id: str
    user_name: str
    organization_name: str | None = None
    rating: int
    title: str | None = None
    comment: str | None = None
    created_at: datetime
    is_visible: bool = True

    model_config = ConfigDict(from_attributes=True)


class ReviewListResponse(BaseModel):
    """Paginated list of reviews."""

    items: list[ReviewResponse]
    total: int
    page: int
    page_size: int
    avg_rating: float | None = None
    rating_distribution: dict[int, int] | None = None
