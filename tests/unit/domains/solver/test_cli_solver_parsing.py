"""Parsing tests for the CBC and GLPK adapters, against output they really wrote.

Every fixture in this file is a verbatim copy of what the binaries printed on
this project's own models — not a guess at their format. Both solvers write
plain text in shapes nobody documents, and a parser tested against invented
output proves only that the author is consistent with themselves.

No binary runs here. The tests that do run one are in
``test_cli_solver_adapters.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domains.solver.adapters import cbc as cbc_mod, glpk as glpk_mod
from app.domains.solver.adapters._cli_solver import (
    parse_float,
    relative_gap,
    scrub_paths,
    tail,
)
from app.domains.solver.adapters.base import SolverError
from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    SolverStatus,
    Variable,
    VariableType,
)

pytestmark = pytest.mark.unit


def _binary_problem(count: int) -> OptimizationProblem:
    return OptimizationProblem(
        name="bins",
        variables=[Variable(name=f"k{i}", type=VariableType.BINARY) for i in range(count)],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="k0 + k1"),
        constraints=[
            Constraint(name="c", expression=" + ".join(f"k{i}" for i in range(count)) + " <= 2")
        ],
    )


# ── CBC ──────────────────────────────────────────────────────────────────────

# Written by cbc 2.10.12 with `printingOptions all`: one row record, then the
# six column records, with the index restarting at 0 for the second block.
CBC_SOLUTION_WITH_ROWS = """Optimal - objective value 2.00000000
      0 c                      2                      -0
      0 k0                     1                       1
      1 k1                     1                       1
      2 k2                     0                       0
      3 k3                     0                       0
      4 k4                     0                       0
      5 k5                     0                       0
"""

# The `**` marks a row cbc could not satisfy. It has to survive the record regex
# or the block split lands in the wrong place.
CBC_SOLUTION_INFEASIBLE = """Infeasible - objective value 4.00000000
      0 lo                     4                       1
**       1 hi                     4                       0
      0 a                      4                       0
"""

CBC_SOLUTION_NO_INTEGER_SOLUTION = (
    "Stopped on time (no integer solution - continuous used) - objective value 12.00000000\n"
    "      0 assign_0                1                   0.224\n"
    "      0 x0                      1                       0\n"
)

CBC_STDOUT_STOPPED_ON_TIME = """Result - Stopped on time limit

No feasible solution found
Lower bound:                    12.000
Enumerated nodes:               24072
Total iterations:               351289
Time (CPU seconds):             8.14
Time (Wallclock seconds):       9.16

Total time (CPU seconds):       8.15   (Wallclock seconds):       9.17
"""

# What cbc prints for a pure LP: no summary block at all, and the iteration
# count buried in one line.
CBC_STDOUT_PURE_LP = """Presolve 3 (0) rows, 4 (-1) columns and 6 (-1) elements
Optimal - objective value 12
After Postsolve, objective 12, infeasibilities - dual 0 (0), primal 0 (0)
Optimal objective 12 - 2 iterations time 0.002, Presolve 0.00
Total time (CPU seconds):       0.00   (Wallclock seconds):       0.00
"""


def test_cbc_reads_the_column_block_and_not_the_row_block() -> None:
    """The values come from the columns, even though the rows are printed first."""
    values = cbc_mod._parse_columns(CBC_SOLUTION_WITH_ROWS.splitlines()[1:])

    assert values == {"k0": 1.0, "k1": 1.0, "k2": 0.0, "k3": 0.0, "k4": 0.0, "k5": 0.0}
    assert "c" not in values, "the constraint row leaked into the solution"


def test_cbc_record_regex_survives_the_infeasibility_marker() -> None:
    """A `**`-marked row must still count as a record, or the block split moves."""
    values = cbc_mod._parse_columns(CBC_SOLUTION_INFEASIBLE.splitlines()[1:])

    assert values == {"a": 4.0}


@pytest.mark.parametrize(
    ("headline", "expected_status", "expected_has_solution"),
    [
        ("Optimal - objective value 29.50000000", SolverStatus.OPTIMAL, True),
        ("Optimal (within gap tolerance) - objective value 306679.0", SolverStatus.OPTIMAL, True),
        ("Infeasible - objective value 4.00000000", SolverStatus.INFEASIBLE, False),
        ("Unbounded - objective value 0.00000000", SolverStatus.UNBOUNDED, False),
        ("Stopped on gap - objective value 12.0", SolverStatus.OPTIMAL, True),
        ("Stopped on time - objective value 65.0", SolverStatus.TIME_LIMIT, True),
        (
            "Stopped on time (no integer solution - continuous used) - objective value 12.0",
            SolverStatus.TIME_LIMIT,
            False,
        ),
        ("", SolverStatus.ERROR, False),
    ],
)
def test_cbc_status_line_says_whether_values_may_be_read(
    headline: str, expected_status: SolverStatus, expected_has_solution: bool
) -> None:
    """The second half of the answer is the one that matters.

    CBC prints variable values under headlines that are not answers. The worst
    is "no integer solution - continuous used": those numbers are the linear
    relaxation, so handing them back would present a fractional plan as a
    result.
    """
    status, has_solution = cbc_mod._map_status(headline)

    assert status is expected_status
    assert has_solution is expected_has_solution


def test_cbc_time_limit_without_a_solution_reports_the_bound_and_no_answer() -> None:
    """# CONTRACT-TEST: a relaxation value is a bound, never an objective."""
    adapter = cbc_mod.CBCAdapter()
    run = cbc_mod.CliRun(stdout=CBC_STDOUT_STOPPED_ON_TIME, returncode=0, killed=False)

    result = adapter._build_result(
        CBC_SOLUTION_NO_INTEGER_SOLUTION, run, _binary_problem(2), elapsed=9.2
    )

    assert result.status is SolverStatus.TIME_LIMIT
    assert result.objective_value is None
    assert result.dual_bound == 12.0
    assert result.solution is None
    assert result.nodes == 24072
    assert result.iterations == 351289


