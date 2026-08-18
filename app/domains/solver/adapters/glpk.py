"""GLPK adapter — the ``glpsol`` binary driven as a separate process.

**GLPK is GPLv3 and JAOT is Apache-2.0.** Linking GLPK into this process would
put JAOT's own source under the GPL. So this adapter never imports a GLPK
binding: it writes a file, runs the stock ``glpsol`` program, and reads its
output files. Do not replace this with ``swiglpk``, ``pulp``'s GLPK backend, or
any other binding — they all link the library.

``glpsol`` is asked for two output files at once and both are needed:

- ``-w`` writes the machine-readable solution, which identifies columns **by
  index only**.
- ``-o`` writes the printable report, which is the only place the column names
  appear next to those indices.

The names cannot be recovered from the input file instead: GLPK numbers columns
in order of first appearance while reading, which is not the order JAOT declared
them in.
"""

from __future__ import annotations

import logging
import math
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

GLPK_BINARY = "glpsol"
GLPK_LABEL = "GLPK"

#: A record in the printable report: index, then the name. Anchored on an
#: identifier so the continuation line of a wrapped long name — which starts
#: with the activity number — cannot be mistaken for a record of its own.
_NAMED_RECORD_RE = re.compile(r"^\s*(?P<index>\d+)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")

#: Header above the column block of the printable report.
_COLUMN_SECTION_MARKER = "Column name"

#: One progress line of the search log. Both shapes appear:
#:   "*     2: obj =   1.2e+01 inf =   0.0e+00 (0)"          — simplex
#:   "+ 23360: mip = 3.06e+05 <= 3.06e+05 < 0.1% (11518; 7765)" — branch and bound
_PROGRESS_RE = re.compile(r"^[+*]?\s*(?P<iterations>\d+):\s+(?P<body>.+)$")
_BOUND_RE = re.compile(r"(?:mip\s*=|>>>>>)\s+\S+(?:\s+\S+\s+\S+)?\s*(?:<=|>=)\s*(?P<bound>\S+)")
_TREE_RE = re.compile(r"\((?P<active>\d+);\s*(?P<fathomed>\d+)\)")

#: What glpsol prints when it stops, in the order of preference of the LAST one
#: seen. A MIP run prints "OPTIMAL LP SOLUTION FOUND" for its relaxation long
#: before it decides anything, so only the final verdict counts.
_VERDICTS: tuple[tuple[str, SolverStatus], ...] = (
    ("INTEGER OPTIMAL SOLUTION FOUND", SolverStatus.OPTIMAL),
    ("OPTIMAL LP SOLUTION FOUND", SolverStatus.OPTIMAL),
    ("OPTIMAL SOLUTION FOUND", SolverStatus.OPTIMAL),
    # The gap the caller asked for was reached. SCIP calls that optimal
    # (`gaplimit` maps to OPTIMAL) and the comparison table must agree with
    # itself across solvers.
    ("RELATIVE MIP GAP TOLERANCE REACHED", SolverStatus.OPTIMAL),
    ("TIME LIMIT EXCEEDED", SolverStatus.TIME_LIMIT),
    ("ITERATION LIMIT EXCEEDED", SolverStatus.TIME_LIMIT),
    ("PROBLEM HAS NO INTEGER FEASIBLE SOLUTION", SolverStatus.INFEASIBLE),
    ("PROBLEM HAS NO PRIMAL FEASIBLE SOLUTION", SolverStatus.INFEASIBLE),
    ("PROBLEM HAS NO FEASIBLE SOLUTION", SolverStatus.INFEASIBLE),
    ("INTEGER INFEASIBLE", SolverStatus.INFEASIBLE),
    # GLPK reports an unbounded model as "no dual feasible solution": the dual
    # of an unbounded primal is infeasible. Its own solution file only says
    # UNDEFINED, so this line is the only place the difference is stated.
    ("LP RELAXATION HAS NO DUAL FEASIBLE SOLUTION", SolverStatus.UNBOUNDED),
    ("PROBLEM HAS NO DUAL FEASIBLE SOLUTION", SolverStatus.UNBOUNDED),
    ("PROBLEM HAS UNBOUNDED SOLUTION", SolverStatus.UNBOUNDED),
)


