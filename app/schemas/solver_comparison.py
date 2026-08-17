"""Request and response shapes for the solver comparer.

The response is built to be read as a table, one row per solver asked for —
including the solvers that could not run. A missing row would be read as a blank
cell, and a blank cell in a comparison is read as zero.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.optimization import OptimizationProblem

#: Ceiling on how many solvers one comparison may ask for. Not a fairness rule —
#: the runs are sequential, so the wait is the sum of the time limits and a
#: request naming twenty solvers would park the single comparison worker for
#: hours. Well above the number of solvers that exist.
MAX_SOLVERS_PER_COMPARISON = 8

#: Ceiling on how many datasets one matrix may cross. The number of runs is the
#: product, not the sum: 12 datasets by 8 solvers is 96 solves in a row on a
#: single-slot queue. The daily quota is the real limit, but this stops one
#: request from parking the comparison worker for a day before the quota can.
MAX_DATASETS_PER_BATCH = 12


class ComparisonSettings(BaseModel):
    """What the caller may choose. Applied identically to every solver.

    Thread count is deliberately absent. HiGHS sizes one task scheduler per
    worker process on its first solve, and a later request for a different count
    makes the solve fail silently, so the count cannot be a per-request choice —
    it is fixed at ``DEFAULT_COMPARISON_THREADS``. The value used is reported
    back in :class:`ComparisonTerms`.
    """

    time_limit_seconds: float = Field(
        default=60.0,
        ge=1,
        description="Seconds each solver is given. The same value for all of them.",
    )
    gap_tolerance: float = Field(
        default=0.0001, ge=0, le=1, description="MIP gap tolerance, the same for all solvers."
    )


class ComparisonTerms(BaseModel):
    """The terms every solver in the run actually received.

    Reported rather than requested: the instance can clamp the time limit, and
    the thread count is fixed by the platform. The table shows these, because
    what the solvers got is what the numbers mean.
    """

    time_limit_seconds: float
    gap_tolerance: float
    threads: int


class CreateComparisonRequest(BaseModel):
    """Ask for one problem to be run against several solvers.

    The problem arrives one of two ways and exactly one must be given:

    - ``problem`` — an optimization problem inline. This is also the path for an
      uploaded MPS/LP/CIP/JSON file: the client parses it first with
      ``POST /api/v2/import/preview`` and sends the parsed problem here. Nothing
      of that file is stored beyond the snapshot on the comparison, which is
      deleted with it.
    - ``project_id`` — a studio model, optionally pinned to ``version_id``. The
      server reads the model itself, so the client cannot substitute a different
      problem for a project it names.
    """

    solver_names: list[str] = Field(
        min_length=1,
        max_length=MAX_SOLVERS_PER_COMPARISON,
        description="Solvers to compare, in the order they should run.",
    )
    settings: ComparisonSettings = Field(default_factory=ComparisonSettings)

    problem: OptimizationProblem | None = Field(
        default=None, description="The problem to compare, inline."
    )
    project_id: str | None = Field(default=None, description="Studio model to compare.")
    version_id: str | None = Field(
        default=None, description="Committed version of project_id. Draft when omitted."
    )
    uploaded_filename: str | None = Field(
        default=None,
        max_length=255,
        description="Name of the file the problem came from, for the header only.",
    )

    @model_validator(mode="after")
    def _exactly_one_source(self) -> CreateComparisonRequest:
        if (self.problem is None) == (self.project_id is None):
            raise ValueError("Provide exactly one of 'problem' or 'project_id'.")
        if self.version_id is not None and self.project_id is None:
            raise ValueError("'version_id' requires 'project_id'.")
        return self


class ComparisonSolverResult(BaseModel):
    """One row of the table: what this solver did with the shared problem."""

    solver_name: str
    execution_id: str | None = None
    #: Which version of this solver produced the row, e.g. "2.10.12". None when
    #: the solver would not say, or when the row predates this being recorded.
    #: Seconds only mean something against a named version once the images that
    #: produced them have been rebuilt.
    solver_version: str | None = None

    #: Execution lifecycle: pending | running | completed | failed | cancelled.
    status: str
    #: The solver's own verdict: optimal | feasible | infeasible | unbounded |
    #: time_limit | error | unsupported. None until it has one.
    solver_status: str | None = None
    #: Set when solver_status is "unsupported": a machine-readable code
    #: (integer_variables | quadratic_terms | not_registered | not_available).
    #: The UI turns it into a sentence; the sentence is not stored.
    unsupported_reason: str | None = None

    objective_value: float | None = None
    #: The best objective value the solver proved could still exist. With the
    #: objective it says how much room was left — which is the whole content of
    #: a run stopped by its time limit.
    dual_bound: float | None = None
    gap: float | None = None
    iterations: int | None = None
    nodes: int | None = None

    #: Wall time around the whole call, building the solver's model included.
    #: This is the number the table shows, because it is the wait.
    wall_time_ms: int | None = None
    #: The adapter's own measure of the search alone. Kept because slow-to-build
    #: and slow-to-search are different problems.
    solver_time_seconds: float | None = None

    error_message: str | None = None


class ComparisonAgreement(BaseModel):
    """Whether the solvers that finished actually agree.

    Two solvers can both be right and disagree on the variables: a problem with
    several optimal solutions has no single answer to return. Saying so is the
    point of this block — without it a reader sees two different solutions and
    concludes one solver is broken.
    """

    #: Solvers whose verdict was optimal or feasible. The rest are not compared.
    compared_solvers: list[str]
    #: True when every compared objective matches within tolerance.
    objectives_agree: bool | None = None
    #: True when every compared solution assigns the same value to every variable.
    solutions_identical: bool | None = None
    #: Largest absolute objective difference among the compared solvers.
    max_objective_delta: float | None = None
    #: Set when objectives agree but the solutions do not: alternative optima.
    alternative_optima: bool = False


class ComparisonDetail(BaseModel):
    """A comparison and its table."""

    id: str
    status: str
    problem_name: str | None = None
    #: Set when this comparison is one row of a matrix, so a page opened on the
    #: row can offer the way back to the matrix it came from.
    batch_id: str | None = None

    source_kind: str | None = None
    source_id: str | None = None
    uploaded_filename: str | None = None
    model_project_id: str | None = None
    model_project_version_id: str | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None

    settings: ComparisonTerms
    #: What the compared problem is: LP, MILP, IP, BIP, QP, MIQP, QCP or MIQCP,
    #: with its size. Twelve seconds means one thing on an LP and another on a
    #: mixed-integer model with twenty thousand rows.
    problem_class: str | None = None
    variable_count: int | None = None
    constraint_count: int | None = None
    #: Which machine produced these seconds. Times are comparable within one
    #: comparison and nowhere else, so the machine is shown next to them.
    machine_note: str | None = None

    results: list[ComparisonSolverResult]
    agreement: ComparisonAgreement | None = None

    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ComparisonSummary(BaseModel):
    """One entry of the comparison history list."""

    id: str
    status: str
    problem_name: str | None = None
    solver_names: list[str]
    created_at: datetime
    completed_at: datetime | None = None


class ComparisonListResponse(BaseModel):
    """This organization's comparisons, newest first."""

    comparisons: list[ComparisonSummary]
    total: int


