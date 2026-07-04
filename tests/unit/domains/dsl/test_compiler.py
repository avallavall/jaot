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
        compile_jmodel("param p{J} := a 1; var x >= 0; minimize obj: x; subject to c: x >= 1;")


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
        ({"sets": {"I": ["a,"]}}, "empty component"),
        ({"sets": {"I": ["a,b", "c"]}}, "different dimensions"),
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


# ---------------------------------------------------------------------------
# S2a — inspect_declarations (parse-only, powers /dsl/inspect)
# ---------------------------------------------------------------------------


def test_inspect_declaration_only_symbols():
    from app.domains.dsl import inspect_declarations

    decls = inspect_declarations(
        "set I;\nparam w{I};\nparam cap;\nvar x{I} binary;\n"
        "maximize obj: sum{i in I} w[i] * x[i];\n"
        "subject to c: sum{i in I} x[i] <= cap;"
    )
    assert [(s.name, s.has_inline_values) for s in decls.sets] == [("I", False)]
    by_name = {p.name: p for p in decls.params}
    assert by_name["w"].index_sets == ("I",)
    assert by_name["w"].arity == 1
    assert by_name["w"].has_inline_values is False
    assert by_name["cap"].index_sets == ()
    assert by_name["cap"].arity == 0


def test_inspect_marks_inline_values_and_multi_arity():
    from app.domains.dsl import inspect_declarations

    decls = inspect_declarations(
        "set I := {a, b};\nset J := {p, q};\nparam c{I, J} := a p 1, a q 2, b p 3, b q 4;\n"
        "var x{I, J} binary;\nmaximize obj: sum{i in I, j in J} c[i, j] * x[i, j];\n"
        "subject to one: sum{i in I, j in J} x[i, j] <= 2;"
    )
    assert all(s.has_inline_values for s in decls.sets)
    (param,) = decls.params
    assert param.index_sets == ("I", "J")
    assert param.arity == 2
    assert param.has_inline_values is True


def test_inspect_never_grounds():
    from app.domains.dsl import inspect_declarations

    # compile_jmodel on this source raises (set has no members); inspect must not.
    src = (
        "set I;\nparam w{I};\nvar x{I} binary;\n"
        "maximize obj: sum{i in I} w[i] * x[i];\n"
        "subject to c: sum{i in I} x[i] <= 1;"
    )
    with pytest.raises(JModelError):
        compile_jmodel(src)
    decls = inspect_declarations(src)
    assert decls.sets[0].name == "I"


def test_inspect_raises_on_parse_error():
    from app.domains.dsl import inspect_declarations

    with pytest.raises(JModelError) as exc_info:
        inspect_declarations("set S := {a, b}\nvar x >= 0;")
    assert exc_info.value.position is not None


# --------------------------------------------------------------------------- #
# Tuple sets (S6 / DSL-expressivity #3)
# --------------------------------------------------------------------------- #

SPARSE_PATH = """
set ARCS := {(a, b), (b, c), (a, c)};
param w{ARCS} := a b 1, b c 2, a c 4;
var use{ARCS} binary;
minimize total: sum{(i, j) in ARCS} w[i, j] * use[i, j];
subject to reach_c: sum{(i, j) in ARCS : j == c} use[i, j] >= 1;
subject to chain{(i, j) in ARCS : j != c}: use[i, j] <= 1;
"""


def test_tuple_set_inline_lowering_is_sparse():
    prob = compile_jmodel(SPARSE_PATH)

    # only the 3 declared arcs expand — never the 9-member cartesian closure
    assert [v.name for v in prob.variables] == ["use_a_b", "use_b_c", "use_a_c"]
    assert prob.objective.expression == "use_a_b + 2*use_b_c + 4*use_a_c"
    by_name = {c.name: c.expression for c in prob.constraints}
    assert by_name["reach_c"] == "use_b_c + use_a_c >= 1"
    # the constraint family grounds one row per matching tuple, named by components
    assert by_name["chain_a_b"] == "use_a_b <= 1"
    assert "chain_b_c" not in by_name


def test_tuple_set_solves_to_known_optimum():
    from app.domains.solver.adapters.scip import SCIPAdapter

    result = SCIPAdapter().solve(compile_jmodel(SPARSE_PATH))
    assert result.status.value == "optimal"
    assert result.objective_value is not None
    assert abs(result.objective_value - 2.0) < 1e-6  # cheapest way to reach c is b->c


def test_tuple_set_lowering_is_deterministic():
    assert compile_jmodel(SPARSE_PATH).model_dump() == compile_jmodel(SPARSE_PATH).model_dump()


