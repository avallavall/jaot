"""
Universal Optimization Problem Schema

This module defines the JSON schema for optimization problems that can be
solved by the universal SCIP-based solver.

Example problem (Production Planning):
{
    "name": "production_planning",
    "description": "Maximize profit from producing widgets",

    "objective": {
        "sense": "maximize",
        "expression": "50*widgets_a + 40*widgets_b + 60*widgets_c"
    },

    "variables": [
        {"name": "widgets_a", "type": "integer", "lower_bound": 0, "upper_bound": 100},
        {"name": "widgets_b", "type": "integer", "lower_bound": 0, "upper_bound": 80},
        {"name": "widgets_c", "type": "integer", "lower_bound": 0, "upper_bound": 50}
    ],

    "constraints": [
        {
            "name": "machine_hours",
            "expression": "2*widgets_a + 3*widgets_b + 2*widgets_c <= 240"
        },
        {
            "name": "labor_hours",
            "expression": "4*widgets_a + 2*widgets_b + 3*widgets_c <= 200"
        },
        {
            "name": "raw_material",
            "expression": "widgets_a + widgets_b + widgets_c <= 150"
        }
    ],

    "options": {
        "time_limit_seconds": 30,
        "gap_tolerance": 0.01
    }
}
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _strip_nul(v: str) -> str:
    """Strip NUL bytes that PostgreSQL rejects in TEXT/VARCHAR columns."""
    return v.replace("\x00", "") if "\x00" in v else v


class VariableType(str, Enum):
    """Type of optimization variable."""

    CONTINUOUS = "continuous"
    INTEGER = "integer"
    BINARY = "binary"


class ObjectiveSense(str, Enum):
    """Optimization direction."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class SolverStatus(str, Enum):
    """Status of the solver after optimization."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"  # Solution found but not proven optimal
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    TIME_LIMIT = "time_limit"
    ERROR = "error"


class Variable(BaseModel):
    """Definition of a decision variable."""

    name: str = Field(..., description="Variable name (alphanumeric + underscore)")
    type: VariableType = Field(default=VariableType.CONTINUOUS, description="Variable type")
    lower_bound: float | None = Field(default=None, description="Lower bound (None = -inf)")
    upper_bound: float | None = Field(default=None, description="Upper bound (None = +inf)")
    # Optional index structure so a flat mangled name ("assign_v3_o107") can be
    # presented — and grouped — as the indexed family it came from
    # (assign[v3, o107]). Set AUTHORITATIVELY by the JModel compiler when it
    # grounds an indexed family; best-effort parsed for flat/imported models;
    # left None for genuine scalars (they render flat). Solver-agnostic.
    family: str | None = Field(
        default=None, description="Indexed family this variable belongs to, if any"
    )
    index_tuple: list[str] | None = Field(
        default=None,
        description="Per-index-set members of this variable, e.g. ['v3', 'o107'].",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure variable name is valid identifier."""
        if not v.replace("_", "").isalnum():
            raise ValueError(f"Variable name must be alphanumeric: {v}")
        if v[0].isdigit():
            raise ValueError(f"Variable name cannot start with digit: {v}")
        return v


class Constraint(BaseModel):
    """Definition of a constraint."""

    name: str | None = Field(
        default=None, max_length=256, description="Constraint name for debugging"
    )
    expression: str = Field(..., description="Constraint expression (e.g., 'x + 2*y <= 10')")
    # Same contract as Variable.family: set AUTHORITATIVELY by the JModel compiler
    # when it grounds an indexed constraint family ("cap_s1" → "cap"); best-effort
    # parsed for flat/imported problems; None for genuine scalar rows.
    family: str | None = Field(
        default=None, description="Indexed constraint family this row belongs to, if any"
    )

    @field_validator("name", "expression", mode="before")
    @classmethod
    def strip_nul_bytes(cls, v: str | None) -> str | None:
        return _strip_nul(v) if isinstance(v, str) else v

    @field_validator("expression")
    @classmethod
    def validate_expression(cls, v: str) -> str:
        """Basic validation of constraint expression.

        Normalizes single ``=`` to ``==`` for convenience (common in
        math notation and YAML templates).
        """
        # Must contain a comparison operator
        if not any(op in v for op in ["<=", ">=", "==", "<", ">"]):
            # Check for single = (not part of <= or >=) and normalize
            import re

            if re.search(r"(?<![<>!])=(?!=)", v):
                v = re.sub(r"(?<![<>!])=(?!=)", "==", v)
            else:
                raise ValueError(f"Constraint must contain comparison operator: {v}")
        return v