# ──────────────────────────────────────────────────────────────
# The matrix: several datasets crossed with several solvers
# ──────────────────────────────────────────────────────────────


class CreateComparisonBatchRequest(BaseModel):
    """Cross several of a project's datasets with several solvers.

    The model comes from the project's JModel source and is compiled once per
    dataset, on the server. There is no ``problem`` field on purpose: a matrix
    only means something when every row is the same model fed different data,
    and that is exactly what a JModel source plus N datasets is.
    """

    project_id: str = Field(description="Studio model whose JModel source is compiled.")
    version_id: str | None = Field(
        default=None, description="Committed version of project_id. Draft when omitted."
    )
    dataset_ids: list[str] = Field(
        min_length=1,
        max_length=MAX_DATASETS_PER_BATCH,
        description="Datasets to compile the source against, one row each.",
    )
    solver_names: list[str] = Field(
        min_length=1,
        max_length=MAX_SOLVERS_PER_COMPARISON,
        description="Solvers to compare, one column each.",
    )
    settings: ComparisonSettings = Field(default_factory=ComparisonSettings)


class ComparisonMatrixRow(BaseModel):
    """One row of the matrix: one dataset, run against every solver.

    Carries its own ``comparison_id`` because the row IS a comparison — clicking
    a cell opens it, with the agreement block and everything else a single
    comparison shows.
    """

    comparison_id: str
    dataset_id: str | None = None
    dataset_name: str | None = None

    status: str
    #: The compiled size of THIS row. Two datasets of the same model routinely
    #: ground to very different sizes, which is often the answer to why one row
    #: took ten times longer than the one above it.
    problem_class: str | None = None
    variable_count: int | None = None
    constraint_count: int | None = None
    error_message: str | None = None

    results: list[ComparisonSolverResult]


class ComparisonBatchDetail(BaseModel):
    """A matrix: the datasets down the side, the solvers across the top."""

    batch_id: str
    #: Derived from the rows: pending until one starts, running while any row is
    #: still going, then completed / failed / cancelled.
    status: str
    project_id: str | None = None
    project_name: str | None = None
    model_project_version_id: str | None = None

    settings: ComparisonTerms
    #: The columns, in the order they run. The same for every row.
    solver_names: list[str]
    machine_note: str | None = None

    rows: list[ComparisonMatrixRow]

    created_at: datetime
    completed_at: datetime | None = None


class ComparisonBatchSummary(BaseModel):
    """One entry of the matrix history list."""

    batch_id: str
    status: str
    project_id: str | None = None
    project_name: str | None = None
    dataset_count: int
    solver_names: list[str]
    created_at: datetime
    completed_at: datetime | None = None


class ComparisonBatchListResponse(BaseModel):
    """This organization's matrices, newest first."""

    batches: list[ComparisonBatchSummary]
    total: int
