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

from app.domains.dsl import JModelData, JModelError, compile_jmodel
from app.domains.solver.services.expression_parser import ExpressionParser, ParseError
from app.schemas.optimization import OptimizationProblem, Variable, VariableType
from app.schemas.solution_structure import annotate_variable_structure

_EPS = 1e-9
# Index letters for reconstructed sums / ∀-quantifiers (i, j, k, …).
_INDEX_LETTERS = "ijklmnpqrstuvw"


@dataclass(frozen=True)
class DegroundDraft:
    """A derived draft: the JModel source, plus its data as a dataset when split.

    ``dataset`` is the standard JModel dataset JSON (``{"sets": …, "params": …}``)
    when the caller asked for model/data separation and the model carries indexed
    data; ``None`` when the draft is self-contained (inline or scalar fallback).
    """

    source: str
    dataset: dict | None


def deground_problem(problem: OptimizationProblem) -> str | None:
    """Reconstruct a compact, self-contained JModel source, or ``None``.

    Returns source only when it is recoverable AND verifiably round-trips to a
    problem equivalent to the input; otherwise ``None`` (the caller declines).
    Set/param data is inlined (``:=``) — see :func:`deground_problem_split` for
    the model/data-separated form.
    """
    draft = _deground(problem, split=False)
    return draft.source if draft else None


def deground_problem_split(problem: OptimizationProblem) -> DegroundDraft | None:
    """Reconstruct a JModel draft with the model/data separation JModel is FOR.

    The source carries only the general formulation — declaration-only sets and
    params (``set S1;`` / ``param c{S1, S1};``), variable families, the objective
    and the ∀-quantified constraint families, with uniform constants inline —
    while every set member and param value lands in the returned dataset JSON.
    A 100×100 model derives as ~10 readable lines instead of a wall of numbers.

    Verified exactly like the inline form: ``compile(source, dataset)`` must be
    equivalent to the input, or the whole derive declines. The scalar fallback
    (a small flat model with no indexed structure) stays self-contained
    (``dataset=None``).
    """
    return _deground(problem, split=True)


def _deground(problem: OptimizationProblem, *, split: bool) -> DegroundDraft | None:
    try:
        emission = _reconstruct(problem)
    except (_DegroundError, ParseError):
        emission = None
    # No compact structure recovered — fall back to a plain scalar JModel for a SMALL
    # model (a large flat model would just be the wall of rows B2 exists to avoid, so
    # it stays declined).
    if emission is None:
        source = _scalar_jmodel(problem)
        if source is None:
            return None
        return _verified(problem, source, None)
    if split:
        try:
            source, dataset = _render_split(emission)
        except _DegroundError:
            return None
        return _verified(problem, source, dataset)
    return _verified(problem, _render_inline(emission), None)


def _verified(
    problem: OptimizationProblem, source: str, dataset: dict | None
) -> DegroundDraft | None:
    """Honesty gate: the draft (+ its data) must recompile to an equivalent problem."""
    try:
        data = JModelData.from_json(dataset) if dataset is not None else None
        rebuilt = compile_jmodel(source, data=data)
    except JModelError:
        return None
    if not _problems_equivalent(problem, rebuilt):
        return None
    return DegroundDraft(source=source, dataset=dataset)


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


@dataclass(frozen=True)
class _ParamRecord:
    """A reconstructed indexed param: its declaration shape + its data entries."""

    name: str
    index_sets: tuple[str, ...]
    entries: dict[tuple[str, ...], float]  # insertion-ordered


@dataclass(frozen=True)
class _Emission:
    """The reconstructed draft before rendering — formulation + data, separated."""

    sets: "_SetRegistry"
    params: list[_ParamRecord]
    var_lines: list[str]
    objective_line: str
    constraint_lines: list[str]


_HEADER = "# JModel draft — derived from a flat model, review before relying on it"
_SPLIT_HEADER = (
    "# JModel draft — derived from a flat model, review before relying on it\n"
    "# (set members and param values live in the derived dataset)"
)


def _render_inline(e: _Emission) -> str:
    lines = e.sets.declarations()
    lines += [_param_inline(r) for r in e.params]
    lines += e.var_lines + [e.objective_line] + e.constraint_lines
    return _HEADER + "\n" + "\n".join(lines)


def _param_inline(r: _ParamRecord) -> str:
    body = ", ".join(f"{' '.join(key)} {_num(value)}" for key, value in r.entries.items())
    return f"param {r.name}{{{', '.join(r.index_sets)}}} := {body};"