class Objective(BaseModel):
    """Definition of the objective function."""

    sense: ObjectiveSense = Field(..., description="Minimize or maximize")
    expression: str = Field(..., description="Objective expression (e.g., '3*x + 2*y')")

    @field_validator("expression", mode="before")
    @classmethod
    def strip_nul_bytes(cls, v: str) -> str:
        return _strip_nul(v) if isinstance(v, str) else v


class SolverOptions(BaseModel):
    """Solver configuration options."""

    # No upper bound on either: this is self-hosted software and the operator's
    # hardware decides. A public instance caps solve time per organization through
    # the `max_solve_time_seconds` platform setting, which clamps this value.
    time_limit_seconds: float = Field(
        default=300.0, ge=1, description="Max solve time in seconds (no ceiling — see plan caps)"
    )
    gap_tolerance: float = Field(default=0.0001, ge=0, le=1, description="MIP gap tolerance")
    threads: int = Field(
        default=0, ge=0, description="Number of solver threads (0=auto, no ceiling)"
    )
    verbose: bool = Field(default=False, description="Enable solver output")


class WarmStartConfig(BaseModel):
    """Configuration for warm-starting a solve from a previous execution."""

    execution_id: str = Field(
        ..., description="ID of a previous completed execution to use as warm start"
    )


class ObjectiveSpec(BaseModel):
    """Specification of a single objective in a multi-objective problem."""

    expression: str = Field(..., description="Objective expression (e.g., '3*x + 2*y')")
    sense: ObjectiveSense = Field(..., description="Minimize or maximize this objective")
    weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Weight for weighted-scalarization mode (0.0 to 1.0)",
    )
    label: str | None = Field(default=None, description="Human-readable label for this objective")


class MultiObjectiveConfig(BaseModel):
    """Configuration for multi-objective optimization."""

    mode: Literal["epsilon", "weighted"] = Field(
        ..., description="Solving mode: epsilon-constraint or weighted scalarization"
    )
    objectives: list[ObjectiveSpec] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Exactly two objectives to optimize",
    )
    n_points: int = Field(
        default=10,
        ge=2,
        le=50,
        description="Number of Pareto points to compute",
    )


class ConstraintSensitivity(BaseModel):
    """Sensitivity information for a single constraint."""

    name: str = Field(..., description="Constraint name")
    shadow_price: float | None = Field(
        default=None, description="Dual value / shadow price of the constraint"
    )
    is_binding: bool | None = Field(
        default=None, description="Whether the constraint is active at optimality"
    )
    is_approximate: bool = Field(
        default=False, description="True if value is from LP relaxation approximation"
    )


class VariableSensitivity(BaseModel):
    """Sensitivity information for a single decision variable."""

    name: str = Field(..., description="Variable name")
    reduced_cost: float | None = Field(
        default=None,
        description=(
            "Reduced cost: marginal change in the objective per unit relaxation of the "
            "variable's binding bound (meaningful when the variable sits at a bound)"
        ),
    )
    is_at_bound: bool | None = Field(
        default=None,
        description="Whether the variable rests at one of its bounds at optimality",
    )
    is_approximate: bool = Field(
        default=False, description="True if value is from LP relaxation approximation"
    )


class ObjectiveCoeffRange(BaseModel):
    """Range over which an objective coefficient keeps the optimal basis unchanged."""

    variable: str = Field(..., description="Variable whose objective coefficient this range covers")
    lower: float | None = Field(default=None, description="Lower end of the coefficient range")
    upper: float | None = Field(default=None, description="Upper end of the coefficient range")


class RhsRange(BaseModel):
    """Range over which a constraint right-hand side keeps the optimal basis unchanged."""

    constraint: str = Field(..., description="Constraint whose RHS range this covers")
    lower: float | None = Field(default=None, description="Lower end of the RHS range")
    upper: float | None = Field(default=None, description="Upper end of the RHS range")


