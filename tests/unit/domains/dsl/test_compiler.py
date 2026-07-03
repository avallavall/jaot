"""Unit tests for the JModel DSL compiler (P5).

Covers deterministic lowering of three real models, structural assertions on the
emitted flat OptimizationProblem, a real SCIP solve to the known optima, and the
error paths. Grammar: ``.claude/plans/jmodel-grammar-2026-07-01.md``.
"""

import pytest

from app.domains.dsl import JModelData, JModelError, compile_jmodel
from app.schemas.optimization import VariableType

pytestmark = pytest.mark.unit


ASSIGNMENT = """
set WORKERS := {A, B, C};
set TASKS := {1, 2, 3};

param cost{WORKERS, TASKS} :=
    A 1 9, A 2 2, A 3 7,
    B 1 6, B 2 4, B 3 3,
    C 1 5, C 2 8, C 3 1;

var assign{WORKERS, TASKS} binary;

minimize total_cost:
    sum{w in WORKERS, t in TASKS} cost[w, t] * assign[w, t];

subject to one_worker_per_task{t in TASKS}:
    sum{w in WORKERS} assign[w, t] == 1;

subject to one_task_per_worker{w in WORKERS}:
    sum{t in TASKS} assign[w, t] == 1;
"""

KNAPSACK = """
set ITEMS := {a, b, c, d};
param value{ITEMS} := a 60, b 100, c 120, d 40;
param weight{ITEMS} := a 10, b 20, c 30, d 15;
param cap := 50;
var take{ITEMS} binary;
maximize total_value:
    sum{i in ITEMS} value[i] * take[i];
subject to capacity:
    sum{i in ITEMS} weight[i] * take[i] <= cap;
"""

EDGE_SELECT = """
set NODES := {1, 2, 3};
param dist{NODES, NODES} :=
    1 2 4, 1 3 2,
    2 1 3, 2 3 5,
    3 1 6, 3 2 1;
var pick{NODES, NODES} binary;
minimize total_dist:
    sum{i in NODES, j in NODES: i != j} dist[i, j] * pick[i, j];
subject to one_out{i in NODES}:
    sum{j in NODES: i != j} pick[i, j] == 1;
"""


# --------------------------------------------------------------------------- #
# Structural lowering
# --------------------------------------------------------------------------- #


def test_assignment_lowering():
    prob = compile_jmodel(ASSIGNMENT)

    assert prob.name == "total_cost"
    assert len(prob.variables) == 9
    assert all(v.type == VariableType.BINARY for v in prob.variables)
    assert all(v.lower_bound == 0.0 and v.upper_bound == 1.0 for v in prob.variables)
    assert [v.name for v in prob.variables][:3] == ["assign_A_1", "assign_A_2", "assign_A_3"]

    assert prob.objective.sense.value == "minimize"
    assert prob.objective.expression == (
        "9*assign_A_1 + 2*assign_A_2 + 7*assign_A_3 "
        "+ 6*assign_B_1 + 4*assign_B_2 + 3*assign_B_3 "
        "+ 5*assign_C_1 + 8*assign_C_2 + assign_C_3"
    )

    assert len(prob.constraints) == 6
    by_name = {c.name: c.expression for c in prob.constraints}
    assert by_name["one_worker_per_task_1"] == "assign_A_1 + assign_B_1 + assign_C_1 == 1"
    assert by_name["one_task_per_worker_A"] == "assign_A_1 + assign_A_2 + assign_A_3 == 1"


def test_knapsack_lowering_scalar_param_and_maximize():
    prob = compile_jmodel(KNAPSACK)

    assert len(prob.variables) == 4
    assert prob.objective.sense.value == "maximize"
    assert prob.objective.expression == "60*take_a + 100*take_b + 120*take_c + 40*take_d"

    assert len(prob.constraints) == 1
    # scalar param `cap` resolved into the RHS
    assert prob.constraints[0].expression == "10*take_a + 20*take_b + 30*take_c + 15*take_d <= 50"


