"""Rebuild the solved problem + solution from a stored execution row.

Both on-demand analyses (exact / A3 and what-if / L2) start from the same two
blobs an execution persists: the problem it solved and the solution it found.
Sharing one loader keeps their preconditions identical — a row the exact
analysis declines to read must not be one the scenario batch happily re-solves.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.schemas.optimization import OptimizationProblem

# Why a row cannot be analysed (surfaced verbatim as the analysis ``note``).
NO_SOLUTION = "no_solution"
NOT_A_PROBLEM = "not_a_problem"


class ExecutionPayloadError(Exception):
    """An execution that carries nothing analysable, with the reason slug."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ExecutionPayload:
    """The analysable content of one completed execution."""

    problem: OptimizationProblem
    solution: dict[str, float]
    objective_value: float | None


def load_execution_payload(
    input_data: Any,
    result_data: dict[str, Any] | None,
) -> ExecutionPayload:
    """Parse an execution's stored blobs, or raise ``ExecutionPayloadError``."""
    result = result_data or {}
    raw_solution = result.get("model")
    if not isinstance(raw_solution, dict) or not raw_solution:
        raise ExecutionPayloadError(NO_SOLUTION)

    try:
        problem = OptimizationProblem.model_validate(input_data)
    except (ValidationError, TypeError, ValueError) as exc:
        # Template / model executions may not store a flat problem.
        raise ExecutionPayloadError(NOT_A_PROBLEM) from exc

    solution: dict[str, float] = {}
    for key, value in raw_solution.items():
        try:
            solution[key] = float(value)
        except (TypeError, ValueError):
            continue

    objective_value = result.get("objective_value")
    if objective_value is not None:
        try:
            objective_value = float(objective_value)
        except (TypeError, ValueError):
            objective_value = None

    return ExecutionPayload(
        problem=problem,
        solution=solution,
        objective_value=objective_value,
    )
