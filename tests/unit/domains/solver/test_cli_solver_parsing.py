"""Parsing tests for the CBC and GLPK adapters, against output they really wrote.

Every fixture in this file is a verbatim copy of what the binaries printed on
this project's own models — not a guess at their format. Both solvers write
plain text in shapes nobody documents, and a parser tested against invented
output proves only that the author is consistent with themselves.

No binary runs here. The tests that do run one are in
``test_cli_solver_adapters.py``.
"""

from __future__ import annotations

import pytest

from app.domains.solver.adapters import cbc as cbc_mod, glpk as glpk_mod
from app.domains.solver.adapters._cli_solver import parse_float, relative_gap, tail
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