def test_edge_select_filters_drop_self_loops():
    prob = compile_jmodel(EDGE_SELECT)

    # the family declares all 9 pick[i,j] vars (incl. self-loops)...
    assert len(prob.variables) == 9
    # ...but the `i != j` filter keeps self-loops out of the objective and constraints
    assert "pick_1_1" not in prob.objective.expression
    assert prob.objective.expression == (
        "4*pick_1_2 + 2*pick_1_3 + 3*pick_2_1 + 5*pick_2_3 + 6*pick_3_1 + pick_3_2"
    )
    by_name = {c.name: c.expression for c in prob.constraints}
    assert by_name["one_out_1"] == "pick_1_2 + pick_1_3 == 1"
    assert "pick_1_1" not in by_name["one_out_1"]


def test_lowering_is_deterministic():
    a = compile_jmodel(ASSIGNMENT).model_dump()
    b = compile_jmodel(ASSIGNMENT).model_dump()
    assert a == b


# --------------------------------------------------------------------------- #
# Semantic correctness — real solve to the known optima
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source", "expected_objective"),
    [(ASSIGNMENT, 9.0), (KNAPSACK, 220.0), (EDGE_SELECT, 6.0)],
)
def test_compiled_models_solve_to_known_optimum(source, expected_objective):
    from app.domains.solver.adapters.scip import SCIPAdapter

    result = SCIPAdapter().solve(compile_jmodel(source))
    assert result.status.value == "optimal"
    assert result.objective_value is not None
    assert abs(result.objective_value - expected_objective) < 1e-6


# --------------------------------------------------------------------------- #
# Grammar edge cases
# --------------------------------------------------------------------------- #


def test_empty_sum_is_zero():
    # NONE is empty -> the sum grounds to 0, leaving just the constant on the RHS
    prob = compile_jmodel(
        """
        set NONE := {};
        var x >= 0;
        minimize obj: x;
        subject to c: x + sum{i in NONE} x >= 5;
        """
    )
    assert prob.constraints[0].expression == "x >= 5"


def test_scalar_variable_and_bounds():
    prob = compile_jmodel(
        """
        var x integer >= 0 <= 100;
        minimize obj: x;
        subject to c: x >= 7;
        """
    )
    assert len(prob.variables) == 1
    v = prob.variables[0]
    assert v.name == "x" and v.type == VariableType.INTEGER
    assert v.lower_bound == 0.0 and v.upper_bound == 100.0


def test_constant_folding_in_coefficients():
    prob = compile_jmodel(
        """
        var x >= 0;
        minimize obj: 2 * 3 * x;
        subject to c: x <= 10;
        """
    )
    assert prob.objective.expression == "6*x"


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #


def test_missing_objective_raises():
    with pytest.raises(JModelError, match="no objective"):
        compile_jmodel("var x >= 0; subject to c: x >= 1;")


def test_unknown_symbol_raises():
    with pytest.raises(JModelError, match="unknown symbol"):
        compile_jmodel("var x >= 0; minimize obj: x + y; subject to c: x >= 1;")


def test_nonlinear_term_rejected():
    with pytest.raises(JModelError, match="nonlinear"):
        compile_jmodel("var x >= 0; var y >= 0; minimize obj: x * y; subject to c: x >= 1;")


def test_param_missing_index_value_raises():
    with pytest.raises(JModelError, match="no value for index"):
        compile_jmodel(
            """
            set S := {a, b};
            param p{S} := a 5;
            var x{S} >= 0;
            minimize obj: sum{i in S} p[i] * x[i];
            subject to c: x[a] >= 1;
            """
        )


def test_variable_wrong_arity_raises():
    with pytest.raises(JModelError, match="subscript"):
        compile_jmodel(
            """
            set S := {a, b};
            var x{S} >= 0;
            minimize obj: x[a, b];
            subject to c: x[a] >= 1;
            """
        )


def test_syntax_error_reports_position():
    with pytest.raises(JModelError) as exc:
        compile_jmodel("set S := {a, b}\nvar x >= 0;")  # missing ';' after the set
    assert exc.value.position is not None


def test_illegal_character_raises():
    with pytest.raises(JModelError, match="illegal character"):
        compile_jmodel("var x >= 0; minimize obj: x @ 1; subject to c: x >= 1;")


