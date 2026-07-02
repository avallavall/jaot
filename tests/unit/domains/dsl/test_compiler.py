"""Unit tests for the JModel DSL compiler (P5).

Covers deterministic lowering of three real models, structural assertions on the
emitted flat OptimizationProblem, a real SCIP solve to the known optima, and the
error paths. Grammar: ``.claude/plans/jmodel-grammar-2026-07-01.md``.
"""

import pytest

from app.domains.dsl import JModelError, compile_jmodel
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
    with pytest.raises(JModelError, match="duplicate variable"):
        compile_jmodel("var x >= 0; var x >= 0; minimize obj: x; subject to c: x >= 1;")


def test_constraint_requires_relational_operator():
    with pytest.raises(JModelError, match="relational operator"):
        compile_jmodel("var x >= 0; minimize obj: x; subject to c: x + 1;")