# CONTRACT-TEST: a run cut off by its time limit must never come back with a gap
# of zero. Defaulting the bound to the answer said "proven optimal" about a
# search that had not finished, and a comparison table is read as evidence.
def test_cbc_with_an_answer_but_no_bound_does_not_claim_it_proved_it() -> None:
    adapter = cbc_mod.CBCAdapter()
    # A solution, a time limit, and no "Lower bound" line anywhere.
    run = cbc_mod.CliRun(
        stdout=(
            "Result - Stopped on time limit\n"
            "Enumerated nodes:               900\n"
            "Total iterations:               4200\n"
        ),
        returncode=0,
        killed=False,
    )

    result = adapter._build_result(
        "Stopped on time - objective value 21.00000000\n      0 k0   1   0\n      1 k1   1   0\n",
        run,
        _binary_problem(2),
        elapsed=5.0,
    )

    assert result.status is SolverStatus.TIME_LIMIT
    assert result.objective_value == 21.0
    assert result.dual_bound is None, "the answer was passed off as its own bound"
    assert result.gap is None, "a gap of zero would read as a proof CBC never made"


def test_cbc_at_optimality_takes_the_answer_as_its_own_bound() -> None:
    """A closed search does not always print a bound, and there the two are equal."""
    adapter = cbc_mod.CBCAdapter()
    run = cbc_mod.CliRun(
        stdout="Result - Optimal solution found\nEnumerated nodes:  3\n",
        returncode=0,
        killed=False,
    )

    result = adapter._build_result(
        "Optimal - objective value 21.00000000\n      0 k0   1   0\n      1 k1   1   0\n",
        run,
        _binary_problem(2),
        elapsed=1.0,
    )

    assert result.status is SolverStatus.OPTIMAL
    assert result.dual_bound == 21.0
    assert result.gap == 0.0


def test_cbc_reads_a_bound_written_in_scientific_notation() -> None:
    """A negative exponent is a number too. The value class used to stop at the
    minus sign, drop the line, and leave the bound unknown."""
    counters = cbc_mod._parse_counters(
        "Lower bound:                    -1.5e-05\nEnumerated nodes:  7\n",
        _binary_problem(1),
    )

    assert counters["dual_bound"] == -1.5e-05


def test_cbc_reports_no_bound_for_an_infeasible_model() -> None:
    """The number on an "Infeasible" headline is wherever CBC stopped, not a bound."""
    adapter = cbc_mod.CBCAdapter()
    run = cbc_mod.CliRun(stdout="Problem is infeasible - 0.00 seconds", returncode=0, killed=False)

    result = adapter._build_result(CBC_SOLUTION_INFEASIBLE, run, _binary_problem(1), elapsed=0.1)

    assert result.status is SolverStatus.INFEASIBLE
    assert result.dual_bound is None
    assert result.objective_value is None


