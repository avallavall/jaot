"""Unit tests for the flat → JModel de-grounder (B2, phase 1).

The de-grounder reconstructs a compact indexed JModel from a flat problem and
only returns it when it VERIFIABLY round-trips (recompiles to an equivalent
problem). These tests drive real flat problems (produced by compiling a JModel,
then discarding the source) through it and assert both the recovered structure
and the honesty gate — models with no recoverable structure return ``None``.
"""

import pytest

from app.domains.dsl import compile_jmodel
from app.services.jmodel_deground import deground_problem

pytestmark = pytest.mark.unit


def _flat(src: str):
    """Compile a JModel then strip the source: a flat problem with no lineage."""
    return compile_jmodel(src)


def _recompiles_equivalent(draft: str, original) -> bool:
    """The draft compiles and matches the original's variables / objective / #constraints."""
    rebuilt = compile_jmodel(draft)
    same_vars = {v.name for v in rebuilt.variables} == {v.name for v in original.variables}
    same_sense = rebuilt.objective.sense == original.objective.sense
    same_count = len(rebuilt.constraints) == len(original.constraints)
    return same_vars and same_sense and same_count


ASSIGNMENT = """
set W := {A, B, C}; set T := {1, 2, 3};
param cost{W, T} := A 1 9, A 2 2, A 3 7, B 1 6, B 2 4, B 3 3, C 1 5, C 2 8, C 3 1;
var assign{W, T} binary;
minimize total: sum{w in W, t in T} cost[w, t] * assign[w, t];
subject to one_task{w in W}: sum{t in T} assign[w, t] == 1;
subject to one_worker{t in T}: sum{w in W} assign[w, t] == 1;
"""


def test_assignment_degrounds_to_compact_indexed_model():
    problem = _flat(ASSIGNMENT)
    draft = deground_problem(problem)
    assert draft is not None
    # Sets, an indexed var family, a sum objective and TWO ∀-quantified families.
    assert "set S1 := {A, B, C};" in draft
    assert "var assign{S1, S2} binary;" in draft
    assert "sum{i in S1, j in S2}" in draft
    assert draft.count("subject to") == 2
    assert "{i in S1}" in draft and "{j in S2}" in draft
    assert _recompiles_equivalent(draft, problem)


def test_assignment_draft_is_marked_a_draft():
    draft = deground_problem(_flat(ASSIGNMENT))
    assert draft is not None
    assert draft.splitlines()[0].startswith("#")


KNAPSACK = """
set ITEMS := {a, b, c, d};
param value{ITEMS} := a 60, b 100, c 120, d 40;
param weight{ITEMS} := a 10, b 20, c 30, d 15;
param cap := 50;
var take{ITEMS} binary;
maximize total: sum{i in ITEMS} value[i] * take[i];
subject to capacity: sum{i in ITEMS} weight[i] * take[i] <= cap;
"""


def test_knapsack_recovers_coefficient_params():
    problem = _flat(KNAPSACK)
    draft = deground_problem(problem)
    assert draft is not None
    # A single family, a value param in the objective and a weight param in the
    # capacity constraint (a scalar constraint keeps its literal rhs).
    assert "var take{S1} binary;" in draft
    assert "maximize obj:" in draft
    assert "<= 50" in draft
    assert _recompiles_equivalent(draft, problem)


TRANSPORT = """
set S := {s1, s2}; set D := {d1, d2, d3};
param supply{S} := s1 10, s2 20;
param demand{D} := d1 5, d2 12, d3 13;
param c{S, D} := s1 d1 1, s1 d2 2, s1 d3 3, s2 d1 4, s2 d2 5, s2 d3 6;
var x{S, D} >= 0;
minimize total: sum{s in S, d in D} c[s, d] * x[s, d];
subject to sup{s in S}: sum{d in D} x[s, d] <= supply[s];
subject to dem{d in D}: sum{s in S} x[s, d] >= demand[d];
"""


