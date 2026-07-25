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


def test_parse_flat_name_underscored_index_labels():
    """Routing generators name nodes ``o_0`` / ``p_1``, so an arc is ``x_o_0_p_1_2``.

    The strict pattern rejects those outright (``o`` is purely alphabetic), which
    left every arc variable of such a model unstructured — no family, no grouping,
    no map.
    """
    assert parse_flat_name("x_o_0_p_0_0") == ("x", ["o_0", "p_0", "0"])
    assert parse_flat_name("x_p_0_d_1_2") == ("x", ["p_0", "d_1", "2"])
    # Ordinals are not single-digit-only.
    assert parse_flat_name("x_o_10_e_3_1") == ("x", ["o_10", "e_3", "1"])
    # A tag with no ordinal after it is still not an index.
    assert parse_flat_name("x_o_0_bad") is None
    assert parse_flat_name("x_o") is None
    # Malformed segments stay rejected.
    assert parse_flat_name("_x_1") is None
    assert parse_flat_name("x__1") is None


# CONTRACT-TEST: the wider reading runs ONLY on names the strict parse refused.
# Accepting "<tag>_<ordinal>" as one index is the same shape as the flat name
# "x_cost_3", so the ambiguity is resolved by ORDER, not by cleverness — it may
# add structure where there was none, never reinterpret a name that already reads.
def test_underscored_reading_never_reinterprets_a_name_that_already_parses():
    already_parse = {
        "x_cost_3": ("x_cost", ["3"]),
        "x_3_5": ("x", ["3", "5"]),
        "xsc_s1_c1_k1": ("xsc", ["s1", "c1", "k1"]),
        "assign_v3_o107": ("assign", ["v3", "o107"]),
        "x12_3": ("x12", ["3"]),
        "y_s2_7": ("y", ["s2", "7"]),
        "route_1": ("route", ["1"]),
    }
    for name, expected in already_parse.items():
        assert parse_flat_name(name) == expected, f"{name} was reinterpreted"


def test_underscored_reading_documents_its_known_limit():
    """A name that parses strictly but *wrongly* is not repaired — by design.

    In the same routing model, ``s_p_0_1`` is the arrival time at node ``p_0``
    for vehicle ``1``, so the honest reading would be family ``s``. It parses
    strictly as ``s_p`` over ``(0, 1)`` instead, and nothing in the NAME
    distinguishes it from a genuine ``x_cost_3``. Repairing it would take a
    guess this module refuses to make; pinning it here so the limit is a
    recorded decision rather than an unnoticed bug.
    """
    assert parse_flat_name("s_p_0_1") == ("s_p", ["0", "1"])


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