class SensitivityResult(BaseModel):
    """Sensitivity analysis results for all constraints."""

    constraints: list[ConstraintSensitivity] = Field(
        default=[], description="Sensitivity information per constraint"
    )
    variables: list[VariableSensitivity] = Field(
        default=[],
        description="Per-variable reduced costs (from the LP / LP relaxation)",
    )
    objective_ranges: list[ObjectiveCoeffRange] = Field(
        default=[],
        description="Objective-coefficient ranges, when the solver exposes ranging",
    )
    rhs_ranges: list[RhsRange] = Field(
        default=[],
        description="Constraint right-hand-side ranges, when the solver exposes ranging",
    )
    is_approximate: bool = Field(
        default=False,
        description="True if results are based on LP relaxation (MIP problem)",
    )
    note: str | None = Field(
        default=None, description="Additional context about the sensitivity analysis"
    )


class ConstraintUtilization(BaseModel):
    """Exact, solution-based status of one constraint at the optimum x* (A3).

    Computed from x* + the problem — NOT from the LP relaxation — so it is exact
    for the integer solution and solver-agnostic. ``activity`` is a_i·x* (the LHS
    with variables moved left, constants right); ``slack`` is the signed room
    (≈0 ⇒ binding); ``utilization`` is activity/rhs for ≤-constraints.
    """

    name: str
    activity: float
    rhs: float
    operator: str
    slack: float
    is_binding: bool
    utilization: float | None = None
    family: str | None = None


class ConstraintFamilyStats(BaseModel):
    """Aggregated, exact KPIs for one constraint FAMILY at x* (Sensitivity L1).

    A grounded model repeats each declared constraint over its index sets
    ("cap_s1", "cap_s2", …); per-row tables drown the structure. These stats
    aggregate the rows of one family — computed over ALL analysed rows, before
    the per-row cap — so "3/12 binding, min slack 0.0" reads at model scale.
    ``utilization_*`` cover only rows where utilization is defined (≤ with
    nonzero RHS); None when no row qualifies.
    """

    family: str
    total: int
    binding_count: int
    slack_min: float
    slack_mean: float
    slack_max: float
    utilization_mean: float | None = None
    utilization_max: float | None = None


class ObjectiveTermContribution(BaseModel):
    """Exact contribution c_j·x*_j of one objective term at the solution (A3)."""

    label: str
    contribution: float


class ObjectiveFamilyContribution(BaseModel):
    """Total exact objective contribution of one variable FAMILY (Sensitivity L1).

    Sums c_j·x*_j over every objective term whose variables all belong to the
    family — including terms too small to appear in the per-term list — so the
    family totals are complete, not a sum of the displayed rows.
    """

    family: str
    contribution: float
    terms: int


class ExactAnalysis(BaseModel):
    """Exact, solution-based analysis — binding constraints, slack/utilization,
    objective contributions — all from x* + problem data (A3). Computed ON DEMAND
    (it re-parses every constraint), never on the solve path. Solver-agnostic:
    unlike LP-relaxation shadow prices, these are exact for the MILP solution.
    """

    objective_value: float | None = None
    total_constraints: int = 0
    binding_count: int = 0
    constraints: list[ConstraintUtilization] = []
    contributions: list[ObjectiveTermContribution] = []
    # Family-level KPIs (Sensitivity L1) — aggregated over ALL analysed rows/terms,
    # not the capped display lists. Empty when no family structure was recovered.
    families: list[ConstraintFamilyStats] = []
    contribution_families: list[ObjectiveFamilyContribution] = []
    truncated_constraints: bool = False
    truncated_contributions: bool = False
    truncated_families: bool = False
    computed: bool = True
    note: str | None = None


class ScenarioStatus(str, Enum):
    """Outcome of one what-if re-solve (Sensitivity L2)."""

    COMPUTED = "computed"  # solved to optimality — the delta is exact
    TIME_LIMIT = "time_limit"  # stopped early with an incumbent — delta is a BOUND
    INFEASIBLE = "infeasible"  # the scenario has no solution (itself a finding)
    SKIPPED_BUDGET = "skipped_budget"  # never run: re-solve or time budget exhausted
    ERROR = "error"  # the scenario could not be built or the solver failed


