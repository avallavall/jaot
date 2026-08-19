"""CBC adapter — the COIN-OR ``cbc`` binary driven as a separate process.

CBC ships as a command-line program (EPL-2.0). JAOT writes the model to a CPLEX
LP file, runs ``cbc`` on it and reads back the solution file and the log. There
is no Python binding involved; see ``_cli_solver`` for why the exchange goes
through a file and why the format is LP and not MPS.

Two things about CBC's output cost real debugging time and are worth knowing
before touching the parsing below:

- **The exit code says nothing.** CBC returns 0 after refusing to read the file.
  A run only counts as successful when the solution file exists.
- **"Stopped on time (no integer solution - continuous used)" carries the LP
  relaxation, not an answer.** Its "objective value" is the bound. Returning
  those variable values as a solution would hand the user a fractional
  assignment presented as a plan.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path

from app.domains.solver.adapters._cli_solver import (
    CliRun,
    find_binary,
    hard_timeout_seconds,
    parse_float,
    read_version,
    relative_gap,
    run_binary,
    scrub_paths,
    tail,
    workspace,
    write_problem_lp,
)
from app.domains.solver.adapters.base import (
    CachedVersion,
    SolverCapabilities,
    SolverError,
)
from app.schemas.optimization import (
    OptimizationProblem,
    OptimizationResult,
    ProgressPoint,
    SolverStatus,
    VariableSolution,
    VariableType,
)

logger = logging.getLogger(__name__)

CBC_BINARY = "cbc"
CBC_LABEL = "CBC"

#: One line of CBC's solution file: an optional infeasibility marker, the index
#: within its block, the name, the value, and the reduced cost (or, for a row,
#: the dual). Only the name and the value are read.
_RECORD_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?P<index>\d+)\s+(?P<name>\S+)\s+(?P<value>\S+)\s+(?P<dual>\S+)\s*$"
)

#: "Enumerated nodes:  1234" and friends from the end-of-run summary.
#: The value part accepts a sign in the exponent as well as at the front:
#: "Lower bound: -1.5e-05" is a bound like any other, and a class that only
#: allowed a leading minus skipped the line and left the bound unknown.
_SUMMARY_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z ()]*?):\s+(?P<value>[-+]?[\d.eE+-]+)\s*$")

#: The one-line summary CBC prints instead of the block above when the model was
#: a pure LP: "Optimal objective 12 - 2 iterations time 0.002, Presolve 0.00".
_LP_ITERATIONS_RE = re.compile(r"-\s+(?P<iterations>\d+)\s+iterations")

#: CBC's banner: "Welcome to the CBC MILP Solver \n Version: 2.10.12 \n Build Date: ..."
_VERSION_RE = re.compile(r"Version:\s*(?P<version>[\w.]+)")


class CBCAdapter(CachedVersion):
    """CBC solver adapter implementing the SolverAdapter Protocol."""

    capabilities: SolverCapabilities = SolverCapabilities(
        name="cbc",
        supports_continuous=True,
        supports_integer=True,
        supports_binary=True,
        supports_quadratic=False,
        # CBC does print a dual per row and a reduced cost per column, but under
        # maximization it reformulates the problem and flips them back itself,
        # and that convention has not been checked against SCIP's. Shipping
        # unverified shadow prices is the exact bug the August QA release found
        # in SCIP; the flag stays False until the numbers are compared.
        supports_sensitivity=False,
        supports_warm_start=False,
        supports_multi_objective=False,
        supports_progress=False,
    )

    def __init__(self) -> None:
        self._binary: str | None = None
        self._looked_up = False

    def binary_path(self) -> str | None:
        """Where ``cbc`` lives, looked up once per adapter instance."""
        if not self._looked_up:
            self._binary = find_binary(CBC_BINARY)
            self._looked_up = True
            if self._binary is None:
                logger.info("CBC binary %r not found on PATH — adapter unavailable", CBC_BINARY)
        return self._binary

    def is_available(self) -> bool:
        return self.binary_path() is not None

    def _read_version(self) -> str | None:
        """CBC's own version, e.g. "2.10.12".

        ``cbc -exit`` prints the banner and quits without reading a model, which
        is the shortest way to make it say so. The mixin caches the answer, so
        the child process starts at most once per worker process.
        """
        binary = self.binary_path()
        return None if binary is None else read_version([binary, "-exit"], _VERSION_RE)

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
        on_progress: Callable[[ProgressPoint], None] | None = None,
    ) -> OptimizationResult:
        """Solve ``problem`` with CBC.

        ``warm_start`` and ``on_progress`` are accepted for Protocol
        compatibility and ignored — both capability flags are False.
        """
        if warm_start is not None:
            logger.warning("CBC adapter does not support warm start — argument ignored.")

        start_time = time.monotonic()
        binary = self.binary_path()
        if binary is None:
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.monotonic() - start_time,
                error_message=f"CBC is not installed on this server ({CBC_BINARY} not on PATH).",
            )

        try:
            with workspace("jaot-cbc-") as tmp:
                lp_path = tmp / "problem.lp"
                sol_path = tmp / "solution.txt"
                objective_offset = write_problem_lp(problem, lp_path, solver_label=CBC_LABEL)

                run = run_binary(
                    self._argv(binary, lp_path, sol_path, problem),
                    timeout=hard_timeout_seconds(problem.options.time_limit_seconds),
                )
                elapsed = time.monotonic() - start_time
                if run.killed:
                    return self._killed_result(elapsed)
                if not sol_path.exists():
                    raise SolverError(
                        f"CBC produced no solution file. Its last words:\n{tail(run.stdout)}"
                    )
                return self._build_result(
                    sol_path.read_text(), run, problem, elapsed, objective_offset
                )
        except Exception as exc:
            logger.error("CBC solver error: %s", exc, exc_info=True)
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.monotonic() - start_time,
                # `str(exc)` went straight to the comparison table. A
                # subprocess failure stringifies to its whole argv, and any
                # other exception to whatever paths it was holding, so the
                # server's filesystem was on the user's screen. The full
                # exception, traceback included, is on the line above.
                error_message=scrub_paths(f"CBC could not finish this run: {exc}"),
            )

    # ── running ──────────────────────────────────────────────────────────────

    def _argv(
        self,
        binary: str,
        lp_path: Path,
        sol_path: Path,
        problem: OptimizationProblem,
    ) -> list[str]:
        """The command line, in the order CBC wants it.

        CBC reads its arguments as a script: options first, then the ``solve``
        and ``solution`` commands. ``printingOptions all`` is what makes CBC
        list every column — its default printing drops a variable that is zero
        with a zero reduced cost, which would silently turn a 90-variable answer
        into a 40-variable one.

        ``-timeMode elapsed`` is what makes ``-seconds`` mean the wall clock a
        comparison measures. CBC's default is CPU seconds, and the two are not
        the same number: on a hard feasibility MIP given 10 seconds, CBC spent
        10.03 CPU seconds and 14.53 on the clock, then reported the 14.53 into
        a table whose whole claim is that every solver got the same 10. With
        ``elapsed`` the same run stops at 10.02. The hard timeout in
        ``run_binary`` stays as the backstop, because CBC checks its clock
        only between nodes either way.
        """
        opts = problem.options
        argv = [
            binary,
            str(lp_path),
            "-timeMode",
            "elapsed",
            "-seconds",
            str(float(opts.time_limit_seconds)),
        ]
        if opts.threads > 0:
            argv += ["-threads", str(opts.threads)]
        argv += ["-ratioGap", str(float(opts.gap_tolerance))]
        argv += ["printingOptions", "all", "solve", "solution", str(sol_path)]
        return argv

    def _killed_result(self, elapsed: float) -> OptimizationResult:
        return OptimizationResult(
            status=SolverStatus.TIME_LIMIT,
            solve_time_seconds=elapsed,
            error_message=("CBC overran its time limit and was stopped. It reported nothing back."),
        )

    # ── reading the answer ───────────────────────────────────────────────────

    def _build_result(
        self,
        solution_text: str,
        run: CliRun,
        problem: OptimizationProblem,
        elapsed: float,
        objective_offset: float = 0.0,
    ) -> OptimizationResult:
        lines = solution_text.splitlines()
        headline = lines[0].strip() if lines else ""
        status, has_solution = _map_status(headline)
        counters = _parse_counters(run.stdout, problem)

        result = OptimizationResult(
            status=status,
            solve_time_seconds=elapsed,
            iterations=counters.get("iterations"),
            nodes=counters.get("nodes"),
        )
        if status is SolverStatus.ERROR:
            result.error_message = f"CBC did not finish: {headline or 'no verdict reported'}"
            return result

        headline_objective = _headline_objective(headline)
        # CBC reads an LP objective carrying a constant and drops it without a
        # word, so the constant never goes into the file (see write_problem_lp)
        # and is added back here — to the answer and to the bound alike, before
        # the gap is computed off them.
        if objective_offset:
            if headline_objective is not None:
                headline_objective += objective_offset
            if counters.get("dual_bound") is not None:
                counters["dual_bound"] += objective_offset
        if not has_solution:
            if status is SolverStatus.TIME_LIMIT:
                # Here the headline number is the relaxation's value, which is
                # the bound CBC proved rather than an answer it found. On an
                # infeasible or unbounded model the same slot holds whatever
                # point CBC happened to be standing on, so nothing is reported.
                result.dual_bound = counters.get("dual_bound", headline_objective)
            return result

        result.objective_value = headline_objective
        dual_bound = counters.get("dual_bound")
        # At optimality the bound IS the answer, and CBC does not always print a
        # "Lower bound" line for a search that closed. Anywhere else, defaulting
        # the bound to the answer would report a gap of zero on a run that was
        # cut off by its time limit — the comparison would show it as proven
        # while it was still a long way from proving anything. Same guard the
        # GLPK adapter has, for the same reason.
        if dual_bound is None and status is SolverStatus.OPTIMAL:
            dual_bound = headline_objective
        result.dual_bound = dual_bound
        result.gap = relative_gap(result.objective_value, result.dual_bound)

        values = _parse_columns(lines[1:])
        missing = [v.name for v in problem.variables if v.name not in values]
        if missing:
            # Every declared variable becomes a column in the LP file, and
            # `printingOptions all` prints every column. A name that did not come
            # back means the file and the answer are about different models, and
            # a partly-filled solution would be read as "those variables are 0".
            raise SolverError(
                f"CBC returned no value for {len(missing)} of {len(problem.variables)} "
                f"variables (first missing: {missing[0]}). The solution cannot be trusted."
            )

        variable_solutions = [
            VariableSolution(
                name=var.name,
                value=values[var.name],
                type=var.type,
                family=var.family,
                index_tuple=var.index_tuple,
            )
            for var in problem.variables
        ]
        result.variables = variable_solutions
        result.solution = {var.name: values[var.name] for var in problem.variables}
        return result


def _map_status(headline: str) -> tuple[SolverStatus, bool]:
    """Read CBC's verdict line. Returns the status and whether values follow.

    The second half of the pair is the part that matters. CBC writes variable
    values under several headlines that are not answers: an infeasible model
    gets the last point it looked at, and a time limit with no integer solution
    gets the continuous relaxation.
    """
    if not headline:
        return SolverStatus.ERROR, False
    if "no integer solution" in headline:
        return SolverStatus.TIME_LIMIT, False
    if headline.startswith("Optimal"):
        return SolverStatus.OPTIMAL, True
    if headline.startswith("Infeasible") or headline.startswith("Integer infeasible"):
        return SolverStatus.INFEASIBLE, False
    if headline.startswith("Unbounded"):
        return SolverStatus.UNBOUNDED, False
    if headline.startswith("Stopped on gap"):
        # The gap the user asked for was reached. SCIP calls that optimal
        # (`gaplimit` maps to OPTIMAL) and the comparison table has to agree
        # with itself across solvers.
        return SolverStatus.OPTIMAL, True
    if headline.startswith("Stopped on"):
        return SolverStatus.TIME_LIMIT, True
    return SolverStatus.ERROR, False


def _headline_objective(headline: str) -> float | None:
    """The number after "objective value" on CBC's verdict line."""
    marker = "objective value"
    index = headline.find(marker)
    if index < 0:
        return None
    return parse_float(headline[index + len(marker) :].strip())