def test_transport_recovers_per_family_rhs_params():
    problem = _flat(TRANSPORT)
    draft = deground_problem(problem)
    assert draft is not None
    # A varying rhs across a constraint family becomes a param indexed by the free set.
    assert "r_c1[i]" in draft or "r_c2[j]" in draft
    assert draft.count("subject to") == 2
    assert _recompiles_equivalent(draft, problem)


def test_per_element_constraint_needs_no_sum():
    problem = _flat(
        "set I := {a, b};\n"
        "param p{I} := a 2, b 3;\n"
        "var x{I} binary;\n"
        "minimize obj: sum{i in I} p[i] * x[i];\n"
        "subject to cap{i in I}: x[i] <= 1;\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    # `x[i] <= 1 ∀ i` has no inner sum.
    assert "subject to c1{i in S1}: x[i] <= 1;" in draft
    assert _recompiles_equivalent(draft, problem)


def test_family_plus_scalar_variable():
    problem = _flat(
        "set I := {a, b};\n"
        "param p{I} := a 2, b 3;\n"
        "var x{I} binary;\n"
        "var y >= 0;\n"
        "minimize obj: sum{i in I} p[i] * x[i] + 5 * y;\n"
        "subject to c{i in I}: x[i] <= 1;\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "var y >= 0;" in draft
    assert "5 * y" in draft
    assert _recompiles_equivalent(draft, problem)


def test_unit_coefficient_objective_has_no_param():
    problem = _flat(
        "set I := {a, b, c};\n"
        "var x{I} binary;\n"
        "maximize obj: sum{i in I} x[i];\n"
        "subject to pick: sum{i in I} x[i] <= 2;\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "maximize obj: sum{i in S1} x[i];" in draft
    assert "param" not in draft  # unit coefficients need no coefficient table
    assert _recompiles_equivalent(draft, problem)


def test_negative_and_fractional_coefficients_round_trip():
    problem = _flat(
        "set I := {a, b, c};\n"
        "param p{I} := a -3, b 2.5, c 1;\n"
        "var x{I} >= 0 <= 10;\n"
        "minimize obj: sum{i in I} p[i] * x[i];\n"
        "subject to c{i in I}: x[i] <= 5;\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "-3" in draft and "2.5" in draft
    assert _recompiles_equivalent(draft, problem)


# --------------------------------------------------------------------------- #
# Multi-family constraints — the real hairball (assignment + a linking family)
# --------------------------------------------------------------------------- #

# One constraint touching TWO families with a SHARED free index — the exact shape
# the big TFM scenarios use (`sum_i a[i,j] + z[j] == 1  ∀ j`) that used to decline.
MULTI_FAMILY = """
set I := {1, 2, 3}; set J := {a, b};
param cost{I, J} := 1 a 5, 1 b 3, 2 a 4, 2 b 6, 3 a 7, 3 b 2;
var x{I, J} binary;
var z{J} binary;
minimize obj: sum{i in I, j in J} cost[i, j] * x[i, j];
subject to link{j in J}: sum{i in I} x[i, j] + z[j] == 1;
subject to cover{i in I}: sum{j in J} x[i, j] <= 1;
"""


def test_multi_family_constraint_is_recovered_compactly():
    problem = _flat(MULTI_FAMILY)
    draft = deground_problem(problem)
    assert draft is not None
    # Both families are declared and BOTH appear in one ∀-quantified constraint,
    # sharing the free index — not flattened, not declined.
    assert "var x{" in draft and "var z{" in draft
    assert "sum{" in draft
    assert draft.count("subject to") == 2
    # The multi-family link constraint keeps both x and z under a single ∀.
    link = next(ln for ln in draft.splitlines() if "z[" in ln and "subject to" in ln)
    assert "x[" in link and "z[" in link and "∀" not in link  # ascii source
    assert _recompiles_equivalent(draft, problem)


def test_flat_numeric_multi_family_scenario_round_trips():
    """A flat problem (numeric names, no compiler lineage) mirroring scenario_NxN:
    a family ``a`` over I×J plus a linking family ``z`` over J, with the mixed
    constraint ``sum_i a[i,j] + z[j] == 1``. Recovered via the numeric-name parse."""
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    n_i, n_j = 3, 2
    variables = [
        Variable(name=f"a_{i}_{j}", type=VariableType.BINARY)
        for i in range(1, n_i + 1)
        for j in range(1, n_j + 1)
    ] + [Variable(name=f"z_{j}", type=VariableType.BINARY) for j in range(1, n_j + 1)]
    objective = Objective(
        sense=ObjectiveSense.MAXIMIZE,
        expression=" + ".join(f"a_{i}_{j}" for i in range(1, n_i + 1) for j in range(1, n_j + 1)),
    )
    constraints = [
        Constraint(
            name=f"link_{j}",
            expression=" + ".join(f"a_{i}_{j}" for i in range(1, n_i + 1)) + f" + z_{j} == 1",
        )
        for j in range(1, n_j + 1)
    ]
    problem = OptimizationProblem(variables=variables, objective=objective, constraints=constraints)
    draft = deground_problem(problem)
    assert draft is not None
    assert "sum{" in draft  # compacted (a scalar fallback would have no sum)
    assert draft.count("subject to") == 1  # the 2 flat link constraints → one ∀ family
    assert _recompiles_equivalent(draft, problem)


def test_multi_family_with_varying_coefficients_and_rhs():
    """A mixed constraint whose coefficients AND rhs vary by the free index becomes
    coefficient params + an rhs param — still round-trips."""
    problem = _flat(
        "set I := {1, 2}; set J := {p, q};\n"
        "param w{I, J} := 1 p 2, 1 q 3, 2 p 4, 2 q 5;\n"
        "param cap{J} := p 10, q 20;\n"
        "var x{I, J} >= 0;\n"
        "var y{J} >= 0;\n"
        "minimize obj: sum{i in I, j in J} x[i, j];\n"
        "subject to bal{j in J}: sum{i in I} w[i, j] * x[i, j] + y[j] <= cap[j];\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "sum{" in draft
    assert _recompiles_equivalent(draft, problem)


# --------------------------------------------------------------------------- #
# The honesty gate — decline rather than fake a structure
# --------------------------------------------------------------------------- #


def test_small_scalar_model_gets_a_flat_jmodel():
    """A small model with no indexed families still de-grounds — as a scalar JModel."""
    problem = _flat(
        "var x >= 0;\nvar y >= 0;\nminimize obj: 3 * x + 2 * y;\nsubject to c: x + y <= 10;"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "var x >= 0;" in draft and "var y >= 0;" in draft
    assert "minimize obj:" in draft
    assert _recompiles_equivalent(draft, problem)


def test_small_binary_scalar_model_round_trips():
    """Binary vars carry no explicit bounds in a flat model but [0,1] when recompiled —
    the round-trip must treat those as equal (regression: used to decline)."""
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    problem = OptimizationProblem(
        variables=[
            Variable(name="pick_a", type=VariableType.BINARY),  # lower/upper left None
            Variable(name="pick_b", type=VariableType.BINARY),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="3*pick_a + 2*pick_b"),
        constraints=[Constraint(name="cap", expression="pick_a + pick_b <= 1")],
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "var pick_a binary;" in draft
    assert _recompiles_equivalent(draft, problem)


def test_large_flat_model_without_families_declines():
    """A big flat model has no compact form; a scalar dump would be a wall, so decline."""
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    # 80 scalar vars (no recoverable family) — past the scalar-fallback limit.
    variables = [Variable(name=f"col{i}", type=VariableType.CONTINUOUS) for i in range(80)]
    problem = OptimizationProblem(
        variables=variables,
        objective=Objective(
            sense=ObjectiveSense.MINIMIZE, expression=" + ".join(v.name for v in variables)
        ),
        constraints=[Constraint(name="c", expression=variables[0].name + " >= 1")],
    )
    assert deground_problem(problem) is None


def test_sparse_numeric_family_is_not_falsely_compacted():
    """A flat family whose numeric indices are not a full cartesian block must never
    become a dense ``var x{S1, S2}`` (that would invent the missing variable).

    ``x_1_1, x_1_2, x_2_1`` (no ``x_2_2``) is 2×2 minus one member: the compact path
    declines, and a small model falls back to a scalar JModel that round-trips.
    """
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    problem = OptimizationProblem(
        variables=[
            Variable(name="x_1_1", type=VariableType.BINARY),
            Variable(name="x_1_2", type=VariableType.BINARY),
            Variable(name="x_2_1", type=VariableType.BINARY),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x_1_1 + x_1_2 + x_2_1"),
        constraints=[Constraint(name="c", expression="x_1_1 + x_1_2 + x_2_1 <= 2")],
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "var x{" not in draft  # never falsely compacted into a dense family
    assert _recompiles_equivalent(draft, problem)


def test_tuple_set_family_degrounds_as_one_dimensional():
    """A tuple-set family (joined index labels) is a valid dense 1-D family."""
    problem = _flat(
        "set ARCS := {(a, b), (b, c)};\n"
        "var f{ARCS} >= 0;\n"
        "minimize obj: sum{(i, j) in ARCS} f[i, j];\n"
        "subject to c: sum{(i, j) in ARCS} f[i, j] <= 5;\n"
    )
    draft = deground_problem(problem)
    assert draft is not None  # `f_a_b, f_b_c` → a 1-D set of joined labels, round-trips
    assert _recompiles_equivalent(draft, problem)


def test_partial_objective_coverage_is_not_falsely_summed():
    """An objective touching only some of a family's members can't be a full sum —
    the compact path declines; a small model falls back to a scalar JModel."""
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    problem = OptimizationProblem(
        variables=[
            Variable(name="x_1", type=VariableType.BINARY, family="x", index_tuple=["1"]),
            Variable(name="x_2", type=VariableType.BINARY, family="x", index_tuple=["2"]),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x_1"),  # x_2 missing
        constraints=[Constraint(name="c", expression="x_1 + x_2 <= 1")],
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "sum{" not in draft  # the partial objective is not falsely turned into a sum
    assert _recompiles_equivalent(draft, problem)


def test_split_derives_the_general_formulation_plus_a_dataset():
    """The split form is the point of JModel: the source is the PURE formulation
    (declaration-only sets/params, zero inline data) and every value lands in the
    dataset — verified by compiling source+dataset back to an equivalent problem."""
    from app.domains.dsl import JModelData
    from app.services.jmodel_deground import deground_problem_split

    problem = _flat(ASSIGNMENT)
    draft = deground_problem_split(problem)
    assert draft is not None
    assert draft.dataset is not None

    # Pure formulation: declarations only — not a single `:=` anywhere.
    assert "set S1;" in draft.source
    assert "param c_assign{S1, S2};" in draft.source
    assert ":=" not in draft.source
    assert "sum{i in S1, j in S2}" in draft.source

    # The data went to the dataset, in the standard JModel dataset shape.
    assert draft.dataset["sets"]["S1"] == ["A", "B", "C"]
    assert draft.dataset["sets"]["S2"] == ["1", "2", "3"]
    assert draft.dataset["params"]["c_assign"]["A,1"] == 9.0

    # Honesty gate, split edition: source + dataset recompiles to the same model.
    rebuilt = compile_jmodel(draft.source, data=JModelData.from_json(draft.dataset))
    assert {v.name for v in rebuilt.variables} == {v.name for v in problem.variables}
    assert len(rebuilt.constraints) == len(problem.constraints)


def test_split_keeps_a_scalar_fallback_self_contained():
    """A small flat model with no recoverable compact structure still derives as a
    self-contained scalar JModel — no dataset to split."""
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )
    from app.services.jmodel_deground import deground_problem_split

    problem = OptimizationProblem(
        variables=[
            Variable(name="x_1", type=VariableType.BINARY, family="x", index_tuple=["1"]),
            Variable(name="x_2", type=VariableType.BINARY, family="x", index_tuple=["2"]),
        ],
        objective=Objective(sense=ObjectiveSense.MAXIMIZE, expression="x_1"),  # partial → scalar
        constraints=[Constraint(name="c", expression="x_1 + x_2 <= 1")],
    )
    draft = deground_problem_split(problem)
    assert draft is not None
    assert draft.dataset is None
    assert "sum{" not in draft.source


# --------------------------------------------------------------------------- #
# Template-key capability gaps found by the 2026-07-21 torture test (H1 / H2)
# --------------------------------------------------------------------------- #

# H1 — two same-shape SCALAR constraints over one family (multi-knapsack). They
# share a template key but have no free index a ∀ could range over, so fusing
# them can only decline on the differing weights/rhs; each must emit alone.
MULTI_KNAPSACK = """
set I := {a, b, c};
param v{I} := a 60, b 100, c 120;
param w1{I} := a 10, b 20, c 30;
param w2{I} := a 5, b 15, c 25;
var x{I} binary;
maximize total: sum{i in I} v[i] * x[i];
subject to weight: sum{i in I} w1[i] * x[i] <= 50;
subject to volume: sum{i in I} w2[i] * x[i] <= 40;
"""


def test_two_scalar_knapsack_constraints_do_not_fuse():
    problem = _flat(MULTI_KNAPSACK)
    draft = deground_problem(problem)
    assert draft is not None
    assert "sum{" in draft  # compact — not the scalar fallback (H1 used to decline)
    assert draft.count("subject to") == 2
    assert "<= 50" in draft and "<= 40" in draft
    assert _recompiles_equivalent(draft, problem)


def test_two_scalar_knapsack_constraints_split_with_distinct_params():
    from app.domains.dsl import JModelData
    from app.services.jmodel_deground import deground_problem_split

    problem = _flat(MULTI_KNAPSACK)
    draft = deground_problem_split(problem)
    assert draft is not None
    assert draft.dataset is not None
    assert ":=" not in draft.source
    # Each knapsack keeps its own coefficient table in the dataset.
    assert "a_c1_x" in draft.dataset["params"]
    assert "a_c2_x" in draft.dataset["params"]
    rebuilt = compile_jmodel(draft.source, data=JModelData.from_json(draft.dataset))
    assert len(rebuilt.constraints) == len(problem.constraints)


# H2 — a per-constraint CONSTANT coefficient (CFLP's ``cap_i · y_i``). The constant
# differs per constraint, which used to fragment the template key into singleton
# groups that decline; it must derive as ONE ∀ family with a coefficient param.
CFLP = """
set F := {f1, f2, f3}; set C := {c1, c2};
param cap{F} := f1 8, f2 7, f3 9;
param d{C} := c1 4, c2 6;
var x{F, C} >= 0;
var y{F} binary;
minimize total: sum{f in F} cap[f] * y[f] + sum{f in F, c in C} x[f, c];
subject to open{f in F}: sum{c in C} x[f, c] - cap[f] * y[f] <= 0;
subject to demand{c in C}: sum{f in F} x[f, c] >= d[c];
"""


def test_per_constraint_constant_coefficient_stays_one_family():
    problem = _flat(CFLP)
    draft = deground_problem(problem)
    assert draft is not None
    assert "sum{" in draft
    assert draft.count("subject to") == 2  # open + demand — no singleton shatter
    link = next(ln for ln in draft.splitlines() if "y[" in ln and "subject to" in ln)
    assert "{i in S1}" in link  # ∀-quantified over facilities
    assert "a_c1_y[i] * y[i]" in link  # the per-facility constant became a param
    assert _recompiles_equivalent(draft, problem)


def test_per_row_uniform_coefficients_merge_into_one_param_family():
    """Per-row constants over a full free set (``k_i · Σ_j x[i,j] ≤ m_i``) are the
    indexed flavour of H2 — one ∀ family with a coefficient param, not singletons."""
    problem = _flat(
        "set I := {1, 2}; set J := {p, q};\n"
        "param k{I} := 1 5, 2 7;\n"
        "param m{I} := 1 10, 2 20;\n"
        "var x{I, J} >= 0;\n"
        "minimize obj: sum{i in I, j in J} x[i, j];\n"
        "subject to r{i in I}: sum{j in J} k[i] * x[i, j] <= m[i];\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert draft.count("subject to") == 1
    assert _recompiles_equivalent(draft, problem)


def test_same_pattern_uniform_constant_families_stay_separate():
    """Two ∀ families differing only in a uniform coefficient (and rhs) now share
    the coarse template key; the merged emission conflicts and must fall back to
    the per-value partition — recovered as TWO families, never declined."""
    problem = _flat(
        "set I := {1, 2}; set J := {p, q};\n"
        "var x{I, J} >= 0;\n"
        "minimize obj: sum{i in I, j in J} x[i, j];\n"
        "subject to lo{i in I}: sum{j in J} 5 * x[i, j] <= 10;\n"
        "subject to hi{i in I}: sum{j in J} 7 * x[i, j] <= 20;\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert draft.count("subject to") == 2
    assert "5 * sum{" in draft and "7 * sum{" in draft
    assert _recompiles_equivalent(draft, problem)


# --------------------------------------------------------------------------- #
# Set identity & index letters (the 2026-07-21 torture test's cosmetic findings)
# --------------------------------------------------------------------------- #


def test_equal_membered_axes_stay_distinct_sets():
    """Jobs and periods sharing the same labels are still different sets — nothing
    links them, so the draft must not claim ``x{S1, S1}`` (an identity the flat
    model never stated)."""
    problem = _flat(
        "set J := {1, 2, 3}; set T := {1, 2, 3};\n"
        "var x{J, T} binary;\n"
        "minimize obj: sum{j in J, t in T} x[j, t];\n"
        "subject to one{j in J}: sum{t in T} x[j, t] <= 1;\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "var x{S1, S2} binary;" in draft
    assert draft.count("set S") == 2
    assert _recompiles_equivalent(draft, problem)


def test_shared_free_index_links_slots_to_one_set():
    """The linking constraint (``sum_i x[i,j] + z[j] == 1``) is the structural
    evidence that z ranges over x's second axis — those slots DO share one set."""
    problem = _flat(MULTI_FAMILY)
    draft = deground_problem(problem)
    assert draft is not None
    assert "var x{S1, S2} binary;" in draft
    assert "var z{S2} binary;" in draft
    assert _recompiles_equivalent(draft, problem)


def test_one_index_letter_per_set_across_the_source():
    """One set, one letter, everywhere: a family ranging only over the SECOND set
    uses that set's canonical letter (j) in the objective and under the ∀ alike —
    not a fresh ``i`` per line."""
    problem = _flat(
        "set I := {1, 2, 3}; set J := {a, b};\n"
        "param p{J} := a 5, b 7;\n"
        "var x{I, J} binary;\n"
        "var z{J} binary;\n"
        "minimize obj: sum{i in I, j in J} x[i, j] + sum{j in J} p[j] * z[j];\n"
        "subject to link{j in J}: sum{i in I} x[i, j] + z[j] == 1;\n"
    )
    draft = deground_problem(problem)
    assert draft is not None
    assert "sum{j in S2} c_z[j] * z[j]" in draft
    assert "{j in S2}" in draft
    assert _recompiles_equivalent(draft, problem)


def test_arity_beyond_the_index_letter_pool_declines_gracefully():
    """A family with more index positions than there are index letters (14) must
    DECLINE (None — the model is also too big for the scalar fallback), never leak
    an IndexError/StopIteration out of the service contract."""
    from app.schemas.optimization import (
        Constraint,
        Objective,
        ObjectiveSense,
        OptimizationProblem,
        Variable,
        VariableType,
    )

    base = "_".join(["1"] * 14)  # 14 fixed positions + 1 varying = arity 15
    names = [f"x_{base}_{k}" for k in range(1, 62)]  # 61 members > scalar fallback cap
    problem = OptimizationProblem(
        variables=[Variable(name=n, type=VariableType.CONTINUOUS) for n in names],
        objective=Objective(sense=ObjectiveSense.MINIMIZE, expression=" + ".join(names)),
        constraints=[Constraint(name="c", expression=f"{names[0]} >= 0")],
    )
    assert deground_problem(problem) is None