class RhsScenario(BaseModel):
    """One RHS-ranging re-solve: move a binding constraint's RHS by δ and re-solve.

    The honest MIP answer to "what would one more unit buy me?" — LP shadow
    prices are duals of an easier relaxation and go near-uniform under
    degeneracy, so the only exact answer is to solve the perturbed model.
    ``objective_delta`` is (scenario − base) as-is (sign carries direction);
    ``objective_delta_per_unit`` normalises it by δ so rows with different δ
    stay comparable in one tornado chart. Only ``COMPUTED`` rows are exact:
    ``TIME_LIMIT`` rows carry an incumbent, i.e. a bound on the true delta.
    """

    constraint: str
    family: str | None = None
    operator: str
    # "relax" widens the feasible set (≤: +δ, ≥: −δ); "tighten" narrows it.
    # An equality has no slack to give, so neither direction truly relaxes it —
    # ``is_equality`` tells the UI to read the pair as ↑/↓ RHS instead.
    direction: str
    is_equality: bool = False
    rhs: float
    rhs_new: float
    delta: float
    status: ScenarioStatus
    objective_value: float | None = None
    objective_delta: float | None = None
    objective_delta_per_unit: float | None = None
    # True when the move improves the objective in the problem's own sense.
    improves: bool | None = None
    solve_time_seconds: float | None = None


class DecisionScenario(BaseModel):
    """One regret re-solve: force a binary decision to its opposite value.

    Answers "what does it cost to overrule the model here?" — the user wants to
    open the plant the solver closed. ``regret`` is normalised to the problem's
    sense so it is always "how much worse this makes the objective" (≥ 0 when
    the base solution was optimal); an INFEASIBLE scenario means the overrule is
    not merely expensive but impossible.
    """

    variable: str
    family: str | None = None
    original_value: float
    forced_value: float
    status: ScenarioStatus
    objective_value: float | None = None
    regret: float | None = None
    solve_time_seconds: float | None = None


class ScenarioAnalysis(BaseModel):
    """What-if analysis by real re-solves (Sensitivity L2).

    Runs ON DEMAND off the request path (Celery): each row is a fresh solve of a
    perturbed model, bounded by a per-solve time limit AND a total budget. When
    the budget runs out the remaining rows come back ``SKIPPED_BUDGET`` and
    ``partial`` is true — a truncated answer is reported as truncated, never
    padded with guesses.
    """

    computed: bool = True
    note: str | None = None
    sense: str | None = None
    base_objective: float | None = None
    rhs_scenarios: list[RhsScenario] = []
    decision_scenarios: list[DecisionScenario] = []
    resolves_used: int = 0
    resolves_planned: int = 0
    seconds_used: float = 0.0
    budget_seconds: float = 0.0
    per_solve_limit_seconds: float = 0.0
    partial: bool = False


class ScenarioAnalysisJob(BaseModel):
    """State of one execution's what-if batch (Sensitivity L2).

    The batch runs for minutes on a worker, so the API returns the JOB, not just
    the answer: ``absent`` (never requested), ``running``, ``completed`` (with
    ``analysis``) or ``failed`` (with ``error``). Clients poll this until it
    leaves ``running``.
    """

    status: str = Field(description="absent | running | completed | failed")
    analysis: ScenarioAnalysis | None = None
    error: str | None = None
    requested_at: str | None = None
    completed_at: str | None = None
    # Plain-language reading of the measured scenarios, produced on demand by the
    # assistant and cached alongside them (so a reload never re-bills a call).
    explanation: str | None = None
    explained_at: str | None = None


class ScenarioExplanationResponse(BaseModel):
    """The plain-language reading of a what-if analysis (Sensitivity L2)."""

    explanation: str
    # True when served from the cache — no model call, no spend.
    cached: bool = False


