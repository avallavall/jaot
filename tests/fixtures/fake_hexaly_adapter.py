"""FakeHexalyAdapter implementing SolverAdapter Protocol without the hexaly SDK.

Used by CI jobs that run without the Hexaly SDK installed. Mirrors
the structural contract of ``HexalyAdapter`` (Plan 02) closely
enough that downstream tests — auto-routing, license gating, queue
routing — can run against it as a stand-in. D-19.

Deterministic known-answer: ``objective_value=42.0`` + variable
values assigned by index (``solution[var.name] = float(idx)``).
Plan 02 test authors may refine this if a test requires a specific
shape; keep it simple here to avoid future contract drift.
"""

from __future__ import annotations

from app.domains.solver.adapters.base import SolverCapabilities
from app.schemas.optimization import (
    OptimizationProblem,
    OptimizationResult,
    SolverStatus,
    VariableSolution,
)


class FakeHexalyAdapter:
    """Test double for HexalyAdapter — matches the SolverAdapter Protocol shape.

    Capabilities mirror D-11 exactly so tests pinning against the
    shared SolverCapabilities record keep working once the real
    adapter lands.
    """

    capabilities: SolverCapabilities = SolverCapabilities(
        name="hexaly",
        supports_continuous=True,
        supports_integer=True,
        supports_binary=True,
        supports_quadratic=True,
        supports_sensitivity=False,
        supports_warm_start=True,
        supports_multi_objective=False,
    )

    def __init__(self, fixed_status: SolverStatus = SolverStatus.OPTIMAL) -> None:
        self._status = fixed_status

    def is_available(self) -> bool:
        return True

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
    ) -> OptimizationResult:
        """Return a deterministic known-answer OptimizationResult.

        Variables are assigned ``float(idx)`` in the enumeration
        order they appear on ``problem.variables``. Objective fixed
        at 42.0. ``warm_start`` is accepted and ignored.
        """
        solution: dict[str, float] = {
            var.name: float(idx) for idx, var in enumerate(problem.variables)
        }
        variables = [
            VariableSolution(name=var.name, value=float(idx), type=var.type)
            for idx, var in enumerate(problem.variables)
        ]
        return OptimizationResult(
            status=self._status,
            objective_value=42.0,
            solution=solution,
            variables=variables,
            solve_time_seconds=0.01,
            warm_start_used=warm_start is not None,
        )