def test_duplicate_variable_family_raises():
    with pytest.raises(JModelError, match="already declared as a variable"):
        compile_jmodel("var x >= 0; var x >= 0; minimize obj: x; subject to c: x >= 1;")


def test_constraint_requires_relational_operator():
    with pytest.raises(JModelError, match="relational operator"):
        compile_jmodel("var x >= 0; minimize obj: x; subject to c: x + 1;")


# --------------------------------------------------------------------------- #
# Hardening — declaration validation
# --------------------------------------------------------------------------- #


def test_undefined_set_in_var_family_raises():
    # A raw KeyError here used to escape as a 500 from /dsl/compile.
    with pytest.raises(JModelError, match="unknown set 'J' in variable family") as exc:
        compile_jmodel("var x{J}; minimize obj: 0; subject to c: 0 <= 1;")
    assert exc.value.position is not None


def test_undefined_set_in_param_raises():
    with pytest.raises(JModelError, match="unknown set 'J' in param"):
        compile_jmodel(
            "param p{J} := a 1; var x >= 0; minimize obj: x; subject to c: x >= 1;"
        )


def test_param_data_key_not_in_set_raises():
    # A typo'd data key used to be accepted silently (surfacing later or never).
    with pytest.raises(JModelError, match="not in set 'S'"):
        compile_jmodel(
            """
            set S := {item1, item2};
            param p{S} := iteem1 5, item2 7;
            var x{S} >= 0;
            minimize obj: sum{i in S} p[i] * x[i];
            subject to c: x[item1] >= 1;
            """
        )


def test_ghost_variable_reference_raises():
    # x is declared over I but indexed with a member of the larger J: without the
    # membership check this emitted a flat name that exists nowhere in the expansion.
    with pytest.raises(JModelError, match="'c' is not a member of set 'I'"):
        compile_jmodel(
            """
            set I := {a, b};
            set J := {a, b, c};
            var x{I} >= 0;
            minimize obj: sum{i in I} x[i];
            subject to cover{j in J}: x[j] <= 1;
            """
        )


def test_unknown_filter_identifier_raises():
    # A typo'd filter term used to degrade to a literal string, silently making the
    # filter a no-op (every tuple kept).
    with pytest.raises(JModelError, match="unknown index 'jj' in filter"):
        compile_jmodel(
            """
            set I := {a, b};
            var x{I} >= 0;
            minimize obj: sum{i in I: jj != i} x[i];
            subject to c: x[a] >= 1;
            """
        )


def test_reserved_word_as_name_rejected():
    with pytest.raises(JModelError, match="reserved word"):
        compile_jmodel("var sum >= 0; minimize obj: 0; subject to c: 0 <= 1;")
    with pytest.raises(JModelError, match="reserved word"):
        compile_jmodel("set in := {a}; var x >= 0; minimize obj: x; subject to c: x >= 1;")


def test_cross_namespace_collision_rejected():
    with pytest.raises(JModelError, match="already declared as a param"):
        compile_jmodel("param c := 5; var c >= 0; minimize obj: c; subject to k: c >= 1;")


def test_binary_with_explicit_bounds_rejected():
    with pytest.raises(JModelError, match="binary"):
        compile_jmodel("var x binary >= 5; minimize obj: x; subject to c: x >= 0;")


def test_crossed_bounds_rejected():
    with pytest.raises(JModelError, match="lower bound"):
        compile_jmodel("var x >= 5 <= 2; minimize obj: x; subject to c: x >= 0;")


# --------------------------------------------------------------------------- #
# Hardening — numeric emission (the flat ExpressionParser reads no e-notation)
# --------------------------------------------------------------------------- #


def test_float_coefficients_emitted_positionally():
    prob = compile_jmodel(
        """
        var x >= 0;
        var y >= 0;
        param tiny := .0000001;
        param big := 1234567.89;
        minimize obj: big * x + tiny * y;
        subject to c: x + y >= 2;
        """
    )
    # %g used to emit '1.23457e+06' (precision loss) and '1e-07' — both of which the
    # flat ExpressionParser misreads as a ghost variable 'e'.
    assert "e" not in prob.objective.expression
    assert prob.objective.expression == "1234567.89*x + 0.0000001*y"


