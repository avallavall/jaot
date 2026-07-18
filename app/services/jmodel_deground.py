"""De-ground a flat problem back into a compact JModel draft (B2, phase 1).

The inverse of the JModel compiler: given a flat :class:`OptimizationProblem`
(from the visual builder, an MPS/LP import, or a template) it tries to RECOVER the
indexed structure the flat form threw away — variable families over sets, an
objective as ``sum`` over index params, and constraint families quantified with
``∀`` — so a model with no JModel source can still be read, edited and shown as
math (B1) in its compact form instead of as a wall of scalar rows.

**Honesty over theatre.** Reconstruction is heuristic, so every draft is proven
before it is offered: the candidate source is recompiled and checked to be
*equivalent* to the input (same variables, same objective, same constraints, up to
naming and ordering). If it does not round-trip — or no compact structure is
recoverable — :func:`deground_problem` returns ``None`` and the caller declines
rather than show a draft that lies about the model.

This lives in the service layer (not ``app.domains.dsl``) because it needs both the
DSL compiler and the solver's :class:`ExpressionParser`, which the DSL domain's
import contract forbids it from importing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domains.dsl import JModelError, compile_jmodel
from app.domains.solver.services.expression_parser import ExpressionParser, ParseError
from app.schemas.optimization import OptimizationProblem, Variable, VariableType
from app.schemas.solution_structure import annotate_variable_structure

_EPS = 1e-9
# Index letters for reconstructed sums / ∀-quantifiers (i, j, k, …).
_INDEX_LETTERS = "ijklmnpqrstuvw"


def deground_problem(problem: OptimizationProblem) -> str | None:
    """Reconstruct a compact JModel source from a flat problem, or ``None``.

    Returns source only when it is recoverable AND verifiably round-trips to a
    problem equivalent to the input; otherwise ``None`` (the caller declines).
    """
    try:
        source = _reconstruct(problem)
    except (_DegroundError, ParseError):
        source = None
    # No compact structure recovered — fall back to a plain scalar JModel for a SMALL
    # model (a large flat model would just be the wall of rows B2 exists to avoid, so
    # it stays declined).
    if source is None:
        source = _scalar_jmodel(problem)
    if source is None:
        return None
    # Honesty gate: the draft must recompile to an equivalent problem.
    try:
        rebuilt = compile_jmodel(source)
    except JModelError:
        return None
    if not _problems_equivalent(problem, rebuilt):
        return None
    return source


class _DegroundError(Exception):
    """Internal: the flat problem has no cleanly recoverable compact structure."""


# --------------------------------------------------------------------------- #
# Reconstruction
# --------------------------------------------------------------------------- #


@dataclass
class _Family:
    name: str
    members: list[Variable]  # in flat problem order
    arity: int
    vtype: VariableType
    lb: float | None
    ub: float | None
    # ordered unique member values per index position
    position_values: list[list[str]]
    # index_tuple → the variable's flat name, for coefficient lookup
    by_tuple: dict[tuple[str, ...], str]


def _reconstruct(problem: OptimizationProblem) -> str | None:
    # Ensure family/index structure is present (numeric-index parse for flat models;
    # a no-op when the compiler already annotated authoritatively).
    annotate_variable_structure(problem)

    families, scalars = _group_families(problem.variables)
    if not any(len(f.members) >= 2 for f in families.values()):
        # Nothing is actually indexed — the flat form already IS the model, so a
        # "compact" JModel would just be the scalar model verbatim (no value).
        return None

    parser = ExpressionParser()
    var_names = {v.name for v in problem.variables}

    sets = _SetRegistry()
    for fam in families.values():
        for values in fam.position_values:
            sets.intern(values)

    lines: list[str] = []
    lines.extend(sets.declarations())

    param_lines: list[str] = []
    var_lines: list[str] = []
    for fam in families.values():
        var_lines.append(_var_decl(fam, sets))
    for var in scalars:
        var_lines.append(_scalar_var_decl(var))

    objective_line, obj_params = _build_objective(
        problem, families, scalars, sets, parser, var_names
    )
    param_lines.extend(obj_params)

    constraint_lines, con_params = _build_constraints(problem, families, sets, parser, var_names)
    param_lines.extend(con_params)

    lines.extend(param_lines)
    lines.extend(var_lines)
    lines.append(objective_line)
    lines.extend(constraint_lines)

    header = "# JModel draft — derived from a flat model, review before relying on it"
    return header + "\n" + "\n".join(lines)


def _group_families(
    variables: list[Variable],
) -> tuple[dict[str, _Family], list[Variable]]:
    """Group variables by family; a family must be a dense, uniform, cartesian block."""
    order: list[str] = []
    grouped: dict[str, list[Variable]] = {}
    scalars: list[Variable] = []
    for var in variables:
        if var.family and var.index_tuple:
            if var.family not in grouped:
                grouped[var.family] = []
                order.append(var.family)
            grouped[var.family].append(var)
        else:
            scalars.append(var)

    families: dict[str, _Family] = {}
    for name in order:
        members = grouped[name]
        arity = len(members[0].index_tuple or [])
        if arity == 0 or any(len(m.index_tuple or []) != arity for m in members):
            raise _DegroundError(f"family {name!r} has inconsistent index arity")
        first = members[0]
        if any(
            m.type != first.type
            or m.lower_bound != first.lower_bound
            or m.upper_bound != first.upper_bound
            for m in members
        ):
            raise _DegroundError(f"family {name!r} mixes variable types/bounds")
        position_values = _dense_cartesian_positions(name, members, arity)
        by_tuple = {tuple(m.index_tuple or []): m.name for m in members}
        families[name] = _Family(
            name=name,
            members=members,
            arity=arity,
            vtype=first.type,
            lb=first.lower_bound,
            ub=first.upper_bound,
            position_values=position_values,
            by_tuple=by_tuple,
        )
    return families, scalars


def _dense_cartesian_positions(name: str, members: list[Variable], arity: int) -> list[list[str]]:
    """Per-position ordered-unique members; require a dense cartesian block in order.

    JModel grounds a family as the cartesian product of its sets in nested order, so
    only a family whose members ARE that product (in that order) can be one ``var``
    declaration. A sparse or reordered family raises (caller declines / falls back).
    """
    tuples = [tuple(m.index_tuple or []) for m in members]
    position_values: list[list[str]] = []
    for pos in range(arity):
        seen: list[str] = []
        seen_set: set[str] = set()
        for tup in tuples:
            val = tup[pos]
            if val not in seen_set:
                seen_set.add(val)
                seen.append(val)
        position_values.append(seen)

    expected = 1
    for values in position_values:
        expected *= len(values)
    if expected != len(tuples):
        raise _DegroundError(f"family {name!r} is sparse (not a full cartesian product)")

    # The order must be the nested cartesian order (position 0 outermost).
    cartesian = _cartesian(position_values)
    if cartesian != tuples:
        raise _DegroundError(f"family {name!r} members are not in cartesian order")
    return position_values


def _cartesian(position_values: list[list[str]]) -> list[tuple[str, ...]]:
    result: list[tuple[str, ...]] = [()]
    for values in position_values:
        result = [prev + (v,) for prev in result for v in values]
    return result


# A scalar JModel of thousands of rows is the hairball B2 exists to fix, so the
# flat fallback is offered only for a small model (a hand-built or imported model
# with no indexed families — e.g. an assortment or a two-variable canvas model).
_SCALAR_MAX_ITEMS = 60


def _scalar_jmodel(problem: OptimizationProblem) -> str | None:
    """A plain, non-indexed JModel of a small flat model (no families to recover).

    Emits one ``var`` per variable and the objective/constraints verbatim (they are
    already valid JModel expressions over the flat names). Returns ``None`` past
    :data:`_SCALAR_MAX_ITEMS` — a large flat model has no compact form and a scalar
    dump would be a wall. Still gated by the round-trip check in the caller.
    """
    if len(problem.variables) > _SCALAR_MAX_ITEMS or len(problem.constraints) > _SCALAR_MAX_ITEMS:
        return None
    lines = [_scalar_var_decl(var) for var in problem.variables]
    sense = "minimize" if problem.objective.sense.value == "minimize" else "maximize"
    lines.append(f"{sense} obj: {problem.objective.expression};")
    for i, con in enumerate(problem.constraints, start=1):
        lines.append(f"subject to c{i}: {con.expression};")
    header = "# JModel draft — derived from a flat model, review before relying on it"
    return header + "\n" + "\n".join(lines)


class _SetRegistry:
    """Interns ordered member lists → shared set names (``S1``, ``S2`` …)."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, ...], str] = {}
        self._decls: list[str] = []

    def intern(self, values: list[str]) -> str:
        key = tuple(values)
        name = self._by_key.get(key)
        if name is None:
            name = f"S{len(self._by_key) + 1}"
            self._by_key[key] = name
            self._decls.append(f"set {name} := {{{', '.join(values)}}};")
        return name

    def name_for(self, values: list[str]) -> str:
        return self._by_key[tuple(values)]

    def declarations(self) -> list[str]:
        return list(self._decls)