def test_cbc_counts_no_nodes_on_a_pure_lp_and_still_counts_iterations() -> None:
    """An LP has no branch-and-bound tree, so "0 nodes" would be a false report."""
    problem = OptimizationProblem(
        name="lp",
        variables=[Variable(name="a", lower_bound=0, upper_bound=10)],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="a"),
        constraints=[Constraint(name="r", expression="a <= 4")],
    )

    counters = cbc_mod._parse_counters(CBC_STDOUT_PURE_LP, problem)

    assert counters["iterations"] == 2
    assert "nodes" not in counters


def test_cbc_missing_variable_is_an_error_not_a_zero() -> None:
    """# CONTRACT-TEST: a short answer fails loudly instead of being padded.

    A variable with no value would be stored as absent and read as zero, which
    is a plan the solver never proposed.
    """
    adapter = cbc_mod.CBCAdapter()
    run = cbc_mod.CliRun(stdout="", returncode=0, killed=False)

    with pytest.raises(SolverError, match="k6"):
        adapter._build_result(CBC_SOLUTION_WITH_ROWS, run, _binary_problem(8), elapsed=0.1)


def test_cbc_asks_for_the_wall_clock_and_not_cpu_seconds() -> None:
    """# CONTRACT-TEST: CBC's time limit must mean the clock a comparison shows.

    CBC's own default for ``-seconds`` is CPU time, and the two numbers come
    apart on a hard model. Measured on this project's market-split model with
    ``-seconds 5``: the default stopped after 7.94 seconds on the clock, and
    ``-timeMode elapsed`` after 5.01. A solver comparison states above the
    table that every solver received the same limit, so the extra seconds were
    reported as CBC being slow rather than as CBC being given more time.

    ``elapsed`` must be set before ``-seconds``, which is the order it was
    measured in.
    """
    adapter = cbc_mod.CBCAdapter()
    problem = _binary_problem(3)
    problem.options.time_limit_seconds = 5

    argv = adapter._argv("/usr/bin/cbc", Path("/tmp/p.lp"), Path("/tmp/s.txt"), problem)

    assert "-timeMode" in argv
    assert argv[argv.index("-timeMode") + 1] == "elapsed"
    assert argv.index("-timeMode") < argv.index("-seconds")
    assert argv[argv.index("-seconds") + 1] == "5.0"


# ── GLPK ─────────────────────────────────────────────────────────────────────

# glpsol 5.0, `-w` on a pure LP: the basic-solution shape, values by index only.
GLPK_RAW_LP = """c Problem:
c Rows:       3
c Columns:    5
c Non-zeros:  7
c Status:     OPTIMAL
c Objective:  Obj = 12 (MAXimum)
c
s bas 3 5 f f 12
i 1 u 7 1
i 2 u 5 1
i 3 b 2 0
j 1 b 7 0
j 2 l 0 -1
j 3 b 5 0
j 4 l 0 0
j 5 l 0 0
e o f
"""

# The same run's `-o` report. Names over twelve characters wrap onto the next
# line, and that continuation starts with the activity value — the one thing
# that could be mistaken for a record of its own.
GLPK_REPORT_LP = """Problem:
Rows:       3
Columns:    5
Non-zeros:  7
Status:     OPTIMAL
Objective:  Obj = 12 (MAXimum)

   No.   Row name   St   Activity     Lower bound   Upper bound    Marginal
------ ------------ -- ------------- ------------- ------------- -------------
     1 r1           NU             7                           7             1
     2 r2           NU             5                           5             1
     3 r3           B              2            -2

   No. Column name  St   Activity     Lower bound   Upper bound    Marginal
------ ------------ -- ------------- ------------- ------------- -------------
     1 ab           B              7             0            10
     2 name_len_12x NL             0             0            10            -1
     3 name_len_13xy
                    B              5             0            10
     4 name_len_20_xxxxxxxx
                    NL             0             0            10         < eps
     5 nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
                    NL             0             0            10         < eps
"""

# `-w` on a MIP that ran out of time with an incumbent in hand.
GLPK_RAW_MIP_FEASIBLE = """c Status:     INTEGER NON-OPTIMAL
c Objective:  Obj = 306683 (MAXimum)
c
s mip 1 90 f 306683
i 1 245683
j 1 1
j 2 0
e o f
"""

