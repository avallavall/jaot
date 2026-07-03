"""Schemas for the JModel DSL compile endpoint (P5).

The DSL lowers a declarative source into the flat :class:`OptimizationProblem`;
these models are the request/response wire shapes for ``/api/v2/dsl``.
"""

from pydantic import BaseModel, Field

from app.schemas.optimization import OptimizationProblem


class DSLCompileRequest(BaseModel):
    """A JModel source to compile, optionally against a named dataset."""

    source: str = Field(
        ...,
        max_length=1_000_000,
        description="JModel source text (sets / params / indexed families / sum / filters).",
    )
    dataset_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Optional org-owned dataset (scenario) whose set members / param values "
            "fill a declaration-only source (§8 model/data separation)."
        ),
    )


class DSLCompileError(BaseModel):
    """A single lex, parse, or grounding error."""

    message: str = Field(..., description="Human-readable error message")
    position: int | None = Field(
        default=None, description="0-based character offset in the source, when known"
    )


class DSLCompileResponse(BaseModel):
    """Result of compiling a JModel source.

    On success ``ok`` is true and ``problem`` holds the lowered flat problem; on
    failure ``ok`` is false and ``error`` describes the first failure.
    """

    ok: bool
    problem: OptimizationProblem | None = None
    error: DSLCompileError | None = None


class DSLStatusResponse(BaseModel):
    """Whether the JModel DSL feature is enabled on this instance."""

    enabled: bool
