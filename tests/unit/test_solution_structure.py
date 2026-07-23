"""A1: recover variable index structure server-side (parse + adapter round-trip).

The JModel compiler stamps authoritative family/index_tuple (tested in
``tests/unit/domains/dsl/test_compiler.py``); here we cover the best-effort
parse for flat/imported models, the no-op-when-compiler-ran guard, and the
end-to-end round-trip that the recovered structure reaches the solved result
and its serialized ``result_data``.
"""

import pytest

from app.schemas.optimization import (
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    OptimizationResult,
    SolverStatus,
    Variable,
    VariableSolution,
    VariableType,
)
from app.schemas.solution_structure import annotate_variable_structure, parse_flat_name

pytestmark = pytest.mark.unit


def _problem(names: list[str]) -> OptimizationProblem:
    return OptimizationProblem(
        variables=[Variable(name=n, type=VariableType.BINARY) for n in names],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression=" + ".join(names)),
    )


def test_parse_flat_name_numeric_indices():
    assert parse_flat_name("x_3_5") == ("x", ["3", "5"])
    assert parse_flat_name("route_1") == ("route", ["1"])
    # family names may themselves contain underscores as long as the trailing
    # segments are the numeric indices
    assert parse_flat_name("x_cost_3") == ("x_cost", ["3"])
    # a digit-bearing family segment stays whole when nothing follows it but
    # the numeric index (segments are never re-split)
    assert parse_flat_name("x12_3") == ("x12", ["3"])


def test_parse_flat_name_alphanumeric_indices():
    # MDPDP-style composite labels: letters-then-digits segments are indices,
    # and the index suffix is maximal (family = "xsc", not "xsc_s1_c1").
    assert parse_flat_name("xsc_s1_c1_k1") == ("xsc", ["s1", "c1", "k1"])
    assert parse_flat_name("assign_v3_o107") == ("assign", ["v3", "o107"])
    # numeric and alphanumeric labels can mix
    assert parse_flat_name("y_s2_7") == ("y", ["s2", "7"])


def test_parse_flat_name_rejects_ambiguous():
    assert parse_flat_name("total_cost") is None  # no index-shaped suffix at all
    assert parse_flat_name("x") is None  # scalar, no underscore
    assert parse_flat_name("x0") is None  # digits but no underscore boundary
    assert parse_flat_name("x_3_cost") is None  # index then non-index — ambiguous
    assert parse_flat_name("x_s1c2") is None  # digits inside the label, not trailing


def test_annotate_fills_flat_problem():
    problem = _problem(["x_1", "x_2", "y_3_4", "total"])
    annotate_variable_structure(problem)
    by = {v.name: v for v in problem.variables}
    assert (by["x_1"].family, by["x_1"].index_tuple) == ("x", ["1"])
    assert (by["y_3_4"].family, by["y_3_4"].index_tuple) == ("y", ["3", "4"])
    assert by["total"].family is None  # unparseable → stays flat


# CONTRACT-TEST: the parse must NOT run once the compiler has annotated a
# problem — it would mislabel a deliberately-scalar variable named like an
# indexed one (e.g. penalty_5) as family "penalty" index 5.
def test_annotate_is_noop_when_compiler_already_structured():
    problem = _problem(["assign_v3_o107", "penalty_5"])
    problem.variables[0].family = "assign"
    problem.variables[0].index_tuple = ["v3", "o107"]
    annotate_variable_structure(problem)
    assert problem.variables[1].family is None
    assert problem.variables[1].index_tuple is None


def test_solved_result_carries_structure_end_to_end():
    """SCIP solve of a JModel-compiled model → structure on every VariableSolution
    → survives to_result_data() (the shape persisted + served to UI/MCP)."""
    from app.domains.dsl import compile_jmodel
    from app.domains.solver.adapters.scip import SCIPAdapter

    source = """
    set WORKERS := {A, B};
    set TASKS := {1, 2};
    param cost{WORKERS, TASKS} := A 1 1, A 2 2, B 1 2, B 2 1;
    var assign{WORKERS, TASKS} binary;
    minimize total: sum{w in WORKERS, t in TASKS} cost[w, t] * assign[w, t];
    subject to one_each{t in TASKS}: sum{w in WORKERS} assign[w, t] == 1;
    """
    result = SCIPAdapter().solve(compile_jmodel(source))
    assert result.status == SolverStatus.OPTIMAL
    by_name = {v.name: v for v in result.variables}
    assert by_name["assign_A_1"].family == "assign"
    assert by_name["assign_A_1"].index_tuple == ["A", "1"]

    # The serialized shape that lands in ModelExecution.result_data must carry it.
    serialized = {v["name"]: v for v in result.to_result_data()["variables"]}
    assert serialized["assign_B_2"]["family"] == "assign"
    assert serialized["assign_B_2"]["index_tuple"] == ["B", "2"]


def test_variable_solution_structure_defaults_none():
    """A flat/hand-authored VariableSolution stays unstructured (renders flat)."""
    vs = VariableSolution(name="x", value=1.0, type=VariableType.BINARY)
    assert vs.family is None and vs.index_tuple is None
    dumped = OptimizationResult(
        status=SolverStatus.OPTIMAL, solve_time_seconds=0.0, variables=[vs]
    ).to_result_data()
    assert dumped["variables"][0]["family"] is None