def _render_split(e: _Emission) -> tuple[str, dict]:
    """The general formulation (declaration-only) + a JModel dataset with the data."""
    lines = [f"set {name};" for name in e.sets.names()]
    lines += [f"param {r.name}{{{', '.join(r.index_sets)}}};" for r in e.params]
    lines += e.var_lines + [e.objective_line] + e.constraint_lines
    params_json: dict[str, dict[str, float]] = {}
    for r in e.params:
        if r.name in params_json:  # defensive: derived names are unique by construction
            raise _DegroundError(f"duplicate derived param name {r.name!r}")
        params_json[r.name] = {",".join(key): value for key, value in r.entries.items()}
    dataset: dict = {"sets": {name: list(vals) for name, vals in e.sets.values().items()}}
    if params_json:
        dataset["params"] = params_json
    return _SPLIT_HEADER + "\n" + "\n".join(lines), dataset


def _reconstruct(problem: OptimizationProblem) -> _Emission | None:
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

    params: list[_ParamRecord] = []
    var_lines: list[str] = []
    for fam in families.values():
        var_lines.append(_var_decl(fam, sets))
    for var in scalars:
        var_lines.append(_scalar_var_decl(var))

    objective_line, obj_params = _build_objective(
        problem, families, scalars, sets, parser, var_names
    )
    params.extend(obj_params)

    # name → (family, index tuple), so the constraint decomposition is O(1) per
    # variable (a 150x150 model has 22k variables × hundreds of constraints).
    var_lookup = {
        name: (fam_name, tup)
        for fam_name, fam in families.items()
        for tup, name in fam.by_tuple.items()
    }
    constraint_lines, con_params = _build_constraints(
        problem, families, var_lookup, sets, parser, var_names
    )
    params.extend(con_params)

    return _Emission(
        sets=sets,
        params=params,
        var_lines=var_lines,
        objective_line=objective_line,
        constraint_lines=constraint_lines,
    )


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
        self._values: dict[str, list[str]] = {}

    def intern(self, values: list[str]) -> str:
        key = tuple(values)
        name = self._by_key.get(key)
        if name is None:
            name = f"S{len(self._by_key) + 1}"
            self._by_key[key] = name
            self._values[name] = list(values)
        return name

    def name_for(self, values: list[str]) -> str:
        return self._by_key[tuple(values)]

    def names(self) -> list[str]:
        return list(self._values)

    def values(self) -> dict[str, list[str]]:
        return self._values

    def declarations(self) -> list[str]:
        return [f"set {name} := {{{', '.join(vals)}}};" for name, vals in self._values.items()]


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
) -> tuple[str, list[_ParamRecord]]:
    parsed = parser.parse_expression(problem.objective.expression, var_names)
    coefs: dict[str, float] = {}
    for term in parsed.terms:
        if len(term.variables) != 1:
            raise _DegroundError("objective is not linear")
        coefs[term.variables[0]] = coefs.get(term.variables[0], 0.0) + term.coefficient

    terms: list[str] = []
    params: list[_ParamRecord] = []
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
            params.append(_param_record(pname, fam, sets, fam_coefs))
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
class _FamilyTerm:
    """One variable family's contribution to a constraint."""

    family: str
    fixed: tuple[tuple[int, str], ...]  # (position, member) held constant
    summed: tuple[int, ...]  # positions ranging over their full set
    coef_by_tuple: dict[tuple[str, ...], float]  # coef per full index tuple


@dataclass
class _ConstraintShape:
    """A flat constraint decomposed into one sum-pattern per family it touches.

    A real model constraint often mixes families with a SHARED free index, e.g.
    ``sum_i a[i, j] + z[j] == 1`` links family ``a`` (summing ``i``) and family
    ``z`` at the same ``j`` — recovered by aligning the fixed slots that co-vary.
    """

    terms: tuple[_FamilyTerm, ...]
    operator: str
    rhs: float


def _coef_class(coef_by_tuple: dict[tuple[str, ...], float]) -> str:
    """A coefficient signature for grouping: unit / a shared constant / varying.

    Two constraint families can share the same index structure yet differ in their
    coefficients (``sum_j a[i,j] == 1`` vs ``sum_j dist[i,j]*a[i,j] <= M``); grouping
    them together would merge distinct ∀-families, so the coefficient character is
    part of the template key.
    """
    distinct = {round(c, 9) for c in coef_by_tuple.values()}
    if distinct == {1.0}:
        return "unit"
    if len(distinct) == 1:
        return f"const:{next(iter(distinct))}"
    return "vary"


