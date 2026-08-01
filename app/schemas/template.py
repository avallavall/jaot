"""Schemas for the template surface under ``/solve``.

A template id resolves to one of two things — a YAML template definition or a
generator-backed marketplace listing — and both are served through the same
endpoint. :class:`TemplateDetailResponse` is therefore the union of the two
shapes: the fields a listing has no equivalent for are optional here, not
absent from the contract.
"""

from typing import Any

from pydantic import BaseModel, Field


class TemplateSummaryResponse(BaseModel):
    """One entry of the template catalog — the card, not the form.

    Deliberately without the long ``description``: it was 59% of a 90 KB listing
    (~22.6k tokens for an MCP client's first discovery call) and ``get_template``
    already serves it. ``short_description`` is what a card shows, and every
    template has one.
    """

    id: str
    name: str
    display_name: str
    short_description: str
    category: str
    tags: list[str] = Field(default_factory=list)
    problem_type_tags: list[str] = Field(default_factory=list)
    generator_type: str
    is_featured: bool = False
    estimated_variables: int | None = None
    estimated_constraints: int | None = None


class TemplateListResponse(BaseModel):
    """One page of the template catalog, optionally filtered.

    ``total`` counts everything that matched the filters, not the page — a client
    that reads only ``templates`` would otherwise think it had them all.
    """

    templates: list[TemplateSummaryResponse]
    total: int
    page: int = 1
    page_size: int = 0


class TemplateDetailResponse(BaseModel):
    """A template with everything needed to render its form and solve it.

    ``short_description``, ``problem_type_tags``, ``generator_params``,
    ``is_featured``, the estimates and ``version`` come from YAML definitions
    only; ``generator`` rides only on a marketplace listing.
    """

    id: str
    name: str
    display_name: str
    description: str
    category: str
    scenario_description: str | None = None
    tags: list[str] = Field(default_factory=list)
    generator_type: str | None = None
    input_schema: dict[str, Any] | None = None
    input_fields: list[dict[str, Any]] | None = None
    example_input: dict[str, Any] | None = None

    # YAML-only
    short_description: str | None = None
    problem_type_tags: list[str] | None = None
    generator_params: dict[str, Any] | None = None
    is_featured: bool | None = None
    estimated_variables: int | None = None
    estimated_constraints: int | None = None
    version: str | None = None

    # Marketplace-listing-only: the generator name, served alongside
    # ``generator_type`` for callers that read either.
    generator: str | None = None


class SolveMetadataResponse(BaseModel):
    """Categories and generator types available for model creation."""

    categories: list[str]
    generator_types: list[str]
    category_generators: dict[str, list[str]] = Field(
        description="Category -> generator types that have templates in it"
    )


class ExampleProblem(BaseModel):
    """A ready-to-solve sample problem."""

    name: str
    description: str
    problem: dict[str, Any]


class ExampleProblemsResponse(BaseModel):
    """Example optimization problems served for testing and onboarding."""

    examples: list[ExampleProblem]