#: What ``glpsol --version`` prints first: "GLPSOL--GLPK LP/MIP Solver 5.0".
_VERSION_RE = re.compile(r"GLPK LP/MIP Solver\s+(?P<version>[\w.]+)")


class GLPKAdapter(CachedVersion):
    """GLPK solver adapter implementing the SolverAdapter Protocol."""

    capabilities: SolverCapabilities = SolverCapabilities(
        name="glpk",
        supports_continuous=True,
        supports_integer=True,
        supports_binary=True,
        supports_quadratic=False,
        # GLPK does write row duals and reduced costs into its solution file for
        # a pure LP, and wiring them up is a small change. The flag stays False
        # until those numbers have been compared against SCIP's on the same
        # model: a capability that claims sensitivity it never checked is the
        # bug the August QA release found, and it is not worth repeating.
        supports_sensitivity=False,
        supports_warm_start=False,
        supports_multi_objective=False,
        supports_progress=False,
    )

    def __init__(self) -> None:
        self._binary: str | None = None
        self._looked_up = False

    def binary_path(self) -> str | None:
        """Where ``glpsol`` lives, looked up once per adapter instance."""
        if not self._looked_up:
            self._binary = find_binary(GLPK_BINARY)
            self._looked_up = True
            if self._binary is None:
                logger.info("GLPK binary %r not found on PATH — adapter unavailable", GLPK_BINARY)
        return self._binary

    def is_available(self) -> bool:
        return self.binary_path() is not None

    def _read_version(self) -> str | None:
        """GLPK's own version, e.g. "5.0".

        The mixin caches it, so the child process starts at most once per
        worker process.
        """
        binary = self.binary_path()
        return None if binary is None else read_version([binary, "--version"], _VERSION_RE)

    def solve(
        self,
        problem: OptimizationProblem,
        *,
        warm_start: dict[str, float] | None = None,
        on_progress: Callable[[ProgressPoint], None] | None = None,
    ) -> OptimizationResult:
        """Solve ``problem`` with GLPK.

        ``warm_start`` and ``on_progress`` are accepted for Protocol
        compatibility and ignored — both capability flags are False.
        """
        if warm_start is not None:
            logger.warning("GLPK adapter does not support warm start — argument ignored.")

        start_time = time.time()
        binary = self.binary_path()
        if binary is None:
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.time() - start_time,
                error_message=f"GLPK is not installed on this server ({GLPK_BINARY} not on PATH).",
            )

        try:
            with workspace("jaot-glpk-") as tmp:
                lp_path = tmp / "problem.lp"
                raw_path = tmp / "solution.raw"
                report_path = tmp / "solution.txt"
                write_problem_lp(problem, lp_path, solver_label=GLPK_LABEL)

                run = run_binary(
                    self._argv(binary, lp_path, raw_path, report_path, problem),
                    timeout=hard_timeout_seconds(problem.options.time_limit_seconds),
                )
                elapsed = time.time() - start_time
                if run.killed:
                    return OptimizationResult(
                        status=SolverStatus.TIME_LIMIT,
                        solve_time_seconds=elapsed,
                        error_message=(
                            "GLPK overran its time limit and was stopped. It reported nothing back."
                        ),
                    )
                if not raw_path.exists():
                    raise SolverError(
                        f"GLPK produced no solution file. Its last words:\n{tail(run.stdout)}"
                    )
                return self._build_result(
                    raw_path.read_text(),
                    report_path.read_text() if report_path.exists() else "",
                    run,
                    problem,
                    elapsed,
                )
        except Exception as exc:
            logger.error("GLPK solver error: %s", exc, exc_info=True)
            return OptimizationResult(
                status=SolverStatus.ERROR,
                solve_time_seconds=time.time() - start_time,
                # Same reason as the CBC adapter: a stringified exception
                # carries the argv and the temp paths with it.
                error_message=scrub_paths(f"GLPK could not finish this run: {exc}"),
            )

    # ── running ──────────────────────────────────────────────────────────────

    def _argv(
        self,
        binary: str,
        lp_path: Path,
        raw_path: Path,
        report_path: Path,
        problem: OptimizationProblem,
    ) -> list[str]:
        """The command line.

        ``--tmlim`` takes whole seconds, so a sub-second limit is rounded up to
        one: GLPK cannot be asked for less. There is no thread option — GLPK is
        single-threaded, which is a fact about the solver and shows up honestly
        in the seconds column of a comparison.
        """
        opts = problem.options
        time_limit = max(1, math.ceil(opts.time_limit_seconds))
        return [
            binary,
            "--lp",
            str(lp_path),
            "--tmlim",
            str(time_limit),
            "--mipgap",
            str(float(opts.gap_tolerance)),
            "-w",
            str(raw_path),
            "-o",
            str(report_path),
        ]

    # ── reading the answer ───────────────────────────────────────────────────

    def _build_result(
        self,
        raw_text: str,
        report_text: str,
        run: CliRun,
        problem: OptimizationProblem,
        elapsed: float,
    ) -> OptimizationResult:
        solution = _parse_raw_solution(raw_text)
        status = _verdict(run.stdout)
        if status is None:
            status = SolverStatus.OPTIMAL if solution.has_solution else SolverStatus.ERROR
        counters = _parse_counters(run.stdout, problem)

        result = OptimizationResult(
            status=status,
            solve_time_seconds=elapsed,
            iterations=counters.get("iterations"),
            nodes=counters.get("nodes"),
        )
        if status is SolverStatus.ERROR:
            result.error_message = f"GLPK did not finish. Its last words:\n{tail(run.stdout)}"
            return result

        dual_bound = counters.get("dual_bound")
        if not solution.has_solution:
            result.dual_bound = dual_bound
            return result

        result.objective_value = solution.objective_value
        # At optimality the bound is the answer. GLPK stops printing progress
        # lines once the tree is empty, so there may be no bound in the log.
        if dual_bound is None and status is SolverStatus.OPTIMAL:
            dual_bound = solution.objective_value
        result.dual_bound = dual_bound
        result.gap = relative_gap(result.objective_value, result.dual_bound)

        names = _parse_column_names(report_text)
        values = {
            name: solution.column_values[index]
            for index, name in names.items()
            if index in solution.column_values
        }
        absent = [var.name for var in problem.variables if var.name not in values]
        if absent:
            # The report names every column and the raw file gives every column a
            # value, so a variable with neither means the two files are about a
            # different model than the one asked for. A partly-filled solution
            # would be read as "those variables are zero".
            raise SolverError(
                f"GLPK returned no value for {len(absent)} of {len(problem.variables)} "
                f"variables (first missing: {absent[0]}). The solution cannot be trusted."
            )

        result.variables = [
            VariableSolution(
                name=var.name,
                value=values[var.name],
                type=var.type,
                family=var.family,
                index_tuple=var.index_tuple,
            )
            for var in problem.variables
        ]
        result.solution = {var.name: values[var.name] for var in problem.variables}
        return result