def test_tuple_set_from_dataset_with_composite_members():
    src = """
    set ARCS dimen 2;
    param w{ARCS};
    var use{ARCS} binary;
    minimize total: sum{(i, j) in ARCS} w[i, j] * use[i, j];
    subject to pick_all{(i, j) in ARCS}: use[i, j] >= 1;
    """
    data = JModelData.from_json(
        {"sets": {"ARCS": ["a,b", "b,c"]}, "params": {"w": {"a,b": 3, "b,c": 5}}}
    )
    prob = compile_jmodel(src, data=data)
    assert [v.name for v in prob.variables] == ["use_a_b", "use_b_c"]
    assert prob.objective.expression == "3*use_a_b + 5*use_b_c"


def test_declaration_only_tuple_set_defaults_to_dimen_1():
    src = """
    set ARCS;
    var use{ARCS} binary;
    minimize total: sum{a in ARCS} use[a];
    subject to c: sum{a in ARCS} use[a] <= 1;
    """
    with pytest.raises(JModelError, match="dimen 2"):
        compile_jmodel(src, data=JModelData.from_json({"sets": {"ARCS": ["a,b"]}}))


def test_mixed_arity_set_literal_rejected():
    with pytest.raises(JModelError, match="different dimensions"):
        compile_jmodel(
            "set A := {(a, b), c};\nvar x{A} binary;\n"
            "minimize o: sum{(i, j) in A} x[i, j];\nsubject to c1: x[a, b] <= 1;"
        )


def test_dimen_contradicting_inline_literal_rejected():
    with pytest.raises(JModelError, match="declares dimen 3"):
        compile_jmodel(
            "set A dimen 3 := {(a, b)};\nvar x{A} binary;\n"
            "minimize o: sum{(i, j) in A} x[i, j];\nsubject to c1: x[a, b] <= 1;"
        )


def test_binding_arity_must_match_set_dimension():
    src = """
    set ARCS := {(a, b)};
    var use{ARCS} binary;
    minimize total: sum{i in ARCS} use[i];
    subject to c: use[a, b] <= 1;
    """
    with pytest.raises(JModelError, match="2-dimensional"):
        compile_jmodel(src)


def test_duplicate_index_in_one_qualifier_rejected():
    src = """
    set ARCS := {(a, b)};
    var use{ARCS} binary;
    minimize total: sum{(i, i) in ARCS} use[i, i];
    subject to c: use[a, b] <= 1;
    """
    with pytest.raises(JModelError, match="bound more than once"):
        compile_jmodel(src)


def test_reference_outside_tuple_set_is_a_ghost_error():
    src = """
    set ARCS := {(a, b), (b, c)};
    var use{ARCS} binary;
    minimize total: sum{(i, j) in ARCS} use[i, j];
    subject to c: use[a, c] <= 1;
    """
    # (a, c) is not a member — must never emit a ghost flat variable use_a_c
    with pytest.raises(JModelError, match="not a member of set 'ARCS'"):
        compile_jmodel(src)


def test_var_over_tuple_set_takes_flat_subscripts():
    src = """
    set ARCS := {(a, b)};
    set K := {1, 2};
    var x{ARCS, K} binary;
    minimize total: sum{(i, j) in ARCS, k in K} x[i, j, k];
    subject to c: x[a, b] <= 1;
    """
    with pytest.raises(JModelError, match="expected 3"):
        compile_jmodel(src)


def test_param_key_flat_arity_validated_against_tuple_sets():
    src = """
    set ARCS dimen 2;
    param w{ARCS};
    var use{ARCS} binary;
    minimize total: sum{(i, j) in ARCS} w[i, j] * use[i, j];
    subject to c{(i, j) in ARCS}: use[i, j] <= 1;
    """
    data = JModelData.from_json({"sets": {"ARCS": ["a,b"]}, "params": {"w": {"a": 1}}})
    with pytest.raises(JModelError, match="expected 2"):
        compile_jmodel(src, data=data)


