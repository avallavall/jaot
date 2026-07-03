"""JModel compiler — lexer + recursive-descent parser + deterministic lowering.

Public API::

    compile_jmodel(src: str, data: JModelData | None = None) -> OptimizationProblem
    JModelData.from_json(payload)  # validate a {"sets": ..., "params": ...} bundle

Raises :class:`JModelError` (with a source position when available) on any lex, parse,
or grounding error. The compiler is pure: it depends only on the standard library and
:mod:`app.schemas.optimization`.

Model/data separation (§8 Scenarios): ``set I;`` and ``param w{I};`` — with no ``:=``
body — DECLARE structure whose values must come from a dataset (:class:`JModelData`).
A dataset may also override an inline ``:=`` default, always replacing the WHOLE
symbol (never a per-key merge). A dataset key the model does not declare is an error
(a typo'd name must never silently fall back to the inline value), and a declared
set/param that ends up with no values is an error naming the missing symbol.

Hardening guarantees (all violations raise :class:`JModelError`, never a raw exception):

- every referenced set/param/variable must be declared; every resolved index member must
  belong to the family's declared index set (no "ghost" flat variables);
- grounding work is bounded by an expansion budget (``max_grounded_elements``) checked
  *before* cartesian products are materialized;
- emitted numbers are always plain positional decimals (the flat ``ExpressionParser``
  does not understand scientific notation);
- constant constraint rows are dropped when trivially satisfied and rejected at compile
  time when violated by construction.

See ``.claude/plans/jmodel-grammar-2026-07-01.md`` for the frozen grammar.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import product

from app.schemas.optimization import (
    Constraint,
    Objective,
    ObjectiveSense,
    OptimizationProblem,
    Variable,
    VariableType,
)

#: Hard cap on grounded work per compile: expanded variables + constraint rows + summed
#: terms. Generous for real models (the largest TFM scenario is ~49k variables) while
#: rejecting accidental combinatorial blowups (three-index families over large sets)
#: before they pin a CPU.
MAX_GROUNDED_ELEMENTS = 500_000

#: Maximum expression nesting depth (parens / unary signs / sum bodies) before the
#: parser refuses — keeps pathological sources from hitting Python's recursion limit.
_MAX_EXPR_DEPTH = 200

#: Words with grammatical meaning; rejected as set/param/var/objective/constraint names
#: and as index variables so a model can never shadow the language.
_RESERVED_WORDS = {
    "set",
    "param",
    "var",
    "minimize",
    "maximize",
    "subject",
    "to",
    "in",
    "and",
    "sum",
    "binary",
    "integer",
    "continuous",
}


class JModelError(Exception):
    """A lex, parse, or grounding error in a JModel source.

    ``position`` is the 0-based character offset in the source when known, else ``None``.
    """

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position


@dataclass(frozen=True)
class JModelData:
    """A validated model↔data bundle: set members and param values for a JModel source.

    This is what a named dataset ("scenario") carries. Build one from its stored JSON
    with :meth:`from_json`; pass it to :func:`compile_jmodel`. Scalar param values are
    stored under the empty key ``()``; an N-dim value key is a tuple of members.
    """

    sets: dict[str, list[str]]
    params: dict[str, dict[tuple[str, ...], float]]

    @staticmethod
    def from_json(payload: object) -> JModelData:
        """Validate and normalize a ``{"sets": {...}, "params": {...}}`` JSON object.

        Set members are strings or integers. A param value is either a single number
        (scalar param) or an object mapping comma-joined index keys to numbers
        (``{"A,1": 4}`` — members never contain commas, so the join is unambiguous).
        Raises :class:`JModelError` on any shape violation.
        """
        if not isinstance(payload, dict):
            raise JModelError("dataset must be a JSON object with 'sets' and/or 'params'")
        unknown = set(payload) - {"sets", "params"}
        if unknown:
            raise JModelError(
                f"dataset has unknown top-level key(s) {sorted(unknown)!r} — "
                "only 'sets' and 'params' are allowed"
            )
        sets: dict[str, list[str]] = {}
        raw_sets = payload.get("sets", {})
        if not isinstance(raw_sets, dict):
            raise JModelError("dataset 'sets' must be an object of set name -> member list")
        for name, raw_members in raw_sets.items():
            if not isinstance(raw_members, list):
                raise JModelError(f"dataset set {name!r} must be a list of members")
            sets[name] = [_data_member(name, m) for m in raw_members]
        params: dict[str, dict[tuple[str, ...], float]] = {}
        raw_params = payload.get("params", {})
        if not isinstance(raw_params, dict):
            raise JModelError("dataset 'params' must be an object of param name -> value(s)")
        for name, raw_value in raw_params.items():
            if isinstance(raw_value, bool):
                raise JModelError(f"dataset param {name!r} must be a number, not a boolean")
            if isinstance(raw_value, (int, float)):
                params[name] = {(): _data_number(name, raw_value)}
                continue
            if not isinstance(raw_value, dict):
                raise JModelError(
                    f"dataset param {name!r} must be a number (scalar) or an object "
                    "of index keys to numbers"
                )
            values: dict[tuple[str, ...], float] = {}
            for raw_key, raw_num in raw_value.items():
                key = _data_key(name, raw_key)
                if key in values:
                    raise JModelError(
                        f"dataset param {name!r} has duplicate entries for key {','.join(key)!r}"
                    )
                values[key] = _data_number(name, raw_num)
            params[name] = values
        return JModelData(sets=sets, params=params)


def _data_member(set_name: str, raw: object) -> str:
    """A set member from dataset JSON: a non-empty string (comma-free) or an integer."""
    if isinstance(raw, bool):
        raise JModelError(f"dataset set {set_name!r} has a boolean member — use strings/integers")
    if isinstance(raw, int):
        return str(raw)
    if not isinstance(raw, str):
        raise JModelError(
            f"dataset set {set_name!r} members must be strings or integers (got {raw!r})"
        )
    member = raw.strip()
    if not member:
        raise JModelError(f"dataset set {set_name!r} has an empty member")
    if "," in member:
        raise JModelError(
            f"dataset set {set_name!r} member {raw!r} contains a comma — "
            "commas separate the members of a composite param key"
        )
    return member


def _data_key(param_name: str, raw: object) -> tuple[str, ...]:
    """A composite param key from dataset JSON: comma-joined members, e.g. ``\"A,1\"``."""
    if not isinstance(raw, str):
        raise JModelError(f"dataset param {param_name!r} keys must be strings (got {raw!r})")
    parts = tuple(part.strip() for part in raw.split(","))
    if any(not part for part in parts):
        raise JModelError(f"dataset param {param_name!r} key {raw!r} has an empty index member")
    return parts