class InfeasibilityAnalysis(BaseModel):
    """Why an INFEASIBLE model has no solution — a minimal conflicting set.

    Computed solver-agnostically by deletion filtering (see
    ``app.domains.solver.services.infeasibility.compute_iis``). The IIS is a
    minimal subset of constraints (and/or variable bounds) that are mutually
    unsatisfiable: drop any one of them and the model becomes feasible. When the
    model is too large (constraint cap) or the time budget is exceeded, exact IIS
    is skipped (``method="llm_only"``) and the LLM reasons heuristically over the
    formulation instead. ``explanation`` is filled later by the LLM endpoint.
    """

    iis_constraints: list[str] = Field(
        default=[],
        description="Names of the constraints in the minimal infeasible subset",
    )
    iis_variable_bounds: list[str] = Field(
        default=[],
        description="Variable-bound identifiers (e.g. 'x>=lb') that participate in the conflict",
    )
    conflict_type: Literal["constraint", "bound", "mixed", "unknown"] = Field(
        default="unknown",
        description="Whether the conflict is among constraints, bounds, both, or undetermined",
    )
    method: Literal["iis", "llm_only"] = Field(
        default="iis",
        description="'iis' = exact deletion filtering; 'llm_only' = heuristic LLM fallback",
    )
    note: str | None = Field(
        default=None,
        description="Context about how the analysis was produced or why it was skipped",
    )
    explanation: str | None = Field(
        default=None,
        description="Plain-language explanation produced by the LLM (filled on demand)",
    )


class ParetoPoint(BaseModel):
    """A single point on the Pareto front."""

    f1: float = Field(..., description="Value of objective 1")
    f2: float = Field(..., description="Value of objective 2")
    solution: dict[str, float] = Field(..., description="Variable values at this Pareto point")
    objective_values: dict[str, float] = Field(
        ..., description="Objective function values keyed by label"
    )


class MultiObjectiveResult(BaseModel):
    """Result of a multi-objective optimization solve."""

    pareto_points: list[ParetoPoint] = Field(..., description="Points on the Pareto front")
    mode: str = Field(..., description="Solving mode used (epsilon or weighted)")
    n_solved: int = Field(..., description="Number of Pareto points found")
    labels: list[str] = Field(..., description="Labels for each objective")


class OptimizationProblem(BaseModel):
    """
    Complete optimization problem definition.

    This is the main input schema for the /solve endpoint.
    """

    name: str | None = Field(default=None, max_length=256, description="Problem name for logging")
    description: str | None = Field(
        default=None, max_length=2000, description="Problem description"
    )

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_nul_bytes(cls, v: str | None) -> str | None:
        return _strip_nul(v) if isinstance(v, str) else v

    variables: list[Variable] = Field(..., min_length=1, description="Decision variables")
    objective: Objective = Field(..., description="Objective function")
    constraints: list[Constraint] = Field(default=[], description="Constraints")

    options: SolverOptions = Field(default_factory=SolverOptions, description="Solver options")

    # Advanced features
    warm_start: WarmStartConfig | None = Field(
        default=None, description="Warm start from a previous execution"
    )
    heuristic_warm_start: dict[str, float] | None = Field(
        default=None,
        description="Heuristic warm start solution built by the generator. "
        "Used automatically when no external warm_start is provided.",
        exclude=True,  # not serialized to API responses
    )

    # Optional metadata
    metadata: dict[str, Any] | None = Field(default=None, description="Custom metadata")

    # Solver routing hint. Optional; defaults to "scip" at the API layer.
    # Not solver-specific — just a routing instruction for the registry.
    solver_name: str | None = Field(
        default=None,
        max_length=32,
        description="Solver name override (e.g. 'highs', 'scip'). Defaults to platform default.",
    )

    @field_validator("variables")
    @classmethod
    def validate_unique_names(cls, v: list[Variable]) -> list[Variable]:
        """Ensure variable names are unique."""
        names = [var.name for var in v]
        if len(names) != len(set(names)):
            raise ValueError("Variable names must be unique")
        return v


class VariableSolution(BaseModel):
    """Solution value for a single variable."""

    name: str
    value: float
    type: VariableType
    # Recovered index structure (see ``Variable.family`` / ``index_tuple``),
    # copied through from the problem definition so the solution can be grouped
    # by family server-side and every consumer (UI, MCP, explain_solution) sees
    # ``assign[v3, o107]`` instead of a flat ``assign_v3_o107``. None → flat.
    family: str | None = None
    index_tuple: list[str] | None = None


class ProgressPoint(BaseModel):
    """One snapshot of the solver's progress, captured by the SCIP event handler."""

    iteration: int
    node: int | None = None
    objective: float
    primal_bound: float
    dual_bound: float | None = None
    gap: float | None = None
    elapsed_seconds: float