GLPK_STDOUT_TIME_LIMIT = """Solving LP relaxation...
OPTIMAL LP SOLUTION FOUND
Integer optimization begins...
+   924: >>>>>   3.066810000e+05 <=   3.070510000e+05   0.1% (753; 45)
+ 23360: mip =   3.066830000e+05 <=   3.068030000e+05 < 0.1% (11518; 7765)
TIME LIMIT EXCEEDED; SEARCH TERMINATED
Time used:   6.0 secs
"""

GLPK_STDOUT_UNBOUNDED_MIP = """Preprocessing...
LP RELAXATION HAS NO DUAL FEASIBLE SOLUTION
Time used:   0.0 secs
"""

GLPK_STDOUT_NO_BOUND_YET = """Integer optimization begins...
+    31: mip =     not found yet >=              -inf        (1; 0)
TIME LIMIT EXCEEDED; SEARCH TERMINATED
"""


# --------------------------------------------------------------------------- #
# CBC's search trace
#
# Verbatim from `cbc -log 2` on a 45-item knapsack this project generated, run
# inside the comparison worker image on 2026-09-01. Two things in it decide the
# parser and neither is documented anywhere:
#
#   - "no incumbent yet" is printed as CBC's own infinity, signed to match the
#     objective sense: -1e+50 under maximization;
#   - CBC restarts its search and starts the node count again from zero, so the
#     raw log announces "no incumbent" AFTER it has already reported one.
# --------------------------------------------------------------------------- #

CBC_TRACE = """\
Cbc0010I After 0 nodes, 1 on tree, -1e+50 best solution, best possible 130552.63 (0.00 seconds)
Cbc0010I After 50 nodes, 20 on tree, 130442 best solution, best possible 130552.63 (0.04 seconds)
Cbc0010I After 100 nodes, 18 on tree, 130442 best solution, best possible 130520.10 (0.09 seconds)
Cbc0010I After 150 nodes, 21 on tree, 130480 best solution, best possible 130500.00 (0.15 seconds)
Cbc0010I After 0 nodes, 1 on tree, -1e+50 best solution, best possible 130500.00 (0.16 seconds)
Cbc0010I After 50 nodes, 10 on tree, 130485 best solution, best possible 130490.00 (0.22 seconds)
Cbc0001I Search completed - best objective 130485, took 812 iterations and 200 nodes
"""


def test_cbc_trace_becomes_points_a_convergence_chart_can_draw() -> None:
    points = cbc_mod._parse_progress(CBC_TRACE)

    assert [p.objective for p in points] == [130442.0, 130442.0, 130480.0, 130485.0]
    assert [p.elapsed_seconds for p in points] == [0.04, 0.09, 0.15, 0.22]
    assert [p.dual_bound for p in points] == [130552.63, 130520.1, 130500.0, 130490.0]
    # iteration is the snapshot number, the same meaning the SCIP handler gives it
    assert [p.iteration for p in points] == [1, 2, 3, 4]
    assert [p.node for p in points] == [50, 100, 150, 50]


# CONTRACT-TEST: CBC prints its own infinity where an objective goes, signed to
# match the sense, and it prints it again after a restart when it already holds
# an answer. Drawn as a number, -1e+50 flattens every real point onto the axis;
# drawn as a real incumbent, the primal line falls off a cliff mid-search.
def test_cbc_no_incumbent_placeholder_never_becomes_a_point() -> None:
    points = cbc_mod._parse_progress(CBC_TRACE)

    assert all(abs(p.objective) < 1e30 for p in points)
    assert len(points) == 4, "the two -1e+50 lines must not be points"


# CONTRACT-TEST: filtering the placeholders is what makes the incumbent series
# monotone. Without it a restart reads as the solver losing its answer.
def test_cbc_incumbent_never_goes_backwards_across_a_restart() -> None:
    points = cbc_mod._parse_progress(CBC_TRACE)
    objectives = [p.objective for p in points]

    assert objectives == sorted(objectives), f"incumbent went backwards: {objectives}"