def test_float_model_solves_correctly():
    from app.domains.solver.adapters.scip import SCIPAdapter

    prob = compile_jmodel(
        """
        var x >= 0;
        var y >= 0;
        param cheap := 0.5;
        param dear := 1234567.89;
        minimize obj: dear * x + cheap * y;
        subject to demand: x + y >= 2;
        """
    )
    result = SCIPAdapter().solve(prob)
    assert result.status.value == "optimal"
    assert result.objective_value is not None
    assert abs(result.objective_value - 1.0) < 1e-6  # all demand on the cheap variable


def test_huge_number_literal_rejected():
    with pytest.raises(JModelError, match="too large"):
        compile_jmodel(f"param big := {'9' * 400}; var x >= 0; minimize obj: x;")


# --------------------------------------------------------------------------- #
# Hardening — grounded semantics
# --------------------------------------------------------------------------- #


def test_variables_on_both_sides_of_a_constraint():
    prob = compile_jmodel(
        """
        var x >= 0;
        var y >= 0;
        minimize obj: x + y;
        subject to c: x >= y;
        """
    )
    # the RHS variable must move to the LHS with a negated coefficient
    assert prob.constraints[0].expression == "x - y >= 0"


def test_sum_binds_to_the_following_term_only():
    prob = compile_jmodel(
        """
        set I := {a, b};
        var x{I} >= 0;
        var y >= 0;
        minimize obj: sum{i in I} x[i] - y;
        subject to c: y >= 1;
        """
    )
    # AMPL precedence: the sum spans only the next term, so y is subtracted ONCE
    assert prob.objective.expression == "x_a + x_b - y"


def test_trivially_true_constant_row_is_dropped():
    prob = compile_jmodel(
        """
        set I := {a};
        var x{I} >= 0;
        minimize obj: x[a];
        subject to vacuous: sum{i in I: i != a} x[i] <= 5;
        subject to real: x[a] >= 1;
        """
    )
    names = [c.name for c in prob.constraints]
    assert "vacuous" not in names
    assert "real" in names


def test_constant_violated_row_is_a_compile_error():
    with pytest.raises(JModelError, match="constant and violated"):
        compile_jmodel(
            """
            set I := {a};
            var x{I} >= 0;
            minimize obj: x[a];
            subject to impossible: sum{i in I: i != a} x[i] >= 5;
            """
        )


def test_constraint_name_collision_after_mangling_rejected():
    with pytest.raises(JModelError, match="constraint name collision"):
        compile_jmodel(
            """
            set I := {a};
            var x{I} >= 0;
            minimize obj: x[a];
            subject to c{i in I}: x[i] <= 1;
            subject to c_a: x[a] <= 1;
            """
        )


# --------------------------------------------------------------------------- #
# Hardening — resource bounds
# --------------------------------------------------------------------------- #


def test_expansion_budget_rejects_blowup_before_grounding():
    src = """
    set A := {a, b, c, d};
    var x{A, A} >= 0;
    minimize obj: sum{i in A, j in A} x[i, j];
    subject to c: x[a, a] >= 1;
    """
    # 16 grounded variables exceed a budget of 10 — must refuse, not expand
    with pytest.raises(JModelError, match="grounded elements"):
        compile_jmodel(src, max_grounded_elements=10)
    # and the identical source compiles fine under the default budget
    assert len(compile_jmodel(src).variables) == 16


def test_deep_nesting_rejected_with_structured_error():
    depth = 300
    src = "var x >= 0; minimize obj: " + "(" * depth + "x" + ")" * depth + "; subject to c: x >= 1;"
    # a raw RecursionError here used to escape as a 500 from /dsl/compile
    with pytest.raises(JModelError, match="nesting"):
        compile_jmodel(src)


def test_grounding_error_position_is_exact():
    src = "var x >= 0;\nminimize obj: x + qq;\nsubject to c: x >= 1;"
    with pytest.raises(JModelError) as exc:
        compile_jmodel(src)
    assert exc.value.position == src.index("qq")


