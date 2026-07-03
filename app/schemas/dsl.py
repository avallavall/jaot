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


class DSLInspectRequest(BaseModel):
    """A JModel source whose data-facing declarations we want to list (S2a)."""

    source: str = Field(
        ...,
        max_length=1_000_000,
        description="JModel source text — parsed only, never grounded.",
    )


class DSLSetDecl(BaseModel):
    """A declared set, as the dataset editor needs to see it."""

    name: str
    has_inline_values: bool = Field(
        ..., description="True when the source defines members inline (:=)."
    )


class DSLParamDecl(BaseModel):
    """A declared param: its index sets define the dataset key shape."""

    name: str
    index_sets: list[str] = Field(..., description="Empty for a scalar param.")
    arity: int = Field(..., description="len(index_sets) — 0 for a scalar.")
    has_inline_values: bool = Field(
        ..., description="True when the source defines values inline (:=)."
    )


class DSLInspectResponse(BaseModel):
    """Parse-only view of a source's sets/params (skeleton + live validation).

    On success ``ok`` is true and ``sets``/``params`` list every declaration
    (inline-valued or dataset-fillable); on a lex/parse failure ``ok`` is false
    and ``error`` describes it.
    """

    ok: bool
    sets: list[DSLSetDecl] | None = None
    params: list[DSLParamDecl] | None = None
    error: DSLCompileError | None = None


class DSLStatusResponse(BaseModel):
    """Whether the JModel DSL feature is enabled on this instance."""

    enabled: bool