class _RawSolution:
    """What the ``-w`` file said: whether there is an answer, and the numbers."""

    __slots__ = ("column_values", "has_solution", "objective_value")

    def __init__(self) -> None:
        self.has_solution = False
        self.objective_value: float | None = None
        self.column_values: dict[int, float] = {}


def _parse_raw_solution(raw_text: str) -> _RawSolution:
    """Read glpsol's machine-readable solution file.

    Two shapes, decided by the ``s`` line:

    - ``s bas <rows> <cols> <primal> <dual> <objective>`` for an LP, with
      ``j <index> <status> <value> <reduced cost>`` per column.
    - ``s mip <rows> <cols> <status> <objective>`` for a MIP, with
      ``j <index> <value>`` per column.

    Status codes: ``o`` optimal, ``f`` feasible, ``n`` no solution, ``u``
    undefined for a MIP; ``f`` feasible, ``i`` infeasible, ``n`` none, ``u``
    undefined for the primal half of an LP. Only ``o`` and ``f`` mean numbers
    worth reading.
    """
    solution = _RawSolution()
    is_mip = False
    for line in raw_text.splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "s" and len(fields) >= 5:
            is_mip = fields[1] == "mip"
            # Field 4 is the MIP status for `s mip` and the PRIMAL status for
            # `s bas`; both live at the same offset and both use "f" for a
            # solution worth reading.
            solution.has_solution = fields[4] in ("o", "f")
            solution.objective_value = parse_float(fields[-1]) if solution.has_solution else None
        elif fields[0] == "j":
            # LP: j index status primal dual. MIP: j index primal.
            value_field = fields[2] if is_mip else (fields[3] if len(fields) >= 4 else None)
            value = parse_float(value_field) if value_field is not None else None
            index = parse_float(fields[1])
            if value is not None and index is not None:
                solution.column_values[int(index)] = value
    return solution