# --------------------------------------------------------------------------- #
# Datasets (§8 Scenarios) — declaration-only sets/params + JModelData
# --------------------------------------------------------------------------- #

# The KNAPSACK model with its structure and data separated: same optimization
# problem, values supplied by a dataset instead of inline `:=` bodies.
PARAMETRIC_KNAPSACK = """
set ITEMS;
param value{ITEMS};
param weight{ITEMS};
param cap;
var take{ITEMS} binary;
maximize total_value:
    sum{i in ITEMS} value[i] * take[i];
subject to capacity:
    sum{i in ITEMS} weight[i] * take[i] <= cap;
"""

KNAPSACK_DATA = {
    "sets": {"ITEMS": ["a", "b", "c", "d"]},
    "params": {
        "value": {"a": 60, "b": 100, "c": 120, "d": 40},
        "weight": {"a": 10, "b": 20, "c": 30, "d": 15},
        "cap": 50,
    },
}


def test_parametric_model_with_dataset_lowers_identically_to_inline():
    # The strongest equivalence proof available: structure+dataset must produce the
    # exact same flat problem as the classic inline model, byte for byte.
    data = JModelData.from_json(KNAPSACK_DATA)
    parametric = compile_jmodel(PARAMETRIC_KNAPSACK, data=data).model_dump()
    inline = compile_jmodel(KNAPSACK).model_dump()
    assert parametric == inline


def test_dataset_compile_is_deterministic():
    data = JModelData.from_json(KNAPSACK_DATA)
    a = compile_jmodel(PARAMETRIC_KNAPSACK, data=data).model_dump()
    b = compile_jmodel(PARAMETRIC_KNAPSACK, data=data).model_dump()
    assert a == b


def test_declaration_only_model_without_dataset_names_the_missing_symbol():
    with pytest.raises(JModelError, match="set 'ITEMS' has no members"):
        compile_jmodel(PARAMETRIC_KNAPSACK)


def test_declaration_only_param_without_dataset_names_the_missing_symbol():
    src = """
    set I := {a, b};
    param w{I};
    var x{I} binary;
    maximize obj: sum{i in I} w[i] * x[i];
    subject to c: sum{i in I} x[i] <= 1;
    """
    with pytest.raises(JModelError, match="param 'w' has no values") as exc:
        compile_jmodel(src)
    assert exc.value.position == src.index("param w") + len("param ")


def test_dataset_overrides_an_inline_default_whole_symbol():
    # A scenario can replace an inline `:=` default; the replace is whole-symbol.
    data = JModelData.from_json({"params": {"cap": 30}})
    prob = compile_jmodel(KNAPSACK, data=data)
    assert prob.constraints[0].expression.endswith("<= 30")


def test_dataset_partial_indexed_override_fails_on_the_missing_key():
    # Whole-symbol replace: providing 1 of 4 keys leaves the other 3 undefined —
    # a per-key merge with the inline values must NOT happen silently.
    data = JModelData.from_json({"params": {"value": {"a": 1}}})
    with pytest.raises(JModelError, match="has no value for index"):
        compile_jmodel(KNAPSACK, data=data)


def test_dataset_unknown_symbols_rejected():
    with pytest.raises(JModelError, match="unknown param 'capp'"):
        compile_jmodel(KNAPSACK, data=JModelData.from_json({"params": {"capp": 1}}))
    with pytest.raises(JModelError, match="unknown set 'X'"):
        compile_jmodel(KNAPSACK, data=JModelData.from_json({"sets": {"X": ["a"]}}))


def test_dataset_composite_keys_ground_a_two_dim_param():
    src = """
    set W := {A, B};
    set T := {1, 2};
    param cost{W, T};
    var assign{W, T} binary;
    minimize obj: sum{w in W, t in T} cost[w, t] * assign[w, t];
    subject to one{t in T}: sum{w in W} assign[w, t] == 1;
    """
    data = JModelData.from_json(
        # " A, 1" exercises the documented whitespace tolerance around members.
        {"params": {"cost": {"A,1": 9, " A, 2": 2, "B,1": 6, "B,2": 4}}}
    )
    prob = compile_jmodel(src, data=data)
    assert prob.objective.expression == (
        "9*assign_A_1 + 2*assign_A_2 + 6*assign_B_1 + 4*assign_B_2"
    )