def _parse_columns(record_lines: list[str]) -> dict[str, float]:
    """Variable name to value, from the column block of the solution file.

    With ``printingOptions all`` CBC prints the rows first and then the columns,
    and restarts its index at 0 for each block. The split is found by watching
    the index rather than by counting rows: a name is not a safe discriminator
    because a constraint and a variable may share one.
    """
    blocks: list[dict[str, float]] = []
    previous_index: int | None = None
    for line in record_lines:
        match = _RECORD_RE.match(line)
        if match is None:
            continue
        index = int(match.group("index"))
        if previous_index is None or index <= previous_index:
            blocks.append({})
        previous_index = index
        value = parse_float(match.group("value"))
        if value is not None:
            blocks[-1][match.group("name")] = value
    return blocks[-1] if blocks else {}


def _parse_counters(stdout: str, problem: OptimizationProblem) -> dict[str, float | int]:
    """How much work CBC did, read from its end-of-run summary.

    Best-effort throughout: a counter CBC did not print must never fail a solve
    that produced an answer. Without these the comparison table is blank in the
    columns that do not depend on the machine, which is what the table is for.

    ``Lower bound`` / ``Upper bound`` appear only when CBC stopped early — which
    is also the only time they say anything the objective does not.
    """
    counters: dict[str, float | int] = {}
    has_integrality = any(
        v.type in (VariableType.INTEGER, VariableType.BINARY) for v in problem.variables
    )

    for raw_line in stdout.splitlines():
        match = _SUMMARY_RE.match(raw_line.strip())
        if match is None:
            if "iterations" in raw_line and "iterations" not in counters:
                lp_match = _LP_ITERATIONS_RE.search(raw_line)
                if lp_match is not None:
                    counters["iterations"] = int(lp_match.group("iterations"))
            continue
        label = match.group("label")
        value = parse_float(match.group("value"))
        if value is None:
            continue
        if label == "Total iterations":
            counters["iterations"] = int(value)
        elif label == "Enumerated nodes" and has_integrality:
            # A pure LP has no branch-and-bound tree, so "0 nodes" would read as
            # "explored none" when the truth is there were never any to explore.
            counters["nodes"] = int(value)
        elif label in ("Lower bound", "Upper bound"):
            counters["dual_bound"] = value

    return counters