def _var_decl(fam: _Family, sets: _SetRegistry) -> str:
    index_sets = ", ".join(sets.name_for(values) for values in fam.position_values)
    suffix = _type_suffix(fam.vtype, fam.lb, fam.ub)
    return f"var {fam.name}{{{index_sets}}}{suffix};"


def _scalar_var_decl(var: Variable) -> str:
    return f"var {var.name}{_type_suffix(var.type, var.lower_bound, var.upper_bound)};"


def _type_suffix(vtype: VariableType, lb: float | None, ub: float | None) -> str:
    if vtype == VariableType.BINARY:
        return " binary"
    parts = ""
    if vtype == VariableType.INTEGER:
        parts += " integer"
    if lb is not None:
        parts += f" >= {_num(lb)}"
    if ub is not None:
        parts += f" <= {_num(ub)}"
    return parts


# --------------------------------------------------------------------------- #
# Objective
# --------------------------------------------------------------------------- #


def _build_objective(
    problem: OptimizationProblem,
    families: dict[str, _Family],
    scalars: list[Variable],
    sets: _SetRegistry,
    parser: ExpressionParser,
    var_names: set[str],
) -> tuple[str, list[str]]:
    parsed = parser.parse_expression(problem.objective.expression, var_names)
    coefs: dict[str, float] = {}
    for term in parsed.terms:
        if len(term.variables) != 1:
            raise _DegroundError("objective is not linear")
        coefs[term.variables[0]] = coefs.get(term.variables[0], 0.0) + term.coefficient

    terms: list[str] = []
    params: list[str] = []
    used = 0
    for fam in families.values():
        fam_coefs = {tup: coefs.get(name, 0.0) for tup, name in fam.by_tuple.items()}
        if all(abs(c) < _EPS for c in fam_coefs.values()):
            continue  # family absent from the objective
        if any(name not in coefs for name in fam.by_tuple.values()):
            raise _DegroundError(f"objective covers family {fam.name!r} only partially")
        used += len(fam.by_tuple)
        letters = _index_letters(fam.arity)
        binding = _binding(fam, sets, letters)
        ref = f"{fam.name}[{', '.join(letters)}]"
        distinct = {round(c, 9) for c in fam_coefs.values()}
        if distinct == {1.0}:
            terms.append(f"sum{{{binding}}} {ref}")
        elif len(distinct) == 1:
            terms.append(f"sum{{{binding}}} {_num(next(iter(distinct)))} * {ref}")
        else:
            pname = f"c_{fam.name}"
            params.append(_param_decl(pname, fam, sets, fam_coefs))
            idx = ", ".join(letters)
            terms.append(f"sum{{{binding}}} {pname}[{idx}] * {ref}")

    for var in scalars:
        c = coefs.get(var.name, 0.0)
        if abs(c) >= _EPS:
            used += 1
            terms.append(f"{var.name}" if abs(c - 1.0) < _EPS else f"{_num(c)} * {var.name}")

    # Every objective term must have been accounted for by a family or a scalar.
    accounted = used
    present = sum(1 for c in coefs.values() if abs(c) >= _EPS)
    if accounted != present:
        raise _DegroundError("objective has terms outside the recovered families")
    if abs(parsed.constant) >= _EPS:
        terms.append(_num(parsed.constant))
    if not terms:
        raise _DegroundError("objective is empty")

    sense = "minimize" if problem.objective.sense.value == "minimize" else "maximize"
    return f"{sense} obj: {' + '.join(terms)};", params