def _data_number(param_name: str, raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise JModelError(f"dataset param {param_name!r} values must be numbers (got {raw!r})")
    value = float(raw)
    if not math.isfinite(value):
        raise JModelError(f"dataset param {param_name!r} has a non-finite value")
    return value


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
    pos: int = 0


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
    pos: int = 0


Expr = Num | Ref | Neg | BinOp | Sum


@dataclass
class Qualifiers:
    bindings: list[tuple[str, str, int]]  # (index_var, set_name, set_name_pos)
    filters: list[tuple[Token, str, Token]]  # (left, op, right)


@dataclass
class SetDecl:
    name: str
    members: list[str]


@dataclass
class ParamDecl:
    name: str
    index_sets: list[str]  # [] => scalar
    # scalar stored under key (); None => declared without values (dataset must fill)
    data: dict[tuple[str, ...], float] | None
    pos: int = 0


@dataclass
class VarDecl:
    name: str
    index_sets: list[str]
    vtype: str
    lb: float | None
    ub: float | None
    pos: int = 0


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
    pos: int = 0


@dataclass
class ModelAst:
    # a None member list => declared without values (dataset must fill)
    sets: dict[str, list[str] | None] = field(default_factory=dict)
    params: dict[str, ParamDecl] = field(default_factory=dict)
    vars: dict[str, VarDecl] = field(default_factory=dict)
    var_order: list[str] = field(default_factory=list)
    objective: ObjectiveDecl | None = None
    constraints: list[ConstraintDecl] = field(default_factory=list)

    def check_unused_name(self, name: str, position: int) -> None:
        """Reject a declaration whose name is already taken in ANY namespace.

        Sets, params and variables share one symbol space in expressions (a var
        shadowing a param would silently win the lookup), so collisions are errors.
        """
        for kind, names in (("set", self.sets), ("param", self.params), ("variable", self.vars)):
            if name in names:
                raise JModelError(
                    f"name {name!r} is already declared as a {kind}", position=position
                )


# --------------------------------------------------------------------------- #
# Parser (recursive descent)
# --------------------------------------------------------------------------- #


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._toks = tokens
        self._i = 0
        self._depth = 0

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

    def _expect_name(self) -> Token:
        """An identifier being *declared or bound* — reserved words are rejected."""
        tok = self._advance()
        if tok.kind != "IDENT":
            raise JModelError(f"expected identifier (got {tok.value!r})", position=tok.pos)
        if tok.value in _RESERVED_WORDS:
            raise JModelError(
                f"{tok.value!r} is a reserved word and cannot be used as a name",
                position=tok.pos,
            )
        return tok

    def _accept_kw(self, keyword: str) -> bool:
        tok = self._peek()
        if tok.kind == "IDENT" and tok.value == keyword:
            self._advance()
            return True
        return False

    def _expect_kw(self, keyword: str) -> None:
        if not self._accept_kw(keyword):
            raise self._error(f"expected keyword {keyword!r}")

    def _finite_number(self, tok: Token, text: str) -> float:
        value = float(text)
        if not math.isfinite(value):
            raise JModelError(f"number literal {text!r} is too large", position=tok.pos)
        return value

    def _signed_number(self) -> float:
        negative = self._accept_op("-")
        tok = self._advance()
        if tok.kind != "NUM":
            raise JModelError(f"expected number (got {tok.value!r})", position=tok.pos)
        value = self._finite_number(tok, tok.value)
        return -value if negative else value

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
        name_tok = self._expect_name()
        # `set I;` (no body) declares the set; its members must come from a dataset.
        if self._accept_op(";"):
            model.check_unused_name(name_tok.value, name_tok.pos)
            model.sets[name_tok.value] = None
            return
        self._expect_op(":=")
        self._expect_op("{")
        members: list[str] = []
        if not self._accept_op("}"):
            members.append(self._member())
            while self._accept_op(","):
                members.append(self._member())
            self._expect_op("}")
        self._expect_op(";")
        model.check_unused_name(name_tok.value, name_tok.pos)
        if len(members) != len(set(members)):
            raise JModelError(
                f"set {name_tok.value!r} has duplicate members", position=name_tok.pos
            )
        model.sets[name_tok.value] = members

    def _parse_index_sets(self) -> list[str]:
        sets = [self._expect_ident()]
        while self._accept_op(","):
            sets.append(self._expect_ident())
        return sets

    def _parse_param(self, model: ModelAst) -> None:
        self._expect_kw("param")
        name_tok = self._expect_name()
        index_sets: list[str] = []
        if self._accept_op("{"):
            index_sets = self._parse_index_sets()
            self._expect_op("}")
        # `param w{I};` (no body) declares the param; values must come from a dataset.
        if self._accept_op(";"):
            model.check_unused_name(name_tok.value, name_tok.pos)
            model.params[name_tok.value] = ParamDecl(name_tok.value, index_sets, None, name_tok.pos)
            return
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
        model.check_unused_name(name_tok.value, name_tok.pos)
        model.params[name_tok.value] = ParamDecl(name_tok.value, index_sets, data, name_tok.pos)

    def _parse_var(self, model: ModelAst) -> None:
        self._expect_kw("var")
        name_tok = self._expect_name()
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
        name = name_tok.value
        if vtype == "binary":
            if lb is not None or ub is not None:
                raise JModelError(
                    f"variable family {name!r} is binary — explicit bounds are not allowed "
                    "(binary is always [0, 1])",
                    position=name_tok.pos,
                )
            lb, ub = 0.0, 1.0
        if lb is not None and ub is not None and lb > ub:
            raise JModelError(
                f"variable family {name!r} has lower bound {lb:g} greater than upper bound {ub:g}",
                position=name_tok.pos,
            )
        model.check_unused_name(name, name_tok.pos)
        model.vars[name] = VarDecl(name, index_sets, vtype, lb, ub, name_tok.pos)
        model.var_order.append(name)

    def _parse_objective(self, model: ModelAst) -> None:
        sense = self._advance().value  # minimize | maximize
        name_tok = self._expect_name()
        self._expect_op(":")
        expr = self._parse_expr()
        self._expect_op(";")
        if model.objective is not None:
            raise JModelError("multiple objectives are not supported", position=name_tok.pos)
        model.objective = ObjectiveDecl(sense, name_tok.value, expr)

    def _parse_constraint(self, model: ModelAst) -> None:
        self._expect_kw("subject")
        self._expect_kw("to")
        name_tok = self._expect_name()
        quals = Qualifiers([], [])
        if self._accept_op("{"):
            quals = self._parse_qualifiers()
            self._expect_op("}")
        self._expect_op(":")
        lhs = self._parse_expr()
        op_tok = self._advance()
        if op_tok.kind != "OP" or op_tok.value not in _REL_OPS:
            raise JModelError(
                f"expected a relational operator (<=, >=, ==) in constraint {name_tok.value!r} "
                f"(got {op_tok.value!r})",
                position=op_tok.pos,
            )
        rhs = self._parse_expr()
        self._expect_op(";")
        model.constraints.append(
            ConstraintDecl(name_tok.value, quals, lhs, op_tok.value, rhs, name_tok.pos)
        )

    def _parse_qualifiers(self) -> Qualifiers:
        bindings: list[tuple[str, str, int]] = []
        while True:
            index_tok = self._expect_name()
            self._expect_kw("in")
            set_tok = self._advance()
            if set_tok.kind != "IDENT":
                raise JModelError(
                    f"expected a set name (got {set_tok.value!r})", position=set_tok.pos
                )
            bindings.append((index_tok.value, set_tok.value, set_tok.pos))
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
        self._depth += 1
        try:
            if self._depth > _MAX_EXPR_DEPTH:
                raise JModelError(
                    f"expression nesting deeper than {_MAX_EXPR_DEPTH} levels",
                    position=self._peek().pos,
                )
            return self._parse_factor_inner()
        finally:
            self._depth -= 1

    def _parse_factor_inner(self) -> Expr:
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
            return Num(self._finite_number(tok, tok.value))
        if tok.kind == "IDENT":
            if tok.value == "sum":
                self._advance()
                self._expect_op("{")
                quals = self._parse_qualifiers()
                self._expect_op("}")
                body = self._parse_term()  # sum binds to the following term (AMPL precedence)
                return Sum(quals, body, tok.pos)
            name = self._advance().value
            idx: list[Token] = []
            if self._accept_op("["):
                idx.append(self._parse_idx_term())
                while self._accept_op(","):
                    idx.append(self._parse_idx_term())
                self._expect_op("]")
            return Ref(name, idx, tok.pos)
        raise self._error("expected a number, variable, param, sum, or '('")


# --------------------------------------------------------------------------- #
# Dataset application (model ↔ data merge)
# --------------------------------------------------------------------------- #


def _apply_data(model: ModelAst, data: JModelData | None) -> None:
    """Fill the model's declared sets/params from a dataset, then require completeness.

    A dataset value replaces the WHOLE symbol (sets: the member list; params: every
    key) — there is no per-key merge, so a scenario can never half-override an inline
    default. Unknown dataset symbols are errors: a typo'd name must never silently
    leave the inline value in effect.
    """
    if data is not None:
        for name, members in data.sets.items():
            if name not in model.sets:
                raise JModelError(
                    f"dataset provides unknown set {name!r} — the model does not declare it"
                )
            if len(members) != len(set(members)):
                raise JModelError(f"dataset set {name!r} has duplicate members")
            model.sets[name] = list(members)
        for name, values in data.params.items():
            decl = model.params.get(name)
            if decl is None:
                raise JModelError(
                    f"dataset provides unknown param {name!r} — the model does not declare it"
                )
            arity = len(decl.index_sets)
            for key in values:
                if arity == 0 and key != ():
                    raise JModelError(
                        f"param {name!r} is scalar — the dataset value must be a single number"
                    )
                if arity > 0 and key == ():
                    raise JModelError(
                        f"param {name!r} is indexed over {arity} set(s) — the dataset value "
                        "must be an object of index keys to numbers"
                    )
                if len(key) != arity:
                    raise JModelError(
                        f"dataset param {name!r} key {','.join(key)!r} has {len(key)} "
                        f"member(s), expected {arity}"
                    )
            decl.data = dict(values)
    for name, members in model.sets.items():
        if members is None:
            raise JModelError(
                f"set {name!r} has no members — define them inline (:=) or provide a dataset"
            )
    for decl in model.params.values():
        if decl.data is None:
            raise JModelError(
                f"param {decl.name!r} has no values — define them inline (:=) or provide a dataset",
                position=decl.pos,
            )


# --------------------------------------------------------------------------- #
# Grounding / lowering
# --------------------------------------------------------------------------- #


@dataclass
class _Budget:
    """Grounding work budget: counts expanded variables, constraint rows and summed
    terms, and refuses (with a clear error) before a combinatorial blowup is built."""

    limit: int
    used: int = 0

    def consume(self, amount: int, position: int | None = None) -> None:
        self.used += amount
        if self.used > self.limit:
            raise JModelError(
                f"model expands to more than {self.limit:,} grounded elements — "
                "reduce set sizes or index dimensions",
                position=position,
            )


@dataclass
class _Ctx:
    """Grounding context: the parsed model plus membership caches and the budget."""

    model: ModelAst
    set_members: dict[str, frozenset[str]]
    all_members: frozenset[str]
    budget: _Budget

    @staticmethod
    def build(model: ModelAst, max_grounded_elements: int) -> _Ctx:
        # The `is not None` narrow is for the type only: _apply_data ran before any
        # lowering, so every declared set has members here.
        set_members = {
            name: frozenset(members) for name, members in model.sets.items() if members is not None
        }
        all_members: frozenset[str] = frozenset()
        if set_members:
            all_members = frozenset().union(*set_members.values())
        return _Ctx(model, set_members, all_members, _Budget(max_grounded_elements))


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


def _compare(left: str, op: str, right: str, position: int | None = None) -> bool:
    left_num, right_num = _as_number(left), _as_number(right)
    if op in ("==", "!="):
        if left_num is not None and right_num is not None:
            equal = left_num == right_num
        else:
            equal = left == right
        return equal if op == "==" else not equal
    if left_num is None or right_num is None:
        raise JModelError(
            f"ordering filter {op!r} needs numeric index terms, got {left!r} {right!r}",
            position=position,
        )
    if op == "<":
        return left_num < right_num
    if op == ">":
        return left_num > right_num
    if op == "<=":
        return left_num <= right_num
    return left_num >= right_num


def _validate_filter_terms(quals: Qualifiers, base_env: dict[str, str], ctx: _Ctx) -> None:
    """A filter identifier must be a bound index variable or a declared set member —
    anything else is a typo that would otherwise silently degrade to a literal string
    (making the filter a no-op)."""
    bound = set(base_env)
    bound.update(index_var for index_var, _, _ in quals.bindings)
    for left, _, right in quals.filters:
        for tok in (left, right):
            if tok.kind == "IDENT" and tok.value not in bound and tok.value not in ctx.all_members:
                raise JModelError(
                    f"unknown index {tok.value!r} in filter — not a bound index variable "
                    "or a declared set member",
                    position=tok.pos,
                )


def _iter_env(quals: Qualifiers, base_env: dict[str, str], ctx: _Ctx) -> list[dict[str, str]]:
    member_lists: list[list[str]] = []
    for _, set_name, set_pos in quals.bindings:
        members = ctx.model.sets.get(set_name)
        if members is None:
            raise JModelError(f"unknown set {set_name!r} in qualifier", position=set_pos)
        member_lists.append(members)
    _validate_filter_terms(quals, base_env, ctx)
    size = math.prod(len(m) for m in member_lists) if member_lists else 1
    first_pos = quals.bindings[0][2] if quals.bindings else None
    ctx.budget.consume(size, first_pos)
    envs: list[dict[str, str]] = []
    for combo in product(*member_lists):
        env = dict(base_env)
        for (index_var, _, _), member in zip(quals.bindings, combo, strict=True):
            env[index_var] = member
        if all(
            _compare(_resolve_idx(left, env), op, _resolve_idx(right, env), position=left.pos)
            for left, op, right in quals.filters
        ):
            envs.append(env)
    return envs


def _resolve_members(node: Ref, decl_sets: list[str], env: dict[str, str], ctx: _Ctx) -> list[str]:
    """Resolve a Ref's index tokens and verify each member belongs to the declared set
    at that position — a mismatch would otherwise emit a "ghost" name that exists in an
    expression but not in the declared variable expansion."""
    members = [_resolve_idx(tok, env) for tok in node.idx]
    for k, member in enumerate(members):
        set_name = decl_sets[k]
        if member not in ctx.set_members.get(set_name, frozenset()):
            raise JModelError(
                f"{node.name!r} index {member!r} is not a member of set {set_name!r}",
                position=node.pos,
            )
    return members


def _ground(node: Expr, env: dict[str, str], ctx: _Ctx) -> _LinForm:
    if isinstance(node, Num):
        return _LinForm.number(node.value)
    if isinstance(node, Neg):
        return _ground(node.expr, env, ctx).scaled(-1.0)
    if isinstance(node, BinOp):
        left = _ground(node.left, env, ctx)
        right = _ground(node.right, env, ctx)
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
        # Accumulate into one mutable dict — building an immutable _LinForm per term
        # would copy the growing dict on every step (quadratic in the sum's length).
        coeffs: dict[str, float] = {}
        const = 0.0
        for env2 in _iter_env(node.quals, env, ctx):
            form = _ground(node.body, env2, ctx)
            for var, coef in form.coeffs.items():
                coeffs[var] = coeffs.get(var, 0.0) + coef
            const += form.const
        return _LinForm(coeffs, const)
    # Ref
    model = ctx.model
    if node.name in model.vars:
        var_decl = model.vars[node.name]
        if len(node.idx) != len(var_decl.index_sets):
            raise JModelError(
                f"variable {node.name!r} indexed with {len(node.idx)} subscript(s), "
                f"expected {len(var_decl.index_sets)}",
                position=node.pos,
            )
        members = _resolve_members(node, var_decl.index_sets, env, ctx)
        return _LinForm.variable(_mangle(node.name, members))
    if node.name in model.params:
        param_decl = model.params[node.name]
        assert param_decl.data is not None  # guaranteed by _apply_data
        if len(node.idx) != len(param_decl.index_sets):
            raise JModelError(
                f"param {node.name!r} indexed with {len(node.idx)} subscript(s), "
                f"expected {len(param_decl.index_sets)}",
                position=node.pos,
            )
        members = _resolve_members(node, param_decl.index_sets, env, ctx)
        key = tuple(members)
        if key not in param_decl.data:
            raise JModelError(
                f"param {node.name!r} has no value for index {key}", position=node.pos
            )
        return _LinForm.number(param_decl.data[key])
    raise JModelError(f"unknown symbol {node.name!r}", position=node.pos)


def _fmt_num(x: float) -> str:
    """Format a number as a plain positional decimal.

    The flat ``ExpressionParser`` only understands digits and dots — scientific
    notation like ``1e-07`` would be misread as the variable ``e`` — so exponents are
    expanded via ``Decimal`` (exact, round-trips the float's shortest repr).
    """
    if not math.isfinite(x):
        raise JModelError("non-finite coefficient in model (numeric overflow)")
    if x == int(x):
        return str(int(x))
    s = repr(x)
    if "e" in s or "E" in s:
        s = format(Decimal(s), "f")
    return s


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


def _constant_row_is_satisfied(const: float, op: str) -> bool:
    """Truth of a fully-constant row ``const <op> 0`` (the grounded lhs-rhs form)."""
    if op == "<=":
        return const <= 0
    if op == ">=":
        return const >= 0
    return const == 0


def _lower(model: ModelAst, max_grounded_elements: int) -> OptimizationProblem:
    assert model.objective is not None  # guaranteed by parse()
    ctx = _Ctx.build(model, max_grounded_elements)

    # 1. variables — full cartesian expansion of every declared family
    variables: list[Variable] = []
    seen: set[str] = set()
    for name in model.var_order:
        decl = model.vars[name]
        member_lists: list[list[str]] = []
        for set_name in decl.index_sets:
            members = model.sets.get(set_name)
            if members is None:
                raise JModelError(
                    f"unknown set {set_name!r} in variable family {name!r}", position=decl.pos
                )
            member_lists.append(members)
        size = math.prod(len(m) for m in member_lists) if member_lists else 1
        ctx.budget.consume(size, decl.pos)
        combos = product(*member_lists) if member_lists else [()]
        for combo in combos:
            flat = _mangle(name, list(combo))
            if flat in seen:
                raise JModelError(
                    f"variable name collision after mangling: {flat!r}", position=decl.pos
                )
            seen.add(flat)
            variables.append(
                Variable(
                    name=flat,
                    type=VariableType(decl.vtype),
                    lower_bound=decl.lb,
                    upper_bound=decl.ub,
                )
            )

    # The flat schema requires at least one variable; grounding to zero (every family
    # expanded over an empty set) must be a clear compile error, not a downstream
    # Pydantic ValidationError the API can only report as "internal compiler error".
    if not variables:
        raise JModelError(
            "model grounds to zero variables — every variable family expands over an "
            "empty set (check the dataset's set members)"
        )

    # 1b. params — declared index sets must exist and every data key must be a member
    # of the corresponding set (a typo'd key would only surface — or worse, not — when
    # that exact index is referenced).
    for param in model.params.values():
        assert param.data is not None  # guaranteed by _apply_data
        member_sets: list[frozenset[str]] = []
        for set_name in param.index_sets:
            members_frozen = ctx.set_members.get(set_name)
            if members_frozen is None:
                raise JModelError(
                    f"unknown set {set_name!r} in param {param.name!r}", position=param.pos
                )
            member_sets.append(members_frozen)
        for key in param.data:
            for k, member in enumerate(key):
                if member not in member_sets[k]:
                    raise JModelError(
                        f"param {param.name!r} data key {key} has member {member!r} "
                        f"which is not in set {param.index_sets[k]!r}",
                        position=param.pos,
                    )

    # 2. objective
    obj = model.objective
    obj_form = _ground(obj.expr, {}, ctx)
    objective = Objective(
        sense=ObjectiveSense(obj.sense),
        expression=_fmt_linform(obj_form, include_const=True),
    )

    # 3. constraints — ground each family member
    constraints: list[Constraint] = []
    seen_constraints: set[str] = set()
    for con in model.constraints:
        for env in _iter_env(con.quals, {}, ctx):
            combined = _ground(con.lhs, env, ctx).minus(_ground(con.rhs, env, ctx))
            suffix = [env[index_var] for index_var, _, _ in con.quals.bindings]
            flat_name = _mangle(con.name, suffix)
            if combined.is_const():
                # A row with no variables (e.g. a sum emptied by its filters): keep the
                # problem clean by dropping trivially-true rows, and fail compile on a
                # row that is violated by construction — that is always an authoring bug.
                if _constant_row_is_satisfied(combined.const, con.op):
                    continue
                raise JModelError(
                    f"constraint {flat_name!r} is constant and violated "
                    f"({_fmt_num(combined.const)} {con.op} 0 is false)",
                    position=con.pos,
                )
            if flat_name in seen_constraints:
                raise JModelError(
                    f"constraint name collision after mangling: {flat_name!r}",
                    position=con.pos,
                )
            seen_constraints.add(flat_name)
            lhs_str = _fmt_linform(_LinForm(combined.coeffs, 0.0), include_const=False)
            rhs_num = _fmt_num(-combined.const)
            constraints.append(
                Constraint(
                    name=flat_name,
                    expression=f"{lhs_str} {con.op} {rhs_num}",
                )
            )

    return OptimizationProblem(
        name=obj.name,
        variables=variables,
        objective=objective,
        constraints=constraints,
    )


def compile_jmodel(
    src: str,
    *,
    data: JModelData | None = None,
    max_grounded_elements: int = MAX_GROUNDED_ELEMENTS,
) -> OptimizationProblem:
    """Parse and lower JModel source into a flat :class:`OptimizationProblem`.

    ``data`` (a named dataset / scenario) fills declaration-only sets/params and
    replaces inline defaults, whole-symbol. Raises :class:`JModelError` on any lex,
    parse, dataset, or grounding error, including a grounding expansion beyond
    ``max_grounded_elements``.
    """
    model = _Parser(tokenize(src)).parse()
    _apply_data(model, data)
    return _lower(model, max_grounded_elements)