def test_equality_filter_slices_instead_of_scanning_the_whole_set():
    # 20 arcs fan out of 20 sources; each per-source constraint row must consume
    # budget for ITS matching arcs only. A full-scan grounding would need
    # ~20 rows x 40 arcs = 800+ elements; the sliced one stays under 200.
    out_arcs = ", ".join(f"(s{i}, t{i % 2})" for i in range(20))
    in_arcs = ", ".join(f"(t{i % 2}, u{i})" for i in range(20))
    sources = ", ".join(f"s{i}" for i in range(20))
    src = (
        "set ARCS := {" + out_arcs + ", " + in_arcs + "};\n"
        "set SOURCES := {" + sources + "};\n"
        "var use{ARCS} binary;\n"
        "minimize total: sum{(i, j) in ARCS} use[i, j];\n"
        "subject to out_once{s in SOURCES}:\n"
        "    sum{(i, j) in ARCS : i == s} use[i, j] <= 1;\n"
    )
    prob = compile_jmodel(src, max_grounded_elements=200)
    assert len(prob.variables) == 40
    names = {c.name for c in prob.constraints}
    assert "out_once_s0" in names and len(names) == 20


def test_sliced_equality_keeps_numeric_equality_semantics():
    # _compare treats "1" == "1.0" as equal (numeric-first); the slice index must too
    src = """
    set ARCS := {(1, a), (2, b)};
    var use{ARCS} binary;
    minimize total: sum{(i, j) in ARCS} use[i, j];
    subject to c: sum{(i, j) in ARCS : i == 1.0} use[i, j] >= 1;
    """
    prob = compile_jmodel(src)
    assert {c.name: c.expression for c in prob.constraints}["c"] == "use_1_a >= 1"


def test_filter_between_indices_of_same_binding_stays_a_compare():
    src = """
    set PAIRS := {(a, a), (a, b), (b, b)};
    var pick{PAIRS} binary;
    minimize total: sum{(i, j) in PAIRS} pick[i, j];
    subject to no_diag: sum{(i, j) in PAIRS : i == j} pick[i, j] <= 1;
    """
    prob = compile_jmodel(src)
    assert {c.name: c.expression for c in prob.constraints}["no_diag"] == (
        "pick_a_a + pick_b_b <= 1"
    )


def test_cross_binding_equality_slices_on_the_later_binding():
    src = """
    set NODES := {a, b};
    set ARCS := {(a, b), (b, a)};
    var use{ARCS} binary;
    minimize total: sum{(i, j) in ARCS} use[i, j];
    subject to into{n in NODES}:
        sum{(i, j) in ARCS : j == n} use[i, j] == 1;
    """
    prob = compile_jmodel(src)
    by_name = {c.name: c.expression for c in prob.constraints}
    assert by_name["into_a"] == "use_b_a == 1"
    assert by_name["into_b"] == "use_a_b == 1"


def test_inline_param_greedy_entries_over_tuple_set():
    src = """
    set ARCS := {(a, b), (b, c)};
    param w{ARCS} := a b 1.5, b c -2;
    var use{ARCS} binary;
    minimize total: sum{(i, j) in ARCS} w[i, j] * use[i, j];
    subject to c{(i, j) in ARCS}: use[i, j] <= 1;
    """
    prob = compile_jmodel(src)
    assert prob.objective.expression == "1.5*use_a_b - 2*use_b_c"


def test_inline_param_entry_must_end_in_a_number():
    with pytest.raises(JModelError, match="end in a numeric value"):
        compile_jmodel(
            "set I := {a};\nparam w{I} := a b;\nvar x{I} binary;\n"
            "minimize o: sum{i in I} w[i]*x[i];\nsubject to c: x[a] <= 1;"
        )


def test_inline_param_duplicate_key_rejected():
    with pytest.raises(JModelError, match="duplicate entries"):
        compile_jmodel(
            "set I := {a};\nparam w{I} := a 1, a 2;\nvar x{I} binary;\n"
            "minimize o: sum{i in I} w[i]*x[i];\nsubject to c: x[a] <= 1;"
        )


def test_inline_param_negative_key_member_rejected():
    with pytest.raises(JModelError, match="cannot be negative"):
        compile_jmodel(
            "set I := {1};\nparam w{I, I} := -1 1 5;\nvar x{I} binary;\n"
            "minimize o: sum{i in I} w[i, i]*x[i];\nsubject to c: x[1] <= 1;"
        )


def test_tuple_binding_of_one_index_rejected():
    with pytest.raises(JModelError, match="at least two indices"):
        compile_jmodel(
            "set I := {a};\nvar x{I} binary;\nminimize o: sum{(i) in I} x[i];\n"
            "subject to c: x[a] <= 1;"
        )


def test_tuple_literal_of_one_component_rejected():
    with pytest.raises(JModelError, match="at least two components"):
        compile_jmodel(
            "set I := {(a)};\nvar x{I} binary;\nminimize o: sum{i in I} x[i];\n"
            "subject to c: x[a] <= 1;"
        )


