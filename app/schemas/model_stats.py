"""Model statistics + health schema (Analyze surface).

Solver-agnostic, computed in one parse pass from an :class:`OptimizationProblem`
by :class:`app.services.model_stats_service`. Frozen onto each committed
``ModelProjectVersion`` (``stats_json`` / ``problem_class``) and served live for a
project draft via ``GET /projects/{id}/stats``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConditioningTier = Literal["ok", "mild", "poor", "severe"]
HealthBand = Literal["A", "B", "C", "D", "F"]


class BoundProfile(BaseModel):
    """How variable bounds are distributed."""

    free: int = Field(0, description="Both bounds None (-inf, +inf)")
    boxed: int = Field(0, description="Both bounds finite")
    one_sided: int = Field(0, description="Exactly one finite bound")
    binary: int = Field(0, description="Binary variables (0/1)")
    integers_missing_bounds: int = Field(
        0, description="INTEGER vars missing a lower or upper bound (weak branch-and-bound)"
    )


class CoefConditioning(BaseModel):
    """Coefficient magnitude spread — a numerical-conditioning signal."""

    min_abs: float | None = Field(None, description="Smallest non-zero |coefficient|")
    max_abs: float | None = Field(None, description="Largest |coefficient|")
    range_ratio: float | None = Field(None, description="max_abs / min_abs")
    tier: ConditioningTier = Field("ok", description="ok <1e6 < mild <1e9 < poor <1e12 < severe")


class HealthDeduction(BaseModel):
    """A single transparent deduction from the health score."""

    code: str
    points: int = Field(..., description="Points subtracted (positive number)")
    detail: str


class ModelHealth(BaseModel):
    """Auditable 0-100 health score. Hard errors cap the score (band F)."""

    score: int = Field(..., ge=0, le=100)
    band: HealthBand
    deductions: list[HealthDeduction] = Field(default_factory=list)
    has_hard_error: bool = False


class ModelStats(BaseModel):
    """Structural statistics of an optimization model."""

    var_total: int = 0
    var_continuous: int = 0
    var_integer: int = 0
    var_binary: int = 0

    constraint_total: int = 0
    constraints_by_operator: dict[str, int] = Field(default_factory=dict)

    objective_sense: str | None = None
    objective_terms: int = 0
    objective_quadratic: bool = False

    nonzeros: int = 0
    density: float = 0.0
    integrality_ratio: float = 0.0

    bound_profile: BoundProfile = Field(default_factory=BoundProfile)
    conditioning: CoefConditioning = Field(default_factory=CoefConditioning)

    problem_class: str | None = Field(None, description="LP/MILP/IP/BIP/QP/MIQP/QCP/MIQCP or None")

    warnings: list[str] = Field(default_factory=list)
    health: ModelHealth

    content_hash: str = ""
