"""Schemas for the JModel DSL compile endpoint (P5).

The DSL lowers a declarative source into the flat :class:`OptimizationProblem`;
these models are the request/response wire shapes for ``/api/v2/dsl``.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.optimization import OptimizationProblem


class DSLCompileRequest(BaseModel):
    """A JModel source to compile, optionally against a named dataset."""

    source: str = Field(
        ...,
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
    arity: int = Field(
        ...,
        description=(
            "Flat dataset-key arity — the sum of the index sets' dimensions "
            "(tuple sets count one per component); 0 for a scalar."
        ),
    )
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


class DSLLatexRequest(BaseModel):
    """A JModel source to pretty-print as symbolic math (B1)."""

    source: str = Field(
        ...,
        description="JModel source text — parsed only, never grounded.",
    )


class DSLLatexLine(BaseModel):
    """One rendered LaTeX line plus the source name (objective/constraint/variable)."""

    latex: str = Field(..., description="Valid KaTeX math-mode source.")
    label: str | None = Field(default=None, description="The declaration's name, for a caption.")


class DSLLatexModel(BaseModel):
    """A JModel rendered as symbolic math: objective, constraint families, domains."""

    objective: DSLLatexLine | None = None
    constraints: list[DSLLatexLine] = Field(default_factory=list)
    variables: list[DSLLatexLine] = Field(
        default_factory=list, description="Variable domain lines (type + bounds)."
    )


class DSLLatexResponse(BaseModel):
    """Parse-only symbolic-math view of a source (the JModel split-pane, B1).

    On success ``ok`` is true and ``model`` holds the rendered lines; on a lex/parse
    failure ``ok`` is false and ``error`` describes it. Never grounded, so it
    succeeds for declaration-only sources exactly like ``/dsl/inspect``.
    """

    ok: bool
    model: DSLLatexModel | None = None
    error: DSLCompileError | None = None


class DSLDegroundRequest(BaseModel):
    """A flat problem to reconstruct as a compact JModel draft (B2)."""

    problem: OptimizationProblem
    allow_dataset: bool = Field(
        default=False,
        description=(
            "When true, derive the GENERAL formulation (declaration-only sets/params) "
            "and return the data separately as `dataset` — the model/data separation "
            "JModel is for. When false, the draft is self-contained (data inlined)."
        ),
    )


class DSLDegroundResponse(BaseModel):
    """A best-effort JModel draft derived from a flat problem (B2).

    ``source`` is the reconstructed JModel when a compact structure was recovered
    AND verifiably round-trips to an equivalent problem; it is ``None`` (a graceful
    decline, NOT an error) when the flat model has no recoverable compact form.
    With ``allow_dataset``, ``dataset`` carries the set members and param values in
    the standard JModel dataset shape (``{"sets": …, "params": …}``) and the source
    is the pure formulation; the caller should store it as a project dataset and
    compile the source against it.
    """

    source: str | None = Field(
        default=None,
        description="Reconstructed JModel draft, or null when none is recoverable.",
    )
    dataset: dict | None = Field(
        default=None,
        description=(
            "JModel dataset JSON with the draft's data (only when allow_dataset and "
            "the model carries indexed data; null for scalar/self-contained drafts)."
        ),
    )
    reason: Literal["too_large", "not_representable", "error"] | None = Field(
        default=None,
        description=(
            "Why there is no draft (only when source is null): `too_large` — no compact "
            "structure and the flat model is past the scalar-draft budget; "
            "`not_representable` — every candidate draft failed the round-trip "
            "verification; `error` — the de-grounder crashed (logged server-side)."
        ),
    )


# --- B3: generate a JModel source with the LLM (vision + compile-validate-retry) ---

# Claude's native document/image vision — the media types we forward as content blocks.
# Images (png/jpeg/gif/webp) ride as ``image`` blocks; PDFs as ``document`` blocks, so
# a screenshot of a thesis formulation or a spec PDF is read directly — no OCR/poppler.
DSL_GENERATE_IMAGE_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp"}
)
DSL_GENERATE_PDF_TYPE = "application/pdf"
DSL_GENERATE_MEDIA_TYPES: frozenset[str] = DSL_GENERATE_IMAGE_TYPES | {DSL_GENERATE_PDF_TYPE}

# Per-attachment and per-request caps. Claude allows ~5 MB per image and ~32 MB per
# request; we stay well under. ``data`` is base64, so the decoded byte size is ~3/4 of
# the string length — the string cap below keeps a single attachment under ~5 MB decoded.
DSL_GENERATE_MAX_ATTACHMENTS = 4
DSL_GENERATE_MAX_ATTACHMENT_CHARS = 7_000_000
DSL_GENERATE_MAX_DESCRIPTION_CHARS = 8_000
#: Unlike the compile/inspect/latex sources — which are bounded only by the
#: operator's hardware — everything on this request is forwarded to Anthropic and
#: billed per token against the platform's monthly EUR budget. These caps protect a
#: real external cost, not a made-up notion of "too big", so they stay.
DSL_GENERATE_MAX_SOURCE_CHARS = 1_000_000


class DSLGenerateAttachment(BaseModel):
    """One vision attachment: a base64 image or PDF the model reads to formulate."""

    media_type: str = Field(
        ...,
        description="MIME type — one of image/png|jpeg|gif|webp or application/pdf.",
    )
    data: str = Field(
        ...,
        max_length=DSL_GENERATE_MAX_ATTACHMENT_CHARS,
        description="Base64-encoded file bytes (no data: URL prefix).",
    )


class DSLGenerateRequest(BaseModel):
    """A natural-language description (+ optional vision attachments) to formulate.

    At least one of ``description`` / ``attachments`` must be non-empty (validated in
    the route). ``current_source`` seeds a refine-this-model turn when the user already
    has a draft in the editor.
    """

    description: str = Field(
        default="",
        max_length=DSL_GENERATE_MAX_DESCRIPTION_CHARS,
        description="Plain-language description of the optimization problem to model.",
    )
    attachments: list[DSLGenerateAttachment] = Field(
        default_factory=list,
        max_length=DSL_GENERATE_MAX_ATTACHMENTS,
        description="Screenshots / PDFs of a formulation for Claude to read (vision).",
    )
    current_source: str | None = Field(
        default=None,
        max_length=DSL_GENERATE_MAX_SOURCE_CHARS,
        description="An existing JModel draft to refine instead of starting fresh.",
    )
    use_advanced_model: bool = Field(
        default=False,
        description=(
            "Formulate with the advanced model instead of the default one. Same opt-in the "
            "chats and the explainers expose; costs more per call, so it is never implicit."
        ),
    )


class DSLGenerateResponse(BaseModel):
    """Result of an AI JModel generation (B3).

    ``ok`` is true when the generated ``source`` VERIFIABLY compiles (the same
    deterministic validator the editor uses); it is false when every retry still
    failed to compile — in which case ``source`` still holds the best-effort draft
    and ``error`` names the last compile failure, so the user lands on an editable
    starting point rather than nothing. Honest by construction: a compiling source
    is proven, a non-compiling one is flagged, never silently passed off as valid.
    """

    ok: bool
    source: str | None = Field(
        default=None, description="The generated JModel source (best-effort even when !ok)."
    )
    error: DSLCompileError | None = Field(
        default=None, description="Last compile error when the source never compiled."
    )
    attempts: int = Field(
        default=0, description="How many generate→compile rounds ran (for observability)."
    )