def _parse_column_names(report_text: str) -> dict[int, str]:
    """Column index to variable name, from the printable report.

    GLPK breaks the line after a name longer than twelve characters and puts the
    numbers underneath. The continuation line starts with the activity value, so
    requiring the second field to look like an identifier is what keeps a number
    from being read as a name. Indices must arrive in order, one after another,
    or the mapping is refused rather than guessed.
    """
    names: dict[int, str] = {}
    in_columns = False
    for line in report_text.splitlines():
        if _COLUMN_SECTION_MARKER in line:
            in_columns = True
            continue
        if not in_columns:
            continue
        match = _NAMED_RECORD_RE.match(line)
        if match is None:
            continue
        index = int(match.group("index"))
        if index != len(names) + 1:
            continue
        names[index] = match.group("name")
    return names


def _verdict(stdout: str) -> SolverStatus | None:
    """The status from the last verdict glpsol printed, or None if it printed none."""
    status: SolverStatus | None = None
    for line in stdout.splitlines():
        upper = line.upper()
        for marker, mapped in _VERDICTS:
            if marker in upper:
                status = mapped
                break
    return status


def _parse_counters(stdout: str, problem: OptimizationProblem) -> dict[str, float | int]:
    """How much work GLPK did, read from its progress log.

    GLPK reports none of this in its solution files, so the log is the only
    source. Best-effort throughout: a counter that could not be read must never
    fail a solve that produced an answer.

    ``nodes`` is the count of subproblems GLPK has finished with — the second
    number of the ``(active; fathomed)`` pair it prints. The first is how many
    are still waiting, which is a snapshot of the tree rather than work done.
    """
    counters: dict[str, float | int] = {}
    has_integrality = any(
        v.type in (VariableType.INTEGER, VariableType.BINARY) for v in problem.variables
    )

    for line in stdout.splitlines():
        match = _PROGRESS_RE.match(line)
        if match is None:
            continue
        counters["iterations"] = int(match.group("iterations"))
        body = match.group("body")

        bound_match = _BOUND_RE.search(body)
        if bound_match is not None:
            bound = parse_float(bound_match.group("bound"))
            if bound is not None:
                counters["dual_bound"] = bound
            else:
                # "+inf" or "tree is empty": GLPK has nothing to claim yet, and a
                # stale bound from an earlier line would be worse than none.
                counters.pop("dual_bound", None)

        if has_integrality:
            tree_match = _TREE_RE.search(body)
            if tree_match is not None:
                counters["nodes"] = int(tree_match.group("fathomed"))

    return counters
