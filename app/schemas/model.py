"""Optimization model schemas (catalog, organization models, executions)."""

from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


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
    total_activations: int
    total_executions: int
    avg_execution_time_ms: float | None = None
    success_rate: float | None = None
    avg_rating: float | None = None
    author_organization_id: str | None = None
    author_name: str | None = None
    author_verified: bool = False
    # Additive (2026-07-17): whether "Use in studio" can materialize this listing —
    # it needs a generator facet OR a pinned committed version. Legacy demo rows
    # backfilled without content have neither; the UI disables the CTA up front
    # instead of failing the click with a 422.
    can_open_in_studio: bool = True
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
    # Every category in the visible catalogue, not just the ones on this page.
    # The filter sidebar used to derive its options from `items`, so it offered a
    # different set on every page and most of the catalogue could not be filtered.
    categories: list[str] = []


# Every visitor to a model's page downloads its sections, so an uncapped one is
# a page nobody can open: a 5 MB overview was accepted and stored. Generous
# enough for real prose — about twenty-five pages per section — and far above
# the longest text any listing carries today.
MAX_SECTION_CHARS = 50_000
MAX_DESCRIPTION_CHARS = 10_000


class PublishModelRequest(BaseModel):
    """Request to publish a model to the marketplace."""

    display_name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=10, max_length=MAX_DESCRIPTION_CHARS)
    short_description: str | None = Field(None, max_length=500)
    category: str = "general"
    tags: list[str] | None = None
    is_public: bool = True
    # Rich description sections
    section_overview: str | None = Field(None, max_length=MAX_SECTION_CHARS)
    section_features: str | None = Field(None, max_length=MAX_SECTION_CHARS)
    section_how_it_works: str | None = Field(None, max_length=MAX_SECTION_CHARS)
    section_example_io: str | None = Field(None, max_length=MAX_SECTION_CHARS)
    section_changelog: str | None = Field(None, max_length=MAX_SECTION_CHARS)


class UpdateCatalogSectionsRequest(BaseModel):
    """Request to update rich description sections on a published model."""

    section_overview: str | None = Field(None, max_length=MAX_SECTION_CHARS)
    section_features: str | None = Field(None, max_length=MAX_SECTION_CHARS)
    section_how_it_works: str | None = Field(None, max_length=MAX_SECTION_CHARS)
    section_example_io: str | None = Field(None, max_length=MAX_SECTION_CHARS)
    section_changelog: str | None = Field(None, max_length=MAX_SECTION_CHARS)

    # A wrong field name must be a 422, never a silent no-op. `{"sections": {...}}`
    # answered 200 with the listing unchanged, so a client with the wrong shape
    # believed it had saved.
    model_config = ConfigDict(extra="forbid")


class ExecuteModelRequest(BaseModel):
    """Request to execute a model."""

    input_data: dict[str, Any]
    async_mode: bool = False

    # MCP-facing body: a wrong argument name must be a 422, never a silent no-op.
    model_config = ConfigDict(extra="forbid")