class OptimizationResult(BaseModel):
    """
    Result of solving an optimization problem.

    This is the response schema for the /solve endpoint.
    """

    status: SolverStatus = Field(..., description="Solver status")

    # Execution tracking
    execution_id: str | None = Field(default=None, description="ID of the persisted execution")

    # Solution (if found)
    objective_value: float | None = Field(default=None, description="Optimal objective value")
    variables: list[VariableSolution] | None = Field(default=None, description="Variable values")

    # As a simple dict for easy access
    solution: dict[str, float] | None = Field(default=None, description="Variable name -> value")

    # Set only when the caller asked for a compact solution (solution_filter=nonzero):
    # how many near-zero variables were omitted from `variables`/`solution`. The
    # persisted execution always keeps the full solution.
    variables_omitted: int | None = Field(
        default=None,
        description="Count of near-zero variables omitted by solution_filter=nonzero.",
    )

    # Performance metrics
    solve_time_seconds: float = Field(..., description="Time to solve")
    gap: float | None = Field(default=None, description="MIP gap (if applicable)")
    iterations: int | None = Field(default=None, description="Solver iterations")
    nodes: int | None = Field(default=None, description="Branch-and-bound nodes")

    # Error info
    error_message: str | None = Field(default=None, description="Error details if failed")

    # Auto-routing transparency (D-08). ``solver_used`` is the effective
    # solver that ran after ``solver_name="auto"`` resolves; ``auto_route_reason``
    # is an ``AUTO_REASON_*`` constant from ``auto_router`` when auto-routing
    # fired, else ``None`` for explicit solver requests. Non-breaking additions.
    solver_used: str | None = Field(
        default=None,
        description="Solver name that actually executed (after auto-routing).",
    )
    auto_route_reason: str | None = Field(
        default=None,
        description=(
            "Machine-readable auto-routing reason code. "
            "Populated only when solver_name was 'auto'. "
            "Values: lp_routed_to_highs | quadratic_routed_to_hexaly "
            "| hexaly_unavailable_fallback | milp_routed_to_scip."
        ),
    )
    # D-11: non-empty when a quadratic problem fell back from Hexaly to SCIP
    # because the worker was unavailable. UI should surface so users
    # understand quality may differ.
    warning: str | None = Field(
        default=None,
        description=(
            "Human-readable warning when the effective solver is a fallback. "
            "Present only on hexaly_unavailable_fallback routes."
        ),
    )

    # Advanced features
    sensitivity: SensitivityResult | None = Field(
        default=None, description="Sensitivity analysis results (shadow prices)"
    )
    infeasibility_analysis: InfeasibilityAnalysis | None = Field(
        default=None,
        description=(
            "Minimal conflicting set (IIS) explaining why an INFEASIBLE model has "
            "no solution. Populated on demand for infeasible solves."
        ),
    )
    warm_start_used: bool = Field(
        default=False, description="True if warm start solution was injected"
    )
    progress_history: list[ProgressPoint] | None = Field(
        default=None,
        description=(
            "Convergence history captured by the solver event handler. "
            "Used to render the convergence chart in the execution detail view."
        ),
    )

    def to_result_data(self) -> dict[str, Any]:
        """Serialize to the dict shape stored in ModelExecution.result_data."""
        return {
            "model": self.solution,
            "objective_value": self.objective_value,
            "solver_status": self.status.value,
            "solve_time_seconds": self.solve_time_seconds,
            "gap": self.gap,
            # Persisted so the post-solve summary can be honest about HOW the
            # model solved — root node vs. N branch-and-bound nodes vs. time
            # limit — instead of a flat, useless "live" convergence chart (A2).
            "nodes": self.nodes,
            "iterations": self.iterations,
            "variables": [v.model_dump() for v in self.variables] if self.variables else [],
            "sensitivity": self.sensitivity.model_dump() if self.sensitivity else None,
            "infeasibility_analysis": (
                self.infeasibility_analysis.model_dump() if self.infeasibility_analysis else None
            ),
            "progress_history": (
                [p.model_dump() for p in self.progress_history] if self.progress_history else None
            ),
        }