def test_cbc_trace_carries_the_objective_offset_the_lp_file_dropped() -> None:
    """CBC drops an objective constant without a word, so it is added back here.

    A trace converging on a different number than the result printed above it
    would be read as a broken chart, not as a solver quirk.
    """
    points = cbc_mod._parse_progress(CBC_TRACE, objective_offset=1000.0)

    assert [p.objective for p in points] == [131442.0, 131442.0, 131480.0, 131485.0]
    assert [p.dual_bound for p in points] == [131552.63, 131520.1, 131500.0, 131490.0]


def test_cbc_gap_is_computed_from_the_two_numbers_on_the_line() -> None:
    points = cbc_mod._parse_progress(CBC_TRACE)

    last = points[-1]
    assert last.gap == pytest.approx(abs(130485.0 - 130490.0) / 130485.0)


def test_cbc_bound_of_infinity_leaves_the_point_without_one() -> None:
    trace = (
        "Cbc0010I After 10 nodes, 2 on tree, 42 best solution, best possible 1e+50 (0.50 seconds)\n"
    )
    points = cbc_mod._parse_progress(trace)

    assert len(points) == 1
    assert points[0].objective == 42.0
    assert points[0].dual_bound is None
    assert points[0].gap is None


def test_cbc_pure_lp_prints_no_trace_and_that_is_not_an_error() -> None:
    lp_output = "Optimal objective 12 - 2 iterations time 0.002, Presolve 0.00\n"

    assert cbc_mod._parse_progress(lp_output) == []


# CONTRACT-TEST: a long search prints thousands of these lines. A chart cannot
# draw more points than it has pixels, and the payload travels to the browser.
def test_cbc_trace_is_downsampled_but_keeps_its_ends() -> None:
    lines = [
        f"Cbc0010I After {n} nodes, 1 on tree, {1000 + n} best solution, "
        f"best possible {2000 + n} ({n / 100:.2f} seconds)"
        for n in range(1, 1501)
    ]
    points = cbc_mod._parse_progress("\n".join(lines))

    assert len(points) <= cbc_mod._MAX_PROGRESS_POINTS
    assert points[0].objective == 1001.0
    assert points[-1].objective == 2500.0


def test_glpk_column_names_come_out_in_order_including_the_wrapped_ones() -> None:
    """A name over twelve characters wraps, and the numbers below it are not a name."""
    names = glpk_mod._parse_column_names(GLPK_REPORT_LP)

    assert names == {
        1: "ab",
        2: "name_len_12x",
        3: "name_len_13xy",
        4: "name_len_20_xxxxxxxx",
        5: "n" * 40,
    }
    assert "r1" not in names.values(), "a constraint row leaked into the column names"


def test_glpk_reads_values_from_the_basic_solution_shape() -> None:
    solution = glpk_mod._parse_raw_solution(GLPK_RAW_LP)

    assert solution.has_solution is True
    assert solution.objective_value == 12.0
    # `j 1 b 7 0` — index, basis status, value, reduced cost. The value is the
    # THIRD field here and the SECOND in the MIP shape below.
    assert solution.column_values == {1: 7.0, 2: 0.0, 3: 5.0, 4: 0.0, 5: 0.0}


def test_glpk_reads_values_from_the_mip_shape() -> None:
    solution = glpk_mod._parse_raw_solution(GLPK_RAW_MIP_FEASIBLE)

    assert solution.has_solution is True
    assert solution.objective_value == 306683.0
    assert solution.column_values == {1: 1.0, 2: 0.0}


def test_glpk_no_solution_marker_means_no_numbers_are_read() -> None:
    """`s mip ... n` and `s mip ... u` both mean glpsol found nothing."""
    for marker in ("n", "u"):
        solution = glpk_mod._parse_raw_solution(f"s mip 2 1 {marker} 0\nj 1 0\ne o f\n")
        assert solution.has_solution is False
        assert solution.objective_value is None


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        (GLPK_STDOUT_TIME_LIMIT, SolverStatus.TIME_LIMIT),
        (GLPK_STDOUT_UNBOUNDED_MIP, SolverStatus.UNBOUNDED),
        ("PROBLEM HAS NO PRIMAL FEASIBLE SOLUTION\n", SolverStatus.INFEASIBLE),
        ("OPTIMAL LP SOLUTION FOUND\n", SolverStatus.OPTIMAL),
        ("INTEGER OPTIMAL SOLUTION FOUND\n", SolverStatus.OPTIMAL),
        ("RELATIVE MIP GAP TOLERANCE REACHED; SEARCH TERMINATED\n", SolverStatus.OPTIMAL),
        ("nothing recognisable here\n", None),
    ],
)
def test_glpk_verdict_is_the_last_one_printed(stdout: str, expected: SolverStatus | None) -> None:
    """# CONTRACT-TEST: a MIP prints its relaxation's verdict long before its own.

    ``OPTIMAL LP SOLUTION FOUND`` appears in the middle of every MIP run. Taking
    the first match would report a timed-out search as optimal.
    """
    assert glpk_mod._verdict(stdout) is expected


