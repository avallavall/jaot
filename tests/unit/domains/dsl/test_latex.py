"""Unit tests for the JModel LaTeX pretty-printer (B1).

The pretty-printer walks the parsed AST BEFORE grounding, so the symbolic
structure (indexed sums, ∀-quantified constraint families, variable domains)
survives instead of being flattened to scalar rows. It is parse-only and
deterministic, so these tests assert the exact rendered TeX. Grammar:
``.claude/plans/jmodel-grammar-2026-07-01.md``.
"""

import pytest

from app.domains.dsl import JModelError, latexify

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Objective
# --------------------------------------------------------------------------- #


def test_objective_minimize_scalar():
    model = latexify("var x >= 0;\nminimize obj: x;")
    assert model.objective is not None
    assert model.objective.latex == "\\min \\quad x"
    assert model.objective.label == "obj"


def test_objective_maximize_uses_max():
    model = latexify("var x >= 0;\nmaximize obj: x;")
    assert model.objective is not None
    assert model.objective.latex.startswith("\\max \\quad ")


def test_objective_indexed_double_sum_is_symbolic():
    """The TFM's headline form: ΣΣ over two sets with a coefficient·variable body."""
    src = (
        "set I := {a, b};\n"
        "set J := {1, 2};\n"
        "param c{I, J} := a 1 1, a 2 2, b 1 3, b 2 4;\n"
        "var x{I, J} binary;\n"
        "minimize obj: sum{i in I, j in J} c[i, j] * x[i, j];\n"
    )
    model = latexify(src)
    assert model.objective is not None
    assert model.objective.latex == (
        "\\min \\quad \\sum_{i \\in I,\\; j \\in J} c_{i,j} \\, x_{i,j}"
    )


def test_nested_sums_render_as_two_sigmas():
    src = (
        "set I := {a};\nset J := {1};\n"
        "var x{I, J} binary;\n"
        "minimize obj: sum{i in I} sum{j in J} x[i, j];\n"
    )
    model = latexify(src)
    assert model.objective is not None
    assert "\\sum_{i \\in I} \\sum_{j \\in J} x_{i,j}" in model.objective.latex


# --------------------------------------------------------------------------- #
# Constraints — the ∀ quantifier is the whole point
# --------------------------------------------------------------------------- #


def test_constraint_family_carries_forall_quantifier():
    src = (
        "set W := {A, B};\nset T := {1, 2};\n"
        "var assign{W, T} binary;\n"
        "minimize obj: sum{w in W, t in T} assign[w, t];\n"
        "subject to one_per_task{t in T}: sum{w in W} assign[w, t] == 1;\n"
    )
    model = latexify(src)
    assert len(model.constraints) == 1
    con = model.constraints[0]
    assert con.label == "one_per_task"
    assert con.latex == ("\\sum_{w \\in W} \\mathrm{assign}_{w,t} = 1 \\quad \\forall\\, t \\in T")


def test_scalar_constraint_has_no_forall():
    model = latexify("var x >= 0;\nminimize obj: x;\nsubject to c: x >= 5;")
    assert model.constraints[0].latex == "x \\ge 5"
    assert "\\forall" not in model.constraints[0].latex


def test_constraint_relation_operators_map_to_tex():
    src = "var x >= 0;\nminimize obj: x;\nsubject to c: x <= 5;"
    assert latexify(src).constraints[0].latex == "x \\le 5"


def test_sum_filter_renders_as_such_that_clause():
    src = (
        "set I := {a, b};\n"
        "param d{I, I} := a a 0, a b 1, b a 1, b b 0;\n"
        "var x{I, I} binary;\n"
        "minimize obj: sum{i in I, j in I : i != j} d[i, j] * x[i, j];\n"
    )
    model = latexify(src)
    assert model.objective is not None
    assert (
        "\\sum_{i \\in I,\\; j \\in I \\,:\\, i \\ne j} d_{i,j} \\, x_{i,j}"
        in model.objective.latex
    )


def test_tuple_set_binding_renders_as_pair():
    src = (
        "set ARCS := {(a, b), (b, c)};\n"
        "var f{ARCS} >= 0;\n"
        "minimize obj: sum{(i, j) in ARCS} f[i, j];\n"
    )
    model = latexify(src)
    assert model.objective is not None
    assert "\\sum_{(i, j) \\in \\mathrm{ARCS}} f_{i,j}" in model.objective.latex


# --------------------------------------------------------------------------- #
# Operator precedence and multiplication style
# --------------------------------------------------------------------------- #


def test_subtraction_of_a_sum_keeps_parentheses():
    src = "var a >= 0;\nvar b >= 0;\nvar d >= 0;\nminimize obj: a - (b + d);"
    assert latexify(src).objective.latex == "\\min \\quad a - \\left(b + d\\right)"


def test_product_of_a_sum_parenthesizes_the_sum():
    src = "var a >= 0;\nvar b >= 0;\nvar d >= 0;\nminimize obj: (a + b) * d;"
    assert latexify(src).objective.latex == "\\min \\quad \\left(a + b\\right) \\, d"


