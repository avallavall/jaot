"""Pydantic v2 schemas for LLM-powered formulation generation.

Covers: formulation structure (variables, constraints, objective),
chat messages, SSE events, and validation errors.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Formulation structure (matches Anthropic structured-output JSON schema)


class FormulationVariable(BaseModel):
    """A decision variable in the optimization formulation."""

    name: str = Field(..., description="Variable identifier (e.g. x_1, workers_A)")
    type: Literal["continuous", "integer", "binary"] = Field(
        ..., description="Variable domain type"
    )
    lower_bound: float | None = Field(None, description="Lower bound (None = unbounded)")
    upper_bound: float | None = Field(None, description="Upper bound (None = unbounded)")
    description: str = Field(..., description="Plain-language description of this variable")


class FormulationConstraint(BaseModel):
    """A constraint in the optimization formulation."""

    name: str = Field(..., description="Constraint identifier")
    expression: str = Field(..., description="Mathematical expression (e.g. 'x_1 + x_2 <= 100')")
    description: str = Field(..., description="Plain-language description of this constraint")


class FormulationObjective(BaseModel):
    """The objective function of the optimization formulation."""

    sense: Literal["minimize", "maximize"] = Field(..., description="Optimization direction")
    expression: str = Field(..., description="Mathematical expression to optimize")
    description: str = Field(..., description="Plain-language description of the objective")


class Formulation(BaseModel):
    """Complete structured formulation produced by the LLM.

    This schema is exported as JSON Schema for use with Anthropic's
    structured output feature (output_config).
    """

    problem_name: str = Field(..., description="Short name for the problem")
    summary: str = Field(
        ...,
        description="2-3 sentence plain-language explanation of the problem and approach",
    )
    variables: list[FormulationVariable] = Field(..., description="Decision variables")
    constraints: list[FormulationConstraint] = Field(..., description="Problem constraints")
    objective: FormulationObjective = Field(..., description="Objective function")


# Export JSON schema for Anthropic structured outputs
def _add_additional_properties_false(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively add additionalProperties: false to all object types.
    Required by Anthropic's JSON schema structured output."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            schema["additionalProperties"] = False
        for value in schema.values():
            if isinstance(value, dict):
                _add_additional_properties_false(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _add_additional_properties_false(item)
    return schema


_raw_schema = Formulation.model_json_schema()
# Inline $defs into the schema and add additionalProperties: false
if "$defs" in _raw_schema:
    import json as _json

    _schema_str = _json.dumps(_raw_schema)
    for _def_name, def_schema in _raw_schema["$defs"].items():
        _add_additional_properties_false(def_schema)
    _add_additional_properties_false(_raw_schema)
else:
    _add_additional_properties_false(_raw_schema)
FORMULATION_JSON_SCHEMA: dict[str, Any] = _raw_schema


# Chunked generation schemas (for very large problems)


class VariablesChunk(BaseModel):
    """Chunk 1: Variables and objective for chunked generation."""

    problem_name: str = Field(..., description="Short name for the problem")
    summary: str = Field(..., description="Problem summary")
    variables: list[FormulationVariable] = Field(..., description="Decision variables")
    objective: FormulationObjective = Field(..., description="Objective function")


class ConstraintsChunk(BaseModel):
    """Chunk 2: Constraints for chunked generation."""

    constraints: list[FormulationConstraint] = Field(..., description="Problem constraints")


def _build_chunk_schema(model_class: type[BaseModel]) -> dict[str, Any]:
    """Build Anthropic-compatible JSON schema from a Pydantic model."""
    raw = model_class.model_json_schema()
    if "$defs" in raw:
        for def_schema in raw["$defs"].values():
            _add_additional_properties_false(def_schema)
    _add_additional_properties_false(raw)
    return raw


VARIABLES_CHUNK_SCHEMA: dict[str, Any] = _build_chunk_schema(VariablesChunk)
CONSTRAINTS_CHUNK_SCHEMA: dict[str, Any] = _build_chunk_schema(ConstraintsChunk)


class ChatMessageRequest(BaseModel):
    """User sends a message to the LLM."""

    message: str = Field(..., min_length=1, max_length=10000)
    use_advanced_model: bool = Field(
        default=False,
        description="Use the advanced model with adaptive thinking for complex problems",
    )
    response_type: str = Field(
        default="formulation",
        description="Response type: 'formulation' for structured JSON, 'explanation' for plain text",
        pattern="^(formulation|explanation)$",
    )


class ExplainSolutionRequest(BaseModel):
    """Request a plain-language explanation of a solved optimization model.

    Provide ``execution_id`` to load the solution + sensitivity from a persisted
    ``ModelExecution`` (organization ownership is enforced), or pass the
    ``formulation`` / ``solution`` / ``sensitivity`` inline. ``execution_id`` takes
    precedence when both are supplied.
    """

    execution_id: str | None = Field(
        default=None, description="ModelExecution id to load solution + sensitivity from"
    )
    formulation: dict[str, Any] | None = Field(
        default=None, description="Inline formulation (variables/constraints/objective)"
    )
    solution: dict[str, Any] | None = Field(
        default=None, description="Inline solution (variable values + objective)"
    )
    sensitivity: dict[str, Any] | None = Field(
        default=None, description="Inline sensitivity analysis"
    )
    use_advanced_model: bool = Field(
        default=False,
        description="Use the advanced model with adaptive thinking for the explanation",
    )


class ExplainScenariosRequest(BaseModel):
    """Request the plain-language reading of a finished what-if batch (L2).

    The scenarios themselves are already cached on the execution; the only choice
    the caller has is which model narrates them.
    """

    use_advanced_model: bool = Field(
        default=False,
        description="Use the advanced model with adaptive thinking for the explanation",
    )


class ExplainInfeasibilityRequest(BaseModel):
    """Request a plain-language explanation of WHY a model is INFEASIBLE.

    Provide ``execution_id`` to load the formulation + persisted IIS analysis from a
    ``ModelExecution`` (organization ownership is enforced), or pass ``formulation`` /
    ``infeasibility`` inline. ``execution_id`` takes precedence when both are supplied.
    When no IIS is available the explanation falls back to heuristic reasoning, clearly
    flagged as such.
    """

    execution_id: str | None = Field(
        default=None, description="ModelExecution id to load the formulation + IIS analysis from"
    )
    formulation: dict[str, Any] | None = Field(
        default=None, description="Inline formulation (variables/constraints/objective)"
    )
    infeasibility: dict[str, Any] | None = Field(
        default=None,
        description="Inline IIS analysis (iis_constraints/iis_variable_bounds/conflict_type/method)",
    )
    use_advanced_model: bool = Field(
        default=False,
        description="Use the advanced model with adaptive thinking for the explanation",
    )


class ExplainModelRequest(BaseModel):
    """Request a plain-language explanation of an optimization MODEL (not yet solved).

    Provide ``project_id`` to explain a ModelProject (its mutable draft, or a specific
    committed ``version_id``); organization ownership is enforced. Or pass the
    ``formulation`` inline (``stats`` is computed when omitted). ``project_id`` takes
    precedence when both are supplied.
    """

    project_id: str | None = Field(
        default=None, description="ModelProject id to explain (draft or a committed version)"
    )
    version_id: str | None = Field(
        default=None, description="Committed version id to explain; omit to explain the draft"
    )
    formulation: dict[str, Any] | None = Field(
        default=None, description="Inline formulation (variables/constraints/objective)"
    )
    stats: dict[str, Any] | None = Field(
        default=None, description="Inline ModelStats; computed from the formulation when omitted"
    )
    use_advanced_model: bool = Field(
        default=False,
        description="Use the advanced model with adaptive thinking for the explanation",
    )


class ExplainVersionDiffRequest(BaseModel):
    """Request a plain-language narration of the CHANGE between two model versions.

    The structural diff is computed server-side (``model_project_service.diff_versions``)
    and the LLM only narrates it. Organization ownership is enforced on the project and
    both versions.
    """

    project_id: str = Field(..., description="ModelProject id owning both versions")
    from_version_id: str = Field(..., description="The earlier (base) version id")
    to_version_id: str = Field(..., description="The later (target) version id")
    use_advanced_model: bool = Field(
        default=False,
        description="Use the advanced model with adaptive thinking for the explanation",
    )


class ChatMessageResponse(BaseModel):
    """A message in a conversation (returned to client)."""

    id: str
    role: str
    content: str
    formulation_json: dict[str, Any] | None = None
    created_at: datetime


class ConversationResponse(BaseModel):
    """Full conversation with messages and current formulation.

    ``model_id`` (builder document) and ``model_project_id`` (studio project) say
    what the conversation is *about*: at most one is set, and the listing is
    filtered by either.
    """

    id: str
    created_at: datetime
    expires_at: datetime
    messages: list[ChatMessageResponse] = []
    current_formulation: dict[str, Any] | None = None
    model_id: str | None = None
    model_project_id: str | None = None


class SSEEvent(BaseModel):
    """Typed SSE event payload for streaming responses."""

    event: str = Field(
        ..., description="Event type: delta, formulation, validation_errors, done, error"
    )
    data: str = Field(..., description="JSON-encoded event data")


class FormulationValidationError(BaseModel):
    """A validation issue found in a formulation."""

    field: str = Field(..., description="Which part: 'variable', 'constraint', or 'objective'")
    index: int | None = Field(None, description="Index within the field list (if applicable)")
    message: str = Field(..., description="Human-readable error description")
    suggestion: str | None = Field(None, description="Suggested fix")