def test_glpk_counters_come_from_the_last_progress_line() -> None:
    counters = glpk_mod._parse_counters(GLPK_STDOUT_TIME_LIMIT, _binary_problem(2))

    assert counters["iterations"] == 23360
    assert counters["dual_bound"] == pytest.approx(306803.0)
    assert counters["nodes"] == 7765


def test_glpk_forgets_a_bound_it_can_no_longer_claim() -> None:
    """ "not found yet >= -inf" is unknown, and unknown must not read as a number."""
    counters = glpk_mod._parse_counters(GLPK_STDOUT_NO_BOUND_YET, _binary_problem(2))

    assert "dual_bound" not in counters
    assert counters["iterations"] == 31


# ── shared helpers ───────────────────────────────────────────────────────────


def test_relative_gap_is_computed_and_not_read_from_the_solver() -> None:
    """CBC prints its gap to two decimals, which is why JAOT divides it itself."""
    assert relative_gap(65.0, 54.924) == pytest.approx(0.1550153846)
    assert relative_gap(100.0, 100.0) == 0.0
    assert relative_gap(None, 3.0) is None
    assert relative_gap(3.0, None) is None
    assert relative_gap(3.0, float("inf")) is None


def test_parse_float_refuses_the_words_solvers_print_where_numbers_go() -> None:
    assert parse_float("3.5") == 3.5
    assert parse_float("+inf") is None
    assert parse_float("tree") is None
    assert parse_float("not") is None


def test_tail_keeps_the_end_because_that_is_where_the_reason_is() -> None:
    text = "\n".join(f"line {i}" for i in range(50))

    assert tail(text, lines=3) == "line 47\nline 48\nline 49"


# ---------------------------------------------------------------------------
# What a failed run is allowed to say
#
# `error_message` is shown to whoever ran the comparison. The CLI solvers are
# handed a temp file and print its full path back — in the verdict line, in a
# parse error, in whatever goes to stderr — and a stringified subprocess failure
# carries the whole argv with it. All of that was reaching the results table.
# ---------------------------------------------------------------------------


def test_scrub_paths_keeps_the_filename_and_drops_the_directory() -> None:
    scrubbed = scrub_paths("glpsol: cannot open file /tmp/tmpxyz123.lp")
    assert "/tmp/" not in scrubbed
    # The name is what makes the sentence mean anything, and gives nothing away.
    assert "tmpxyz123.lp" in scrubbed


# CONTRACT-TEST: a message shown to a user never carries a server path
def test_scrub_paths_strips_an_argv_out_of_a_subprocess_error() -> None:
    raw = "Command '['cbc', '/tmp/tmpab12.lp', '-solve']' returned non-zero exit status 1."
    scrubbed = scrub_paths(raw)
    assert "/tmp/tmpab12.lp" not in scrubbed
    assert "tmpab12.lp" in scrubbed
    assert "non-zero exit status 1" in scrubbed


def test_scrub_paths_leaves_ordinary_words_alone() -> None:
    for text in (
        "GLPK: the objective has no variables",
        "PROBLEM HAS NO PRIMAL FEASIBLE SOLUTION",
        "ratio 3/4 is fine",
    ):
        assert scrub_paths(text) == text


def test_scrub_paths_handles_a_windows_path() -> None:
    scrubbed = scrub_paths(r"cannot read C:\Users\someone\AppData\Local\Temp\model.lp")
    assert "AppData" not in scrubbed
    assert "model.lp" in scrubbed


def test_tail_scrubs_what_it_returns() -> None:
    """`tail` is the one path solver output takes to a user's screen."""
    output = "reading /tmp/tmpqq.lp\nsyntax error at line 4\nglpsol: /tmp/tmpqq.lp is unreadable"
    trimmed = tail(output)
    assert "/tmp/" not in trimmed
    assert "syntax error at line 4" in trimmed