def _build_constraints(
    problem: OptimizationProblem,
    families: dict[str, _Family],
    var_lookup: dict[str, tuple[str, tuple[str, ...]]],
    sets: _SetRegistry,
    parser: ExpressionParser,
    var_names: set[str],
) -> tuple[list[str], list[_ParamRecord]]:
    shapes = [
        _shape_of(con.expression, families, var_lookup, parser, var_names)
        for con in problem.constraints
    ]

    # Group constraints sharing a template (same families with the same fixed/summed
    # position pattern, same operator); members of a group differ only in their fixed
    # values, which become the ∀-quantified free indices.
    groups: dict[tuple, list[_ConstraintShape]] = {}
    order: list[tuple] = []
    for shape in shapes:
        key = (
            tuple(
                (t.family, tuple(p for p, _ in t.fixed), t.summed, _coef_class(t.coef_by_tuple))
                for t in shape.terms
            ),
            shape.operator,
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(shape)

    lines: list[str] = []
    params: list[_ParamRecord] = []
    for counter, key in enumerate(order, start=1):
        line, extra = _emit_constraint_group(f"c{counter}", groups[key], families, sets)
        lines.append(line)
        params.extend(extra)
    return lines, params


def _shape_of(
    expression: str,
    families: dict[str, _Family],
    var_lookup: dict[str, tuple[str, tuple[str, ...]]],
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

    # Partition the terms by family (each variable must belong to one).
    by_family: dict[str, dict[tuple[str, ...], float]] = {}
    fam_order: list[str] = []
    for name, coef in coefs.items():
        entry = var_lookup.get(name)
        if entry is None:
            raise _DegroundError("constraint references a variable outside any family")
        fam_name, tup = entry
        if fam_name not in by_family:
            by_family[fam_name] = {}
            fam_order.append(fam_name)
        by_family[fam_name][tup] = coef

    terms: list[_FamilyTerm] = []
    for fam_name in fam_order:
        fam = families[fam_name]
        fam_coefs = by_family[fam_name]
        tuples = list(fam_coefs)
        fixed: list[tuple[int, str]] = []
        summed: list[int] = []
        for pos in range(fam.arity):
            pos_values = {tup[pos] for tup in tuples}
            if len(pos_values) == 1:
                fixed.append((pos, next(iter(pos_values))))
            elif pos_values == set(fam.position_values[pos]):
                summed.append(pos)
            else:
                raise _DegroundError("constraint spans a partial set of a family")
        # The summed positions must be a COMPLETE sum over their sets (``summed`` may
        # be empty — a per-element term like ``z[j]``).
        expected = 1
        for pos in summed:
            expected *= len(fam.position_values[pos])
        if len(fam_coefs) != expected:
            raise _DegroundError("constraint is not a complete sum over a family")
        terms.append(_FamilyTerm(fam_name, tuple(fixed), tuple(summed), dict(fam_coefs)))

    return _ConstraintShape(tuple(terms), parsed.operator, parsed.rhs)


def _emit_constraint_group(
    cname: str,
    group: list[_ConstraintShape],
    families: dict[str, _Family],
    sets: _SetRegistry,
) -> tuple[str, list[_ParamRecord]]:
    first = group[0]
    params: list[_ParamRecord] = []

    # 1) Free-index classes: fixed slots (family, position) whose member CO-VARIES
    #    across the group are the same ∀-quantified index. Two slots are the same
    #    index iff they hold identical members in every constraint of the group.
    slots = [(t.family, pos) for t in first.terms for pos, _ in t.fixed]
    slot_sig = {slot: tuple(_slot_member(s, *slot) for s in group) for slot in slots}

    # 2) Letters: scan families/positions in order; a fixed slot reuses its class's
    #    letter, a summed slot takes a fresh one. This reproduces the natural form
    #    ``sum{i in I} a[i, j] + z[j]``.
    pool = iter(_INDEX_LETTERS)
    class_letter: dict[tuple[str, ...], str] = {}
    letter: dict[tuple[str, int], str] = {}
    for term in first.terms:
        fam = families[term.family]
        fixed_pos = {p for p, _ in term.fixed}
        for pos in range(fam.arity):
            if pos in fixed_pos:
                sig = slot_sig[(term.family, pos)]
                if sig not in class_letter:
                    class_letter[sig] = _next_letter(pool)
                letter[(term.family, pos)] = class_letter[sig]
            else:
                letter[(term.family, pos)] = _next_letter(pool)

    # 3) ∀ bindings, one per free class. A class must map to ONE set and its members
    #    must cover that set (so a plain ∀ with no filter is faithful).
    free_classes: list[tuple[tuple[str, ...], str, list[str], tuple[str, int]]] = []
    for sig, lett in class_letter.items():
        rep = next(slot for slot in slots if slot_sig[slot] == sig)
        set_values = families[rep[0]].position_values[rep[1]]
        for slot in slots:
            if slot_sig[slot] == sig:
                other = families[slot[0]].position_values[slot[1]]
                if set(other) != set(set_values):
                    raise _DegroundError("a shared free index maps to different sets")
        if set(sig) != set(set_values):
            raise _DegroundError("constraint family does not cover its free index set")
        free_classes.append((sig, lett, set_values, rep))
    forall = [f"{lett} in {sets.name_for(sv)}" for _, lett, sv, _ in free_classes]

    # 4) One expression term per family — a sum (or a bare ref) over its summed
    #    positions, with a unit / constant / param coefficient.
    term_strs: list[str] = []
    for term in first.terms:
        fam = families[term.family]
        combined: dict[tuple[str, ...], float] = {}
        for shape in group:
            match = next(t for t in shape.terms if t.family == term.family)
            combined.update(match.coef_by_tuple)
        if len(combined) != len(fam.by_tuple):
            raise _DegroundError("constraint family does not cover the variable block")
        letters = [letter[(term.family, p)] for p in range(fam.arity)]
        ref = f"{term.family}[{', '.join(letters)}]"
        sum_parts = [
            f"{letter[(term.family, p)]} in {sets.name_for(fam.position_values[p])}"
            for p in term.summed
        ]
        sum_prefix = f"sum{{{', '.join(sum_parts)}}} " if term.summed else ""
        distinct = {round(c, 9) for c in combined.values()}
        if distinct == {1.0}:
            term_strs.append(f"{sum_prefix}{ref}")
        elif distinct == {-1.0}:
            term_strs.append(f"- {sum_prefix}{ref}")
        elif len(distinct) == 1:
            term_strs.append(f"{_num(next(iter(distinct)))} * {sum_prefix}{ref}")
        else:
            pname = f"a_{cname}_{term.family}"
            params.append(_param_record(pname, fam, sets, combined))
            term_strs.append(f"{sum_prefix}{pname}[{', '.join(letters)}] * {ref}")
    lhs = " + ".join(term_strs).replace("+ - ", "- ")

    # 5) rhs: uniform → a literal, otherwise a param over the free indices.
    rhs_values = {round(s.rhs, 9) for s in group}
    if len(rhs_values) == 1:
        rhs_str = _num(next(iter(rhs_values)))
    elif free_classes:
        pname = f"r_{cname}"
        params.append(_rhs_param_record(pname, group, free_classes, sets))
        rhs_str = f"{pname}[{', '.join(lett for _, lett, _, _ in free_classes)}]"
    else:
        raise _DegroundError("scalar constraint has a varying rhs but no free index")

    head = f"subject to {cname}"
    if forall:
        head += f"{{{', '.join(forall)}}}"
    return f"{head}: {lhs} {first.operator} {rhs_str};", params


# --------------------------------------------------------------------------- #
# Params & helpers
# --------------------------------------------------------------------------- #


def _param_record(
    pname: str, fam: _Family, sets: _SetRegistry, coef_by_tuple: dict[tuple[str, ...], float]
) -> _ParamRecord:
    index_sets = tuple(sets.name_for(values) for values in fam.position_values)
    entries = {tup: coef_by_tuple[tup] for tup in _cartesian(fam.position_values)}
    return _ParamRecord(name=pname, index_sets=index_sets, entries=entries)


def _slot_member(shape: _ConstraintShape, family: str, pos: int) -> str:
    """The member a constraint holds constant at one family's fixed position."""
    for term in shape.terms:
        if term.family == family:
            return dict(term.fixed)[pos]
    raise _DegroundError("inconsistent constraint group")


def _rhs_param_record(
    pname: str,
    group: list[_ConstraintShape],
    free_classes: list[tuple[tuple[str, ...], str, list[str], tuple[str, int]]],
    sets: _SetRegistry,
) -> _ParamRecord:
    """A per-constraint rhs param indexed by the ∀ free-index classes."""
    index_sets = tuple(sets.name_for(sv) for _, _, sv, _ in free_classes)
    # The free indices must uniquely key each constraint; a collision means the group
    # holds hidden structure a plain ∀ can't reproduce, so decline (round-trip-safe).
    by_key: dict[tuple[str, ...], float] = {}
    for shape in group:
        key = tuple(_slot_member(shape, rep[0], rep[1]) for _, _, _, rep in free_classes)
        if key in by_key and round(by_key[key], 9) != round(shape.rhs, 9):
            raise _DegroundError("constraint family free indices are not unique")
        by_key[key] = shape.rhs
    return _ParamRecord(name=pname, index_sets=index_sets, entries=by_key)


def _binding(fam: _Family, sets: _SetRegistry, letters: list[str]) -> str:
    return ", ".join(
        f"{letters[p]} in {sets.name_for(fam.position_values[p])}" for p in range(fam.arity)
    )


def _next_letter(pool) -> str:
    """Next free index letter — a constraint needing more than the pool declines
    (a ``_DegroundError``, caught by the caller) instead of leaking StopIteration."""
    try:
        return next(pool)
    except StopIteration:
        raise _DegroundError("constraint needs more index letters than available") from None


def _index_letters(arity: int) -> list[str]:
    if arity > len(_INDEX_LETTERS):
        raise _DegroundError(f"family arity {arity} exceeds the index-letter pool")
    return [_INDEX_LETTERS[p] for p in range(arity)]


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
