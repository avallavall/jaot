"""JModel compiler — lexer + recursive-descent parser + deterministic lowering.

Public API::

    compile_jmodel(src: str) -> OptimizationProblem

Raises :class:`JModelError` (with a source position when available) on any lex, parse,
or grounding error. The compiler is pure: it depends only on the standard library and
:mod:`app.schemas.optimization`.

See ``.claude/plans/jmodel-grammar-2026-07-01.md`` for the frozen grammar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import product

from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)


class JModelError(Exception):
    """A lex, parse, or grounding error in a JModel source.

    ``position`` is the 0-based character offset in the source when known, else ``None``.
    """

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position


# --------------------------------------------------------------------------- #
# Lexer
# --------------------------------------------------------------------------- #

_TOKEN_SPEC: list[tuple[str, str]] = [
    ("WS", r"[ \t\r\n]+"),
    ("COMMENT", r"#[^\n]*"),
    ("NUM", r"\d+\.\d+|\.\d+|\d+"),
    ("OP", r":=|<=|>=|==|!=|[<>=]|[-+*{}\[\](),;:]"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
]
_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in _TOKEN_SPEC))

_TYPE_KEYWORDS = {"binary", "integer", "continuous"}
_REL_OPS = {"<=", ">=", "=="}
_FILTER_OPS = {"!=", "==", "<", ">", "<=", ">="}


@dataclass(frozen=True)
class Token:
    kind: str  # NUM | OP | IDENT | EOF
    value: str
    pos: int


def tokenize(src: str) -> list[Token]:
    """Split JModel source into tokens (comments and whitespace dropped)."""
    tokens: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        match = _MASTER_RE.match(src, i)
        if match is None:
            raise JModelError(f"illegal character {src[i]!r}", position=i)
        kind = match.lastgroup or ""
        value = match.group()
        i = match.end()
        if kind in ("WS", "COMMENT"):
            continue
        if kind == "OP" and value == "=":  # a lone '=' means '=='
            value = "=="
        tokens.append(Token(kind, value, match.start()))
    tokens.append(Token("EOF", "", n))
    return tokens


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #


@dataclass
class Num:
    value: float


@dataclass
class Ref:
    name: str
    idx: list[Token]  # index tokens: bound index-vars, NUM literals, or member literals


@dataclass
class Neg:
    expr: Expr


@dataclass
class BinOp:
    op: str  # + | - | *
    left: Expr
    right: Expr


@dataclass
class Sum:
    quals: Qualifiers
    body: Expr


Expr = Num | Ref | Neg | BinOp | Sum


@dataclass
class Qualifiers:
    bindings: list[tuple[str, str]]  # (index_var, set_name)
    filters: list[tuple[Token, str, Token]]  # (left, op, right)


@dataclass
class SetDecl:
    name: str
    members: list[str]


@dataclass
class ParamDecl:
    name: str
    index_sets: list[str]  # [] => scalar
    data: dict[tuple[str, ...], float]  # scalar stored under key ()


@dataclass
class VarDecl:
    name: str
    index_sets: list[str]
    vtype: str
    lb: float | None
    ub: float | None


@dataclass
class ObjectiveDecl:
    sense: str  # minimize | maximize
    name: str
    expr: Expr


@dataclass
class ConstraintDecl:
    name: str
    quals: Qualifiers
    lhs: Expr
    op: str  # <= | >= | ==
    rhs: Expr


@dataclass
class ModelAst:
    sets: dict[str, list[str]] = field(default_factory=dict)
    params: dict[str, ParamDecl] = field(default_factory=dict)
    vars: dict[str, VarDecl] = field(default_factory=dict)
    var_order: list[str] = field(default_factory=list)
    objective: ObjectiveDecl | None = None
    constraints: list[ConstraintDecl] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parser (recursive descent)
# --------------------------------------------------------------------------- #


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._toks = tokens
        self._i = 0

    def _peek(self) -> Token:
        return self._toks[self._i]

    def _advance(self) -> Token:
        tok = self._toks[self._i]
        self._i += 1
        return tok

    def _error(self, msg: str) -> JModelError:
        tok = self._peek()
        detail = (
            f"{msg} (got {tok.kind} {tok.value!r})"
            if tok.kind != "EOF"
            else f"{msg} (got end of input)"
        )
        return JModelError(detail, position=tok.pos)

    def _expect_op(self, value: str) -> None:
        tok = self._advance()
        if tok.kind != "OP" or tok.value != value:
            raise self._error(f"expected {value!r}")

    def _accept_op(self, value: str) -> bool:
        tok = self._peek()
        if tok.kind == "OP" and tok.value == value:
            self._advance()
            return True
        return False

    def _expect_ident(self) -> str:
        tok = self._advance()
        if tok.kind != "IDENT":
            raise JModelError(f"expected identifier (got {tok.value!r})", position=tok.pos)
        return tok.value

    def _accept_kw(self, keyword: str) -> bool:
        tok = self._peek()
        if tok.kind == "IDENT" and tok.value == keyword:
            self._advance()
            return True
        return False

    def _expect_kw(self, keyword: str) -> None:
        if not self._accept_kw(keyword):
            raise self._error(f"expected keyword {keyword!r}")

    def _signed_number(self) -> float:
        negative = self._accept_op("-")
        tok = self._advance()
        if tok.kind != "NUM":
            raise JModelError(f"expected number (got {tok.value!r})", position=tok.pos)
        return -float(tok.value) if negative else float(tok.value)

    def _member(self) -> str:
        tok = self._advance()
        if tok.kind not in ("IDENT", "NUM"):
            raise JModelError(
                f"expected a set member (identifier or number, got {tok.value!r})", position=tok.pos
            )
        return tok.value

    # -- top level --
    def parse(self) -> ModelAst:
        model = ModelAst()
        while self._peek().kind != "EOF":
            keyword = self._peek().value
            if keyword == "set":
                self._parse_set(model)
            elif keyword == "param":
                self._parse_param(model)
            elif keyword == "var":
                self._parse_var(model)
            elif keyword in ("minimize", "maximize"):
                self._parse_objective(model)
            elif keyword == "subject":
                self._parse_constraint(model)
            else:
                raise self._error(
                    "expected a statement (set / param / var / minimize / maximize / subject to)"
                )
        if model.objective is None:
            raise JModelError("model has no objective")
        return model

    def _parse_set(self, model: ModelAst) -> None:
        self._expect_kw("set")
        name = self._expect_ident()
        self._expect_op(":=")
        self._expect_op("{")
        members: list[str] = []
        if not self._accept_op("}"):
            members.append(self._member())
            while self._accept_op(","):
                members.append(self._member())
            self._expect_op("}")
        self._expect_op(";")
        if name in model.sets:
            raise JModelError(f"duplicate set {name!r}")
        if len(members) != len(set(members)):
            raise JModelError(f"set {name!r} has duplicate members")
        model.sets[name] = members

    def _parse_index_sets(self) -> list[str]:
        sets = [self._expect_ident()]
        while self._accept_op(","):
            sets.append(self._expect_ident())
        return sets

    def _parse_param(self, model: ModelAst) -> None:
        self._expect_kw("param")
        name = self._expect_ident()
        index_sets: list[str] = []
        if self._accept_op("{"):
            index_sets = self._parse_index_sets()
            self._expect_op("}")
        self._expect_op(":=")
        data: dict[tuple[str, ...], float] = {}
        if not index_sets:
            data[()] = self._signed_number()
            self._expect_op(";")
        else:
            arity = len(index_sets)
            while True:
                key = tuple(self._member() for _ in range(arity))
                data[key] = self._signed_number()
                if self._accept_op(","):
                    continue
                break
            self._expect_op(";")
        if name in model.params:
            raise JModelError(f"duplicate param {name!r}")
        model.params[name] = ParamDecl(name, index_sets, data)

    def _parse_var(self, model: ModelAst) -> None:
        self._expect_kw("var")
        name = self._expect_ident()
        index_sets: list[str] = []
        if self._accept_op("{"):
            index_sets = self._parse_index_sets()
            self._expect_op("}")
        vtype = "continuous"
        lb: float | None = None
        ub: float | None = None
        while not (self._peek().kind == "OP" and self._peek().value == ";"):
            tok = self._peek()
            if tok.kind == "IDENT" and tok.value in _TYPE_KEYWORDS:
                vtype = self._advance().value
            elif tok.kind == "OP" and tok.value == ">=":
                self._advance()
                lb = self._signed_number()
            elif tok.kind == "OP" and tok.value == "<=":
                self._advance()
                ub = self._signed_number()
            else:
                raise self._error("expected variable type, a bound (>= / <=), or ';'")
        self._expect_op(";")
        if vtype == "binary":
            lb, ub = 0.0, 1.0
        if name in model.vars:
            raise JModelError(f"duplicate variable family {name!r}")
        model.vars[name] = VarDecl(name, index_sets, vtype, lb, ub)
        model.var_order.append(name)

    def _parse_objective(self, model: ModelAst) -> None:
        sense = self._advance().value  # minimize | maximize
        name = self._expect_ident()
        self._expect_op(":")
        expr = self._parse_expr()
        self._expect_op(";")
        if model.objective is not None:
            raise JModelError("multiple objectives are not supported")
        model.objective = ObjectiveDecl(sense, name, expr)

    def _parse_constraint(self, model: ModelAst) -> None:
        self._expect_kw("subject")
        self._expect_kw("to")
        name = self._expect_ident()
        quals = Qualifiers([], [])
        if self._accept_op("{"):
            quals = self._parse_qualifiers()
            self._expect_op("}")
        self._expect_op(":")
        lhs = self._parse_expr()
        op_tok = self._advance()
        if op_tok.kind != "OP" or op_tok.value not in _REL_OPS:
            raise JModelError(
                f"expected a relational operator (<=, >=, ==) in constraint {name!r} "
                f"(got {op_tok.value!r})",
                position=op_tok.pos,
            )
        rhs = self._parse_expr()
        self._expect_op(";")
        model.constraints.append(ConstraintDecl(name, quals, lhs, op_tok.value, rhs))

    def _parse_qualifiers(self) -> Qualifiers:
        bindings: list[tuple[str, str]] = []
        while True:
            index_var = self._expect_ident()
            self._expect_kw("in")
            set_name = self._expect_ident()
            bindings.append((index_var, set_name))
            if self._accept_op(","):
                continue
            break
        filters: list[tuple[Token, str, Token]] = []
        if self._accept_op(":"):
            while True:
                filters.append(self._parse_condition())
                if self._accept_kw("and"):
                    continue
                break
        return Qualifiers(bindings, filters)

    def _parse_condition(self) -> tuple[Token, str, Token]:
        left = self._parse_idx_term()
        op_tok = self._advance()
        if op_tok.kind != "OP" or op_tok.value not in _FILTER_OPS:
            raise JModelError(
                f"expected a comparison operator in filter (got {op_tok.value!r})",
                position=op_tok.pos,
            )
        right = self._parse_idx_term()
        return (left, op_tok.value, right)

    def _parse_idx_term(self) -> Token:
        tok = self._advance()
        if tok.kind not in ("IDENT", "NUM"):
            raise JModelError(
                f"expected an index term (identifier or number, got {tok.value!r})",
                position=tok.pos,
            )
        return tok

    # -- expressions --
    def _parse_expr(self) -> Expr:
        node = self._parse_term()
        while self._peek().kind == "OP" and self._peek().value in ("+", "-"):
            op = self._advance().value
            node = BinOp(op, node, self._parse_term())
        return node

    def _parse_term(self) -> Expr:
        node = self._parse_factor()
        while self._peek().kind == "OP" and self._peek().value == "*":
            self._advance()
            node = BinOp("*", node, self._parse_factor())
        return node

    def _parse_factor(self) -> Expr:
        tok = self._peek()
        if tok.kind == "OP" and tok.value == "-":
            self._advance()
            return Neg(self._parse_factor())
        if tok.kind == "OP" and tok.value == "+":
            self._advance()
            return self._parse_factor()
        if tok.kind == "OP" and tok.value == "(":
            self._advance()
            node = self._parse_expr()
            self._expect_op(")")
            return node
        if tok.kind == "NUM":
            self._advance()
            return Num(float(tok.value))
        if tok.kind == "IDENT":
            if tok.value == "sum":
                self._advance()
                self._expect_op("{")
                quals = self._parse_qualifiers()
                self._expect_op("}")
                body = self._parse_term()  # sum binds to the following term (AMPL precedence)
                return Sum(quals, body)
            name = self._advance().value
            idx: list[Token] = []
            if self._accept_op("["):
                idx.append(self._parse_idx_term())
                while self._accept_op(","):
                    idx.append(self._parse_idx_term())
                self._expect_op("]")
            return Ref(name, idx)
        raise self._error("expected a number, variable, param, sum, or '('")


# --------------------------------------------------------------------------- #
# Grounding / lowering
# --------------------------------------------------------------------------- #


@dataclass
class _LinForm:
    """A grounded linear form: sum(coeff * var) + const, ordered by first appearance."""

    coeffs: dict[str, float]
    const: float

    @staticmethod
    def number(value: float) -> _LinForm:
        return _LinForm({}, float(value))

    @staticmethod
    def variable(name: str) -> _LinForm:
        return _LinForm({name: 1.0}, 0.0)

    def is_const(self) -> bool:
        return all(c == 0 for c in self.coeffs.values())

    def scaled(self, k: float) -> _LinForm:
        return _LinForm({v: c * k for v, c in self.coeffs.items()}, self.const * k)

    def plus(self, other: _LinForm) -> _LinForm:
        merged = dict(self.coeffs)
        for var, coef in other.coeffs.items():
            merged[var] = merged.get(var, 0.0) + coef
        return _LinForm(merged, self.const + other.const)

    def minus(self, other: _LinForm) -> _LinForm:
        return self.plus(other.scaled(-1.0))


def _mangle(name: str, members: list[str]) -> str:
    if not members:
        return name
    parts = [re.sub(r"[^A-Za-z0-9_]", "_", m) for m in members]
    return name + "_" + "_".join(parts)


def _resolve_idx(tok: Token, env: dict[str, str]) -> str:
    if tok.kind == "IDENT" and tok.value in env:
        return env[tok.value]
    return tok.value  # NUM literal or bare set-member literal


def _as_number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _compare(left: str, op: str, right: str) -> bool:
    left_num, right_num = _as_number(left), _as_number(right)
    if op in ("==", "!="):
        if left_num is not None and right_num is not None:
            equal = left_num == right_num
        else:
            equal = left == right
        return equal if op == "==" else not equal
    if left_num is None or right_num is None:
        raise JModelError(
            f"ordering filter {op!r} needs numeric index terms, got {left!r} {right!r}"
        )
    if op == "<":
        return left_num < right_num
    if op == ">":
        return left_num > right_num
    if op == "<=":
        return left_num <= right_num
    return left_num >= right_num


def _iter_env(quals: Qualifiers, base_env: dict[str, str], model: ModelAst) -> list[dict[str, str]]:
    member_lists: list[list[str]] = []
    for _, set_name in quals.bindings:
        if set_name not in model.sets:
            raise JModelError(f"unknown set {set_name!r} in qualifier")
        member_lists.append(model.sets[set_name])
    envs: list[dict[str, str]] = []
    for combo in product(*member_lists):
        env = dict(base_env)
        for (index_var, _), member in zip(quals.bindings, combo, strict=True):
            env[index_var] = member
        if all(
            _compare(_resolve_idx(left, env), op, _resolve_idx(right, env))
            for left, op, right in quals.filters
        ):
            envs.append(env)
    return envs


def _ground(node: Expr, env: dict[str, str], model: ModelAst) -> _LinForm:
    if isinstance(node, Num):
        return _LinForm.number(node.value)
    if isinstance(node, Neg):
        return _ground(node.expr, env, model).scaled(-1.0)
    if isinstance(node, BinOp):
        left = _ground(node.left, env, model)
        right = _ground(node.right, env, model)
        if node.op == "+":
            return left.plus(right)
        if node.op == "-":
            return left.minus(right)
        if left.is_const():
            return right.scaled(left.const)
        if right.is_const():
            return left.scaled(right.const)
        raise JModelError("nonlinear term (variable * variable) is out of scope")
    if isinstance(node, Sum):
        acc = _LinForm.number(0.0)
        for env2 in _iter_env(node.quals, env, model):
            acc = acc.plus(_ground(node.body, env2, model))
        return acc
    # Ref
    members = [_resolve_idx(tok, env) for tok in node.idx]
    if node.name in model.vars:
        var_decl = model.vars[node.name]
        if len(members) != len(var_decl.index_sets):
            raise JModelError(
                f"variable {node.name!r} indexed with {len(members)} subscript(s), "
                f"expected {len(var_decl.index_sets)}"
            )
        return _LinForm.variable(_mangle(node.name, members))
    if node.name in model.params:
        param_decl = model.params[node.name]
        if len(members) != len(param_decl.index_sets):
            raise JModelError(
                f"param {node.name!r} indexed with {len(members)} subscript(s), "
                f"expected {len(param_decl.index_sets)}"
            )
        key = tuple(members)
        if key not in param_decl.data:
            raise JModelError(f"param {node.name!r} has no value for index {key}")
        return _LinForm.number(param_decl.data[key])
    raise JModelError(f"unknown symbol {node.name!r}")


def _fmt_num(x: float) -> str:
    if x == int(x):
        return str(int(x))
    return f"{x:g}"


def _fmt_linform(lf: _LinForm, include_const: bool) -> str:
    parts: list[tuple[bool, str]] = []
    for var, coef in lf.coeffs.items():
        if coef == 0:
            continue
        magnitude = _fmt_num(abs(coef))
        term = var if abs(coef) == 1 else f"{magnitude}*{var}"
        parts.append((coef < 0, term))
    if include_const and lf.const != 0:
        parts.append((lf.const < 0, _fmt_num(abs(lf.const))))
    if not parts:
        return "0"
    out = ("-" if parts[0][0] else "") + parts[0][1]
    for negative, term in parts[1:]:
        out += (" - " if negative else " + ") + term
    return out


def _lower(model: ModelAst) -> OptimizationProblem:
    assert model.objective is not None  # guaranteed by parse()

    # 1. variables — full cartesian expansion of every declared family
    variables: list[Variable] = []
    seen: set[str] = set()
    for name in model.var_order:
        decl = model.vars[name]
        member_lists = [model.sets[s] for s in decl.index_sets]
        combos = product(*member_lists) if member_lists else [()]
        for combo in combos:
            flat = _mangle(name, list(combo))
            if flat in seen:
                raise JModelError(f"variable name collision after mangling: {flat!r}")
            seen.add(flat)
            variables.append(
                Variable(
                    name=flat,
                    type=VariableType(decl.vtype),
                    lower_bound=decl.lb,
                    upper_bound=decl.ub,
                )
            )

    # 2. objective
    obj = model.objective
    obj_form = _ground(obj.expr, {}, model)
    objective = Objective(
        sense=ObjectiveSense(obj.sense),
        expression=_fmt_linform(obj_form, include_const=True),
    )

    # 3. constraints — ground each family member
    constraints: list[Constraint] = []
    for con in model.constraints:
        for env in _iter_env(con.quals, {}, model):
            combined = _ground(con.lhs, env, model).minus(_ground(con.rhs, env, model))
            lhs_str = _fmt_linform(_LinForm(combined.coeffs, 0.0), include_const=False)
            rhs_num = _fmt_num(-combined.const)
            suffix = [env[index_var] for index_var, _ in con.quals.bindings]
            constraints.append(
                Constraint(
                    name=_mangle(con.name, suffix),
                    expression=f"{lhs_str} {con.op} {rhs_num}",
                )
            )

    return OptimizationProblem(
        name=obj.name,
        variables=variables,
        objective=objective,
        constraints=constraints,
    )


def compile_jmodel(src: str) -> OptimizationProblem:
    """Parse and lower JModel source into a flat :class:`OptimizationProblem`.

    Raises :class:`JModelError` on any lex, parse, or grounding error.
    """
    model = _Parser(tokenize(src)).parse()
    return _lower(model)