def test_coefficient_times_variable_uses_implicit_product():
    src = "var x >= 0;\nminimize obj: 2 * x;"
    assert latexify(src).objective.latex == "\\min \\quad 2 \\, x"


def test_number_times_number_uses_cdot():
    src = "var x >= 0;\nminimize obj: 2 * 3 * x;"
    # num·num stays an explicit product; the trailing variable is implicit.
    assert "2 \\cdot 3" in latexify(src).objective.latex


def test_power_renders_as_superscript():
    src = "var x >= 0;\nminimize obj: x^2;"
    assert latexify(src).objective.latex == "\\min \\quad x^{2}"


def test_power_of_a_sum_parenthesizes_the_base():
    src = "var a >= 0;\nvar b >= 0;\nminimize obj: (a + b)^2;"
    assert latexify(src).objective.latex == "\\min \\quad \\left(a + b\\right)^{2}"


# --------------------------------------------------------------------------- #
# Symbol rendering — greek, multi-char names, if-expressions
# --------------------------------------------------------------------------- #


def test_greek_named_symbol_renders_as_letter():
    src = (
        "set I := {a};\nparam alpha := 2;\n"
        "var x{I} >= 0;\n"
        "minimize obj: alpha * sum{i in I} x[i];\n"
    )
    model = latexify(src)
    assert model.objective is not None
    assert model.objective.latex == "\\min \\quad \\alpha \\, \\sum_{i \\in I} x_{i}"


def test_multichar_name_is_upright():
    src = (
        "set I := {a};\nparam cost{I} := a 5;\n"
        "var take{I} binary;\n"
        "minimize obj: sum{i in I} cost[i] * take[i];\n"
    )
    model = latexify(src)
    assert model.objective is not None
    assert "\\mathrm{cost}_{i} \\, \\mathrm{take}_{i}" in model.objective.latex


def test_if_expression_renders_as_cases():
    src = (
        "set I := {1, 2};\nparam p := 1;\n"
        "var x{I} >= 0;\n"
        "minimize obj: sum{i in I} (if i == p then 2 else 3) * x[i];\n"
    )
    model = latexify(src)
    assert model.objective is not None
    assert "\\begin{cases}" in model.objective.latex
    assert "\\text{otherwise}" in model.objective.latex
    assert "\\text{if } i = p" in model.objective.latex


# --------------------------------------------------------------------------- #
# Variable domains
# --------------------------------------------------------------------------- #


def test_binary_variable_domain():
    src = (
        "set W := {A};\nset T := {1};\n"
        "var assign{W, T} binary;\n"
        "minimize obj: sum{w in W, t in T} assign[w, t];\n"
    )
    model = latexify(src)
    assert len(model.variables) == 1
    var = model.variables[0]
    assert var.label == "assign"
    assert var.latex == (
        "\\mathrm{assign}_{w,t} \\in \\{0, 1\\} \\quad \\forall\\, w \\in W,\\; t \\in T"
    )


def test_continuous_variable_with_lower_bound():
    model = latexify("var x >= 0;\nminimize obj: x;")
    assert model.variables[0].latex == "x \\in \\mathbb{R},\\; x \\ge 0"


def test_integer_variable_with_both_bounds():
    model = latexify("var x integer >= 1 <= 10;\nminimize obj: x;")
    assert model.variables[0].latex == "x \\in \\mathbb{Z},\\; 1 \\le x \\le 10"


def test_free_continuous_variable_has_no_bound_clause():
    model = latexify("var x;\nminimize obj: x;")
    assert model.variables[0].latex == "x \\in \\mathbb{R}"


def test_variable_order_is_preserved():
    src = "var z >= 0;\nvar a >= 0;\nminimize obj: z + a;"
    labels = [v.label for v in latexify(src).variables]
    assert labels == ["z", "a"]


# --------------------------------------------------------------------------- #
# Error path — parse-only, so lex/parse errors raise (grounding never runs)
# --------------------------------------------------------------------------- #


def test_parse_error_raises_jmodel_error():
    with pytest.raises(JModelError):
        latexify("var x >= ;\nminimize obj: x;")


def test_declaration_only_source_succeeds_without_data():
    """No dataset needed: a declaration-only source still renders its structure."""
    src = "set I;\nparam w{I};\nvar x{I} binary;\nminimize obj: sum{i in I} w[i] * x[i];"
    model = latexify(src)
    assert model.objective is not None
    assert "\\sum_{i \\in I} w_{i} \\, x_{i}" in model.objective.latex
    assert model.variables[0].latex.startswith("x_{i} \\in \\{0, 1\\}")


def test_objectiveless_source_raises():
    """The grammar requires an objective, so an incomplete source raises (the
    frontend surfaces this as "not yet a renderable model", never a crash)."""
    with pytest.raises(JModelError):
        latexify("set I := {a};\nvar x{I} binary;")


def test_model_without_constraints_renders_objective_and_domains():
    model = latexify("var x >= 0;\nminimize obj: x;")
    assert model.objective is not None
    assert model.constraints == ()
    assert len(model.variables) == 1
