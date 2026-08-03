"""MCP-facing request bodies reject unknown keys.

Measured against production (2026-08-02): ``update_model_project_draft`` called
with ``problem=`` instead of ``model_json`` succeeded apparently, saved nothing,
and the follow-up commit sealed an EMPTY model. A wrong argument name is the
typical LLM mistake and these bodies serve the MCP tools, so every input schema
on that surface carries ``extra="forbid"`` — a typo is a 422, never a silent
no-op that loses the caller's work.

``OptimizationProblem`` and its nested types stay permissive ON PURPOSE:
stored ``model_json`` documents are re-validated on every solve, and keys left
behind by older schema shapes must not brick a model that solves fine today.
"""

import pytest
from pydantic import ValidationError

from app.api.v2.projects import FromMarketplaceRequest
from app.api.v2.solve import MultiObjectiveSolveRequest
from app.schemas.model import ExecuteModelRequest
from app.schemas.model_project import (
    CommitRequest,
    DatasetCreate,
    DatasetUpdate,
    DraftUpdate,
    ProjectCreate,
    ProjectMetaUpdate,
)

_TINY_PROBLEM = {
    "name": "tiny",
    "variables": [{"name": "x", "type": "continuous", "lower_bound": 0, "upper_bound": 1}],
    "objective": {"sense": "maximize", "expression": "x"},
    "constraints": [],
}

_MO_CONFIG = {
    "mode": "weighted",
    "objectives": [
        {"expression": "x", "sense": "maximize", "weight": 0.5},
        {"expression": "x", "sense": "minimize", "weight": 0.5},
    ],
}

# (schema, minimal valid payload) — the payload must validate, and the same
# payload plus one unknown key must not.
CASES = [
    (ProjectCreate, {}),
    (ProjectMetaUpdate, {}),
    (DraftUpdate, {}),
    (CommitRequest, {"summary": "v1"}),
    (DatasetCreate, {"name": "base", "data_json": {}}),
    (DatasetUpdate, {}),
    (FromMarketplaceRequest, {}),
    (ExecuteModelRequest, {"input_data": {}}),
    (MultiObjectiveSolveRequest, {"problem": _TINY_PROBLEM, "config": _MO_CONFIG}),
]


@pytest.mark.unit
@pytest.mark.parametrize("schema,payload", CASES, ids=[s.__name__ for s, _ in CASES])
def test_mcp_request_schema_rejects_unknown_keys(schema, payload):
    schema.model_validate(payload)  # the minimal payload itself is valid

    with pytest.raises(ValidationError):
        schema.model_validate({**payload, "definitely_not_a_field": 1})