def test_dataset_key_arity_and_shape_mismatches_rejected():
    two_dim = """
    set W := {A};
    set T := {1};
    param cost{W, T};
    var x{W, T} binary;
    minimize obj: sum{w in W, t in T} cost[w, t] * x[w, t];
    subject to c: x[A, 1] <= 1;
    """
    with pytest.raises(JModelError, match="expected 2"):
        compile_jmodel(two_dim, data=JModelData.from_json({"params": {"cost": {"A": 5}}}))
    with pytest.raises(JModelError, match="is indexed over 2"):
        compile_jmodel(two_dim, data=JModelData.from_json({"params": {"cost": 5}}))
    with pytest.raises(JModelError, match="is scalar"):
        compile_jmodel(KNAPSACK, data=JModelData.from_json({"params": {"cap": {"a": 1}}}))


def test_dataset_key_member_must_belong_to_the_index_set():
    data = JModelData.from_json(
        {
            "sets": {"ITEMS": ["a", "b"]},
            "params": {
                "value": {"a": 1, "zz": 2},
                "weight": {"a": 1, "b": 1},
                "cap": 5,
            },
        }
    )
    with pytest.raises(JModelError, match="'zz'"):
        compile_jmodel(PARAMETRIC_KNAPSACK, data=data)


def test_dataset_empty_set_grounds_to_zero_variables_and_is_a_clear_error():
    data = JModelData.from_json(
        {"sets": {"ITEMS": []}, "params": {"value": {}, "weight": {}, "cap": 5}}
    )
    with pytest.raises(JModelError, match="zero variables"):
        compile_jmodel(PARAMETRIC_KNAPSACK, data=data)


def test_dataset_integer_members_normalize_to_strings():
    src = """
    set T;
    var x{T} binary;
    maximize obj: sum{t in T} x[t];
    subject to c: sum{t in T} x[t] <= 1;
    """
    prob = compile_jmodel(src, data=JModelData.from_json({"sets": {"T": [1, 2]}}))
    assert [v.name for v in prob.variables] == ["x_1", "x_2"]


def test_from_json_shape_violations_are_structured_errors():
    for payload, pattern in [
        ([], "must be a JSON object"),
        ({"sets": {}, "bogus": {}}, "unknown top-level"),
        ({"sets": []}, "'sets' must be an object"),
        ({"sets": {"I": "abc"}}, "must be a list"),
        ({"sets": {"I": [""]}}, "empty member"),
        ({"sets": {"I": ["a,b"]}}, "contains a comma"),
        ({"sets": {"I": [True]}}, "boolean member"),
        ({"sets": {"I": [1.5]}}, "strings or integers"),
        ({"params": []}, "'params' must be an object"),
        ({"params": {"w": True}}, "not a boolean"),
        ({"params": {"w": "5"}}, "number .scalar. or an object"),
        ({"params": {"w": {"a": "x"}}}, "must be numbers"),
        ({"params": {"w": {"a": float("nan")}}}, "non-finite"),
        ({"params": {"w": {1: 2}}}, "keys must be strings"),
        ({"params": {"w": {"a,": 1}}}, "empty index member"),
        ({"params": {"w": {"A,1": 1, "A, 1": 2}}}, "duplicate entries"),
        ({"sets": {"I": ["a", "a"]}}, None),  # duplicate members surface at compile
    ]:
        if pattern is None:
            data = JModelData.from_json(payload)
            with pytest.raises(JModelError, match="duplicate members"):
                compile_jmodel(
                    "set I;\nvar x{I} binary;\nmaximize o: sum{i in I} x[i];\n"
                    "subject to c: sum{i in I} x[i] <= 1;",
                    data=data,
                )
        else:
            with pytest.raises(JModelError, match=pattern):
                JModelData.from_json(payload)