# --------------------------------------------------------------------------- #
# Constraints
# --------------------------------------------------------------------------- #


@dataclass
class _ConstraintShape:
    """One flat constraint reduced to a single-family sum pattern."""

    family: str
    fixed: tuple[tuple[int, str], ...]  # (position, member) held constant
    summed: tuple[int, ...]  # positions ranging over their full set
    coef_by_tuple: dict[tuple[str, ...], float]  # coef per full index tuple
    operator: str
    rhs: float


def _build_constraints(
    problem: OptimizationProblem,
    families: dict[str, _Family],
    sets: _SetRegistry,
    parser: ExpressionParser,
    var_names: set[str],
) -> tuple[list[str], list[str]]:
    shapes: list[_ConstraintShape] = []
    for con in problem.constraints:
        shapes.append(_shape_of(con.expression, families, parser, var_names))

    # Group constraints that share a template but differ only in their fixed members.
    groups: dict[tuple, list[_ConstraintShape]] = {}
    order: list[tuple] = []
    for shape in shapes:
        key = (
            shape.family,
            tuple(p for p, _ in shape.fixed),
            shape.summed,
            shape.operator,
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(shape)

    lines: list[str] = []
    params: list[str] = []
    counter = 0
    for key in order:
        counter += 1
        line, extra = _emit_constraint_group(f"c{counter}", groups[key], families[key[0]], sets)
        lines.append(line)
        params.extend(extra)
    return lines, params


def _shape_of(
    expression: str,
    families: dict[str, _Family],
    parser: ExpressionParser,
    var_names: set[str],
) -> _ConstraintShape:
    parsed = parser.parse_constraint(expression, var_names)
    coefs: dict[str, float] = {}
    for term in parsed.lhs.terms:
        if len(term.variables) != 1:
            raise _DegroundError("constraint is not linear")
        coefs[term.variables[0]] = coefs.get(term.variables[0], 0.0) + term.coefficient
    if not coefs:
        raise _DegroundError("constraint has no variables")

    # Every variable must belong to ONE family (single-family sum patterns only).
    fam_name: str | None = None
    for name in coefs:
        owner = _family_of(name, families)
        if owner is None:
            raise _DegroundError("constraint references a variable outside any family")
        if fam_name is None:
            fam_name = owner
        elif fam_name != owner:
            raise _DegroundError("constraint mixes families")
    assert fam_name is not None
    fam = families[fam_name]

    tuples = [_tuple_of(name, fam) for name in coefs]
    fixed: list[tuple[int, str]] = []
    summed: list[int] = []
    for pos in range(fam.arity):
        pos_values = {tup[pos] for tup in tuples}
        if len(pos_values) == 1:
            fixed.append((pos, next(iter(pos_values))))
        elif pos_values == set(fam.position_values[pos]):
            summed.append(pos)
        else:
            raise _DegroundError("constraint spans a partial set")
    # The summed positions must cover the full cartesian block (a complete sum);
    # ``summed`` may be empty — a per-element constraint (``x[i] <= 1 ∀ i``).
    expected = 1
    for pos in summed:
        expected *= len(fam.position_values[pos])
    if len(coefs) != expected:
        raise _DegroundError("constraint is not a complete sum over its free indices")

    coef_by_tuple = {_tuple_of(name, fam): c for name, c in coefs.items()}
    return _ConstraintShape(
        family=fam_name,
        fixed=tuple(fixed),
        summed=tuple(summed),
        coef_by_tuple=coef_by_tuple,
        operator=parsed.operator,
        rhs=parsed.rhs,
    )


def _emit_constraint_group(
    cname: str,
    group: list[_ConstraintShape],
    fam: _Family,
    sets: _SetRegistry,
) -> tuple[str, list[str]]:
    first = group[0]
    fixed_positions = [p for p, _ in first.fixed]

    # The fixed members across the group must cover the full set(s) of those
    # positions, so a plain ∀ (no filter) is faithful.
    if fixed_positions:
        for pos in fixed_positions:
            members = {dict(s.fixed)[pos] for s in group}
            if members != set(fam.position_values[pos]):
                raise _DegroundError("constraint family does not cover its index set")

    letters = _index_letters(fam.arity)
    forall_parts = [
        f"{letters[p]} in {sets.name_for(fam.position_values[p])}" for p in fixed_positions
    ]
    sum_parts = [f"{letters[p]} in {sets.name_for(fam.position_values[p])}" for p in first.summed]
    ref = f"{fam.name}[{', '.join(letters)}]"
    idx = ", ".join(letters)

    params: list[str] = []

    # Coefficients across the WHOLE group, over the full cartesian block: uniform →
    # a literal, otherwise an index param p_<c>{all positions}.
    combined: dict[tuple[str, ...], float] = {}
    for shape in group:
        combined.update(shape.coef_by_tuple)
    if len(combined) != len(fam.by_tuple):
        raise _DegroundError("constraint family does not cover the variable block")
    sum_prefix = f"sum{{{', '.join(sum_parts)}}} " if first.summed else ""
    distinct = {round(c, 9) for c in combined.values()}
    if distinct == {1.0}:
        body = f"{sum_prefix}{ref}"
    elif len(distinct) == 1:
        body = f"{sum_prefix}{_num(next(iter(distinct)))} * {ref}"
    else:
        pname = f"a_{cname}"
        params.append(_param_decl(pname, fam, sets, combined))
        body = f"{sum_prefix}{pname}[{idx}] * {ref}"

    # rhs: uniform → a literal, otherwise a param r_<c>{fixed positions}.
    rhs_values = {round(s.rhs, 9) for s in group}
    if len(rhs_values) == 1:
        rhs_str = _num(next(iter(rhs_values)))
    elif fixed_positions:
        pname = f"r_{cname}"
        params.append(_rhs_param_decl(pname, group, fam, sets, fixed_positions))
        rhs_str = f"{pname}[{', '.join(letters[p] for p in fixed_positions)}]"
    else:
        raise _DegroundError("scalar constraint has no free index for a varying rhs")

    head = f"subject to {cname}"
    if forall_parts:
        head += f"{{{', '.join(forall_parts)}}}"
    return f"{head}: {body} {first.operator} {rhs_str};", params


# --------------------------------------------------------------------------- #
# Params & helpers
# --------------------------------------------------------------------------- #


def _param_decl(
    pname: str, fam: _Family, sets: _SetRegistry, coef_by_tuple: dict[tuple[str, ...], float]
) -> str:
    index_sets = ", ".join(sets.name_for(values) for values in fam.position_values)
    entries = [
        f"{' '.join(tup)} {_num(coef_by_tuple[tup])}" for tup in _cartesian(fam.position_values)
    ]
    return f"param {pname}{{{index_sets}}} := {', '.join(entries)};"


def _rhs_param_decl(
    pname: str,
    group: list[_ConstraintShape],
    fam: _Family,
    sets: _SetRegistry,
    fixed_positions: list[int],
) -> str:
    index_sets = ", ".join(sets.name_for(fam.position_values[p]) for p in fixed_positions)
    entries = []
    for shape in group:
        members = dict(shape.fixed)
        key = " ".join(members[p] for p in fixed_positions)
        entries.append(f"{key} {_num(shape.rhs)}")
    return f"param {pname}{{{index_sets}}} := {', '.join(entries)};"


def _binding(fam: _Family, sets: _SetRegistry, letters: list[str]) -> str:
    return ", ".join(
        f"{letters[p]} in {sets.name_for(fam.position_values[p])}" for p in range(fam.arity)
    )


def _index_letters(arity: int) -> list[str]:
    return [_INDEX_LETTERS[p] for p in range(arity)]


def _family_of(var_name: str, families: dict[str, _Family]) -> str | None:
    for name, fam in families.items():
        if var_name in fam.by_tuple.values():
            return name
    return None


def _tuple_of(var_name: str, fam: _Family) -> tuple[str, ...]:
    for tup, name in fam.by_tuple.items():
        if name == var_name:
            return tup
    raise _DegroundError(f"{var_name!r} not in family {fam.name!r}")


def _num(value: float) -> str:
    if value == int(value):
        return str(int(value))
    # The JModel lexer reads only positional decimals — expand any scientific
    # notation (``1e-07`` would tokenize as the variable ``e``).
    text = repr(value)
    if "e" in text or "E" in text:
        text = format(Decimal(text), "f")
    return text


# --------------------------------------------------------------------------- #
# Round-trip equivalence
# --------------------------------------------------------------------------- #


def _problems_equivalent(a: OptimizationProblem, b: OptimizationProblem) -> bool:
    if _var_signature(a) != _var_signature(b):
        return False
    parser = ExpressionParser()
    a_names = {v.name for v in a.variables}
    b_names = {v.name for v in b.variables}
    if a.objective.sense != b.objective.sense:
        return False
    if _obj_signature(a, parser, a_names) != _obj_signature(b, parser, b_names):
        return False
    return _con_signatures(a, parser, a_names) == _con_signatures(b, parser, b_names)


def _var_signature(problem: OptimizationProblem) -> frozenset:
    # A binary variable is [0, 1] whether or not the flat problem stated bounds
    # explicitly (an imported/builder model often leaves them None, while the
    # recompiled JModel stamps 0/1) — normalize so the two round-trip as equal.
    def bounds(v: Variable) -> tuple[float | None, float | None]:
        if v.type == VariableType.BINARY:
            return (0.0, 1.0)
        return (v.lower_bound, v.upper_bound)

    return frozenset((v.name, v.type.value, *bounds(v)) for v in problem.variables)


def _obj_signature(problem: OptimizationProblem, parser: ExpressionParser, names: set[str]):
    parsed = parser.parse_expression(problem.objective.expression, names)
    return (_term_map(parsed.terms), round(parsed.constant, 9))


def _con_signatures(problem: OptimizationProblem, parser: ExpressionParser, names: set[str]):
    sigs = []
    for con in problem.constraints:
        pc = parser.parse_constraint(con.expression, names)
        lhs = dict(_term_map(pc.lhs.terms))
        op, rhs = pc.operator, pc.rhs
        if op in (">=", ">"):
            op = "<=" if op == ">=" else "<"
            lhs = {k: -v for k, v in lhs.items()}
            rhs = -rhs
        sigs.append((op, frozenset(lhs.items()), round(rhs, 9)))
    return sorted(sigs, key=repr)


def _term_map(terms) -> frozenset:
    d: dict[tuple[str, ...], float] = {}
    for term in terms:
        key = tuple(sorted(term.variables))
        d[key] = d.get(key, 0.0) + term.coefficient
    return frozenset((k, round(v, 9)) for k, v in d.items() if abs(v) >= _EPS)