def test_inspect_reports_flat_arity_over_tuple_sets():
    from app.domains.dsl import inspect_declarations

    decls = inspect_declarations(
        "set ARCS dimen 2;\nset K;\nparam d{ARCS, K};\nvar x{ARCS, K} binary;\n"
        "minimize o: sum{(i, j) in ARCS, k in K} d[i, j, k] * x[i, j, k];\n"
        "subject to c{k in K}: sum{(i, j) in ARCS} x[i, j, k] <= 1;"
    )
    (param,) = decls.params
    assert param.index_sets == ("ARCS", "K")
    assert param.arity == 3


# --------------------------------------------------------------------------- #
# Ranges (DSL-expressivity #2) — `set T := 1..N;`
# --------------------------------------------------------------------------- #


def test_range_set_lowers_like_the_equivalent_brace_literal():
    range_form = compile_jmodel(
        "set T := 1..4;\nvar x{T} binary;\nmaximize o: sum{t in T} x[t];\n"
        "subject to c: sum{t in T} x[t] <= 2;"
    )
    brace_form = compile_jmodel(
        "set T := {1, 2, 3, 4};\nvar x{T} binary;\nmaximize o: sum{t in T} x[t];\n"
        "subject to c: sum{t in T} x[t] <= 2;"
    )
    assert range_form.model_dump() == brace_form.model_dump()
    assert [v.name for v in range_form.variables] == ["x_1", "x_2", "x_3", "x_4"]


def test_range_members_work_in_filters_and_params():
    prob = compile_jmodel(
        """
        set T := 1..5;
        param w{T} := 1 10, 2 20, 3 30, 4 40, 5 50;
        var x{T} binary;
        minimize o: sum{t in T : t >= 4} w[t] * x[t];
        subject to c: x[1] + x[5] >= 1;
        """
    )
    assert prob.objective.expression == "40*x_4 + 50*x_5"
    assert prob.constraints[0].expression == "x_1 + x_5 >= 1"


def test_range_with_negative_endpoints():
    prob = compile_jmodel(
        "set T := -2..1;\nvar x{T} binary;\nminimize o: sum{t in T} x[t];\n"
        "subject to c: sum{t in T} x[t] >= 1;"
    )
    assert len(prob.variables) == 4  # -2, -1, 0, 1


def test_range_single_member_when_endpoints_equal():
    prob = compile_jmodel(
        "set T := 7..7;\nvar x{T} binary;\nminimize o: x[7];\nsubject to c: x[7] <= 1;"
    )
    assert [v.name for v in prob.variables] == ["x_7"]


def test_descending_range_rejected():
    with pytest.raises(JModelError, match="is empty"):
        compile_jmodel("set T := 5..1;\nvar x{T} binary;\nminimize o: sum{t in T} x[t];")


def test_range_endpoints_must_be_integers():
    with pytest.raises(JModelError, match="must be integer literals"):
        compile_jmodel("set T := 1.5..3;\nvar x{T} binary;\nminimize o: sum{t in T} x[t];")
    with pytest.raises(JModelError, match="must be integer literals"):
        compile_jmodel("set T := 1..n;\nvar x{T} binary;\nminimize o: sum{t in T} x[t];")


def test_range_beyond_budget_rejected():
    with pytest.raises(JModelError, match="grounded-element budget"):
        compile_jmodel(
            "set T := 1..99999999;\nvar x{T} binary;\nminimize o: sum{t in T} x[t];"
        )


def test_range_set_body_must_be_braces_or_range():
    with pytest.raises(JModelError, match="set literal .* or an integer range"):
        compile_jmodel("set T := abc;\nvar x binary;\nminimize o: x;")


def test_range_contradicting_declared_dimen_rejected():
    with pytest.raises(JModelError, match="dimen 2"):
        compile_jmodel(
            "set T dimen 2 := 1..3;\nvar x{T} binary;\nminimize o: sum{(i, j) in T} x[i, j];"
        )


def test_range_set_solves_to_known_optimum():
    from app.domains.solver.adapters.scip import SCIPAdapter

    # pick the 2 cheapest of periods 1..4: 1 (cost 1) and 2 (cost 2) -> 3
    result = SCIPAdapter().solve(
        compile_jmodel(
            """
            set T := 1..4;
            param cost{T} := 1 1, 2 2, 3 3, 4 4;
            var pick{T} binary;
            minimize total: sum{t in T} cost[t] * pick[t];
            subject to need_two: sum{t in T} pick[t] == 2;
            """
        )
    )
    assert result.status.value == "optimal"
    assert result.objective_value is not None
    assert abs(result.objective_value - 3.0) < 1e-6