class ExecutionSummaryResponse(BaseModel):
    """One row of an executions table: everything except the run's payloads.

    ``input_data`` and ``result_data`` hold the whole compiled problem and the
    whole solution. The detail view needs them; a table of twenty rows does not,
    and was paying for them: 37,720,232 bytes measured for one page, 90,922,886
    at one point, to paint six columns, with 6.2 s to first paint on localhost.
    The list queries no longer even load those columns, so the cost is gone at
    the database as well as on the wire.

    The one value the table did read out of them, the trigger's name, is a field
    of its own here, batch-filled the same way ``model_name`` is. The objective
    it read from ``result_data`` was always available as ``objective_value``.
    """

    id: str
    # The ModelProject this run executed (P1.5 fusion). The legacy
    # organization_model_id is served for HISTORIC rows only and drops in the
    # contract release (its value equals the backfilled project id anyway).
    model_project_id: str | None = None
    organization_model_id: str | None = None
    status: str
    error_message: str | None = None
    execution_time_ms: int | None = None
    solver_status: str | None = None
    # The solver the run REQUESTED. Under "auto" the one that actually ran is
    # result_data.solver_used; readers should prefer that and fall back here.
    solver_name: str | None = None
    objective_value: float | None = None
    origin: str | None = None
    trigger_id: str | None = None
    # NOT on the ORM row: the list endpoints batch-fill it from the trigger, so a
    # table can name the schedule a run came from without carrying its input.
    trigger_name: str | None = None
    # Provenance: the object this execution traces back to (builder_document,
    # llm_conversation, template, organization_model, trigger, imported_file).
    source_kind: str | None = None
    source_id: str | None = None
    # §8/S1: dataset provenance — the named dataset the model was compiled
    # against. `dataset_name` is a snapshot that survives dataset deletion.
    dataset_id: str | None = None
    dataset_name: str | None = None
    # Resolved display name + author of the model this run came from (studio
    # ModelProject or activated org model). NOT on the ORM row — the list endpoint
    # batch-fills it from source_kind/source_id (model_project) or
    # organization_model_id, so the history table can show a name, not an id.
    model_name: str | None = None
    model_author: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ModelExecutionResponse(ExecutionSummaryResponse):
    """A single execution, with the input it ran on and the result it produced.

    Served by the detail endpoint, where the payloads are the point.
    """

    #: Read from the row's ``problem_data`` first, falling back to the raw
    #: column. A column of a solver comparison stores no copy of the problem —
    #: it solves the parent's snapshot, and ``problem_data`` is what knows that.
    #: The alias lives here rather than at the call sites because
    #: ``model_validate(execution)`` binds by field NAME: a route that shaped its
    #: response that way silently answered with an empty problem, and neither a
    #: type checker nor a grep for ``.input_data`` could find it.
    input_data: dict[str, Any] = Field(validation_alias=AliasChoices("problem_data", "input_data"))
    result_data: dict[str, Any] | None = None

    # `populate_by_name` so the explicit constructor can still pass `input_data=`.
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ExecutionListResponse(BaseModel):
    """Paginated list of executions."""

    items: list[ExecutionSummaryResponse]
    total: int
    page: int
    page_size: int


class AsyncExecutionResponse(BaseModel):
    """Acknowledgement of a model execution queued on the async pipeline.

    ``id`` and ``execution_id`` are the same value, served under both names for
    callers that read either.
    """

    id: str
    execution_id: str
    model_project_id: str | None = None
    task_id: str
    status: str = "pending"
    message: str = "Execution started"
    ws_url: str | None = None
    poll_url: str | None = None


class ExecutionStatusResponse(BaseModel):
    """Poll response for a queued model execution.

    One shape for every Celery state — ``status`` discriminates and the rest are
    filled per branch, mirroring the solve endpoint's own poll contract.
    """

    task_id: str | None = None
    execution_id: str
    status: str
    message: str | None = None
    result: Any = None
    execution_time_ms: int | None = None
    error: str | None = None

    # Live progress meta (Celery PROGRESS state).
    progress: float | None = None
    iteration: int | None = None
    objective_value: float | None = None
    gap: float | None = None
    timestamp: str | None = None


class ExecutionCancelResponse(BaseModel):
    """Outcome of a cancellation request against a queued model execution."""

    task_id: str
    execution_id: str
    cancelled: bool
    message: str


class FavoriteResponse(BaseModel):
    """Response for favorite status."""

    model_id: str
    is_favorite: bool


class FavoriteModelSummary(BaseModel):
    """One entry of the favourites list.

    A deliberate subset of ``ModelCatalogResponse``: the favourites shelf shows a
    card, not a listing page, and sending the full catalog payload would put the
    rich description sections and the media URLs on a screen that renders none
    of them.
    """

    id: str
    name: str
    display_name: str
    description: str
    category: str
    author_name: str
    is_official: bool
    is_featured: bool
    avg_rating: float | None = None


class FavoriteListResponse(BaseModel):
    """The user's favourite models."""

    items: list[FavoriteModelSummary]
    total: int


class RecentModelSummary(BaseModel):
    """One entry of the recently-opened list."""

    id: str
    name: str
    display_name: str
    category: str
    author_name: str
    last_accessed: datetime
    access_count: int


class RecentListResponse(BaseModel):
    """The user's recently opened models, most recent first."""

    items: list[RecentModelSummary]
    total: int


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


class LogoUploadResponse(BaseModel):
    """URL of the stored logo image."""

    url: str


class ScreenshotUploadResponse(BaseModel):
    """The uploaded screenshot's URL plus the listing's full screenshot list."""

    url: str
    screenshots: list[str]


class ScreenshotListResponse(BaseModel):
    """The listing's screenshots after a deletion."""

    screenshots: list[str]


class CatalogModelSchemaResponse(BaseModel):
    """The input contract of a catalog model: what to fill in to run it."""

    id: str
    name: str
    generator_type: str | None = None
    input_schema: dict[str, Any] | None = None
    input_fields: list[dict[str, Any]] | None = None
    example_input: dict[str, Any] | None = None
    scenario_description: str | None = None
