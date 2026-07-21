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

Tuple sets (S6 / DSL-expressivity #3): a set may hold N-dimensional members —
``set ARCS := {(a, b), (b, c)};`` inline, or ``set ARCS dimen 2;`` declaration-only
(``dimen`` defaults to 1, as in AMPL). Dataset members encode tuples as comma-joined
strings (``"a,b"``), the same composite-key encoding indexed param values use.
Qualifiers unpack them — ``sum{(i, j) in ARCS} d[i,j]*x[i,j]`` — and variables or
params indexed over a tuple set take the FLAT component count as subscripts
(``var x{ARCS, K};`` → ``x[i,j,k]``), expanding only over the set's actual members
(sparse, never the cartesian closure). Equality filters that pin a tuple component
to an already-known index (``sum{(i2, j) in ARCS : i2 == i}``) are applied as indexed
slices, so sparse formulations ground in linear — not quadratic — time and budget.

Ranges (DSL-expressivity #2): ``set T := 1..96;`` declares the 1-dimensional integer
members ``1..96`` inclusive, exactly as the equivalent brace literal would. Endpoints
are (optionally signed) integer literals; an empty (descending) range is an error.

Quadratic terms (DSL-expressivity #1): products of two variables (``x*y``, including
distributed products of linear sub-expressions like ``(x + y)^2``) and squares
(``x^2`` / ``x**2``) ground into degree-2 terms and are emitted as ``v1*v2`` /
``v^2`` strings — the flat ``ExpressionParser`` parses both, ``classify()`` reports
QP/MIQP/QCP/MIQCP, and the capable solvers (SCIP, Hexaly) build them natively.
Anything beyond total degree 2 is a structured compile error.

Set operators (DSL-expressivity #4): ``set S := A union B;`` / ``A diff B`` /
``A cross B`` define a COMPUTED set (``cross`` binds tighter; parentheses, literal
and range atoms allowed). Operands must be declared earlier in the source, so the
member dimension is static (cross adds dimensions) and cycles are impossible;
members are computed after datasets fill the operands, and a dataset may still
override the computed set itself, whole-symbol.

Conditional expressions (DSL-expressivity #5): ``if <cond> [and <cond>]* then
<term> [else <term>]`` selects at GROUNDING time — conditions compare bound
indices, set members, numbers, and (possibly indexed) PARAM values, never
variables. Only the taken branch is grounded (``if i != j then d[i, j]`` never
touches the diagonal); a missing ``else`` is 0, as in AMPL. This is the
"conditional params" seam: per-index data decides the emitted coefficients.

Hardening guarantees (all violations raise :class:`JModelError`, never a raw exception):

- every referenced set/param/variable must be declared; every resolved index member must
  belong to the family's declared index set (no "ghost" flat variables);
- grounding work is bounded by an expansion budget (``max_grounded_elements``) checked
  *before* cartesian products are materialized;
- emitted numbers are always plain positional decimals (the flat ``ExpressionParser``
  does not understand scientific notation);
- constant constraint rows are dropped when trivially satisfied and rejected at compile
  time when violated by construction.

See ``docs/JMODEL_GRAMMAR.md`` for the frozen grammar.
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
#: terms. Generous for real models (the TFM's largest flow scenario — 243 vehicles ×
#: 199 orders over sparse tuple arc sets — grounds to ~850k elements) while rejecting
#: accidental combinatorial blowups (three-index families over large sets) before they
#: pin a CPU. Equality-filter slicing in ``_iter_env`` keeps honest sparse models from
#: burning budget on members their filters would discard.
MAX_GROUNDED_ELEMENTS = 2_000_000

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
    "dimen",
    "union",
    "diff",
    "cross",
    "if",
    "then",
    "else",
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
    with :meth:`from_json`; pass it to :func:`compile_jmodel`. Set members are tuples
    of components (1-tuples for plain sets); scalar param values are stored under the
    empty key ``()``; an N-dim value key is a tuple of members.
    """

    sets: dict[str, list[tuple[str, ...]]]
    params: dict[str, dict[tuple[str, ...], float]]

    @staticmethod
    def from_json(payload: object) -> JModelData:
        """Validate and normalize a ``{"sets": {...}, "params": {...}}`` JSON object.

        Set members are strings or integers; a comma-joined string names a TUPLE
        member (``"A,B"`` in a 2-dimensional set) — the same composite-key encoding
        indexed param values use (``{"A,1": 4}``). Every member of one set must have
        the same number of components. Raises :class:`JModelError` on any shape
        violation.
        """
        if not isinstance(payload, dict):
            raise JModelError("dataset must be a JSON object with 'sets' and/or 'params'")
        unknown = set(payload) - {"sets", "params"}
        if unknown:
            raise JModelError(
                f"dataset has unknown top-level key(s) {sorted(unknown)!r} — "
                "only 'sets' and 'params' are allowed"
            )
        sets: dict[str, list[tuple[str, ...]]] = {}
        raw_sets = payload.get("sets", {})
        if not isinstance(raw_sets, dict):
            raise JModelError("dataset 'sets' must be an object of set name -> member list")
        for name, raw_members in raw_sets.items():
            if not isinstance(raw_members, list):
                raise JModelError(f"dataset set {name!r} must be a list of members")
            members = [_data_member(name, m) for m in raw_members]
            arities = {len(member) for member in members}
            if len(arities) > 1:
                raise JModelError(
                    f"dataset set {name!r} mixes members of different dimensions "
                    f"({sorted(arities)} components) — every member of a set must "
                    "have the same number of comma-separated components"
                )
            sets[name] = members
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


def _data_member(set_name: str, raw: object) -> tuple[str, ...]:
    """A set member from dataset JSON: a non-empty string or an integer.

    A comma-joined string is a TUPLE member (``"A,B"`` → the pair ``(A, B)`` of a
    2-dimensional set); a plain string or integer is a 1-tuple.
    """
    if isinstance(raw, bool):
        raise JModelError(f"dataset set {set_name!r} has a boolean member — use strings/integers")
    if isinstance(raw, int):
        return (str(raw),)
    if not isinstance(raw, str):
        raise JModelError(
            f"dataset set {set_name!r} members must be strings or integers (got {raw!r})"
        )
    if not raw.strip():
        raise JModelError(f"dataset set {set_name!r} has an empty member")
    parts = tuple(part.strip() for part in raw.split(","))
    if any(not part for part in parts):
        raise JModelError(
            f"dataset set {set_name!r} member {raw!r} has an empty component — "
            "commas separate the components of a tuple member"
        )
    return parts


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
    ("OP", r":=|<=|>=|==|!=|\.\.|\*\*|[<>=]|[-+*^{}\[\](),;:]"),
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


@dataclass
class Pow:
    base: Expr
    exponent: int
    pos: int = 0


@dataclass
class CondOperand:
    """One side of an if-condition: an index var, a member/number literal, or a
    (possibly indexed) param reference — never a variable."""

    token: Token
    idx: list[Token]


@dataclass
class IfExpr:
    """``if cond [and cond]* then term [else term]`` — grounding-time selection.

    Only the taken branch is grounded (so ``if i != j then d[i, j]`` never looks
    up the diagonal); a missing ``else`` is 0, as in AMPL.
    """

    conds: list[tuple[CondOperand, str, CondOperand]]
    then: Expr
    els: Expr | None
    pos: int = 0


Expr = Num | Ref | Neg | BinOp | Sum | Pow | IfExpr


@dataclass
class Qualifiers:
    # (index_vars, set_name, set_name_pos) — one index var per member component:
    # `i in I` binds ("i",); `(i, j) in ARCS` binds ("i", "j").
    bindings: list[tuple[tuple[str, ...], str, int]]
    filters: list[tuple[Token, str, Token]]  # (left, op, right)


@dataclass
class SetDef:
    """A declared set: its dimension and (unless dataset-fillable) its members.

    ``dimen`` is the number of components per member (1 for plain sets, as in AMPL);
    for inline sets it is inferred from the literal, for declaration-only sets it
    comes from an explicit ``set ARCS dimen 2;`` (default 1). ``members is None``
    means the set was declared without values and a dataset must fill it — unless
    ``expr`` is set (a ``union``/``diff``/``cross`` expression over earlier sets),
    in which case the members are computed in :func:`_apply_data` after datasets
    are applied. A dataset value for a computed set overrides the expression,
    whole-symbol, exactly like it overrides an inline literal.
    """

    dimen: int
    members: list[tuple[str, ...]] | None
    pos: int = 0
    expr: SetExpr | None = None


@dataclass
class SetLiteralNode:
    """An anonymous literal / range operand inside a set expression."""

    members: list[tuple[str, ...]]
    pos: int = 0


@dataclass
class SetRefNode:
    name: str
    pos: int = 0


@dataclass
class SetOpNode:
    op: str  # union | diff | cross
    left: SetExpr
    right: SetExpr
    pos: int = 0


SetExpr = SetLiteralNode | SetRefNode | SetOpNode


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
    sets: dict[str, SetDef] = field(default_factory=dict)
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
        # `set ARCS dimen 2;` — explicit member dimension (default 1, as in AMPL).
        # Mandatory knowledge for declaration-only tuple sets; optional (but checked)
        # next to an inline literal.
        declared_dimen: int | None = None
        if self._accept_kw("dimen"):
            dimen_tok = self._advance()
            if dimen_tok.kind != "NUM" or not dimen_tok.value.isdigit():
                raise JModelError(
                    f"expected an integer after 'dimen' (got {dimen_tok.value!r})",
                    position=dimen_tok.pos,
                )
            declared_dimen = int(dimen_tok.value)
            if declared_dimen < 1:
                raise JModelError("'dimen' must be at least 1", position=dimen_tok.pos)
        # `set I;` (no body) declares the set; its members must come from a dataset.
        if self._accept_op(";"):
            model.check_unused_name(name_tok.value, name_tok.pos)
            model.sets[name_tok.value] = SetDef(declared_dimen or 1, None, name_tok.pos)
            return
        self._expect_op(":=")
        expr = self._parse_set_expr(model, name_tok.value)
        self._expect_op(";")
        model.check_unused_name(name_tok.value, name_tok.pos)
        if isinstance(expr, SetLiteralNode):
            # plain literal / range body — members are known right here
            members = expr.members
            arities = {len(member) for member in members}
            if len(arities) > 1:
                raise JModelError(
                    f"set {name_tok.value!r} mixes members of different dimensions "
                    f"({sorted(arities)} components) — every member must have the same arity",
                    position=name_tok.pos,
                )
            dimen = next(iter(arities)) if members else (declared_dimen or 1)
            if declared_dimen is not None and members and dimen != declared_dimen:
                raise JModelError(
                    f"set {name_tok.value!r} declares dimen {declared_dimen} but its members "
                    f"have {dimen} component(s)",
                    position=name_tok.pos,
                )
            if len(members) != len(set(members)):
                raise JModelError(
                    f"set {name_tok.value!r} has duplicate members", position=name_tok.pos
                )
            model.sets[name_tok.value] = SetDef(dimen, members, name_tok.pos)
            return
        # union/diff/cross expression — dimension is static, members are computed
        # in _apply_data once datasets have filled the operands
        dimen = self._set_expr_dimen(expr, model, name_tok.value)
        if declared_dimen is not None and dimen != declared_dimen:
            raise JModelError(
                f"set {name_tok.value!r} declares dimen {declared_dimen} but its expression "
                f"produces {dimen}-dimensional members",
                position=name_tok.pos,
            )
        model.sets[name_tok.value] = SetDef(dimen, None, name_tok.pos, expr=expr)

    def _parse_set_expr(self, model: ModelAst, target: str) -> SetExpr:
        """A set expression: term (('union' | 'diff') term)*, left-associative."""
        node = self._parse_set_term(model, target)
        while True:
            tok = self._peek()
            if tok.kind == "IDENT" and tok.value in ("union", "diff"):
                self._advance()
                node = SetOpNode(tok.value, node, self._parse_set_term(model, target), tok.pos)
            else:
                return node

    def _parse_set_term(self, model: ModelAst, target: str) -> SetExpr:
        """A set term: atom ('cross' atom)* — cross binds tighter, as in AMPL."""
        node = self._parse_set_atom(model, target)
        while True:
            tok = self._peek()
            if tok.kind == "IDENT" and tok.value == "cross":
                self._advance()
                node = SetOpNode("cross", node, self._parse_set_atom(model, target), tok.pos)
            else:
                return node

    def _parse_set_atom(self, model: ModelAst, target: str) -> SetExpr:
        tok = self._peek()
        if tok.kind == "OP" and tok.value == "(":
            self._advance()
            node = self._parse_set_expr(model, target)
            self._expect_op(")")
            return node
        if tok.kind == "OP" and tok.value == "{":
            self._advance()
            members: list[tuple[str, ...]] = []
            if not self._accept_op("}"):
                members.append(self._set_member())
                while self._accept_op(","):
                    members.append(self._set_member())
                self._expect_op("}")
            return SetLiteralNode(members, tok.pos)
        if tok.kind == "NUM" or (tok.kind == "OP" and tok.value == "-"):
            return SetLiteralNode(self._parse_range(target), tok.pos)
        if tok.kind == "IDENT" and tok.value not in _RESERVED_WORDS:
            name_tok = self._advance()
            if name_tok.value not in model.sets:
                raise JModelError(
                    f"unknown set {name_tok.value!r} in the definition of {target!r} — "
                    "a set expression may only use sets declared earlier in the source",
                    position=name_tok.pos,
                )
            return SetRefNode(name_tok.value, name_tok.pos)
        raise self._error("expected a set name, a literal '{...}', a range 'lo..hi', or '('")

    def _set_expr_dimen(self, node: SetExpr, model: ModelAst, target: str) -> int:
        """Static member dimension of a set expression (operands are declared earlier,
        so every dimension is known at parse time)."""
        if isinstance(node, SetLiteralNode):
            if not node.members:
                raise JModelError(
                    f"an empty literal has no dimension — declare it as its own set "
                    f"before using it in the definition of {target!r}",
                    position=node.pos,
                )
            arities = {len(member) for member in node.members}
            if len(arities) > 1:
                raise JModelError(
                    f"a literal in the definition of {target!r} mixes members of different "
                    f"dimensions ({sorted(arities)} components)",
                    position=node.pos,
                )
            if len(node.members) != len(set(node.members)):
                raise JModelError(
                    f"a literal in the definition of {target!r} has duplicate members",
                    position=node.pos,
                )
            return next(iter(arities))
        if isinstance(node, SetRefNode):
            return model.sets[node.name].dimen
        left = self._set_expr_dimen(node.left, model, target)
        right = self._set_expr_dimen(node.right, model, target)
        if node.op == "cross":
            return left + right
        if left != right:
            raise JModelError(
                f"'{node.op}' operands in the definition of {target!r} have different "
                f"member dimensions ({left} vs {right})",
                position=node.pos,
            )
        return left

    def _set_member(self) -> tuple[str, ...]:
        """A scalar member (`a`) or a tuple member (`(a, b)`)."""
        if self._accept_op("("):
            open_pos = self._peek().pos
            parts = [self._member()]
            while self._accept_op(","):
                parts.append(self._member())
            self._expect_op(")")
            if len(parts) < 2:
                raise JModelError(
                    "a tuple member needs at least two components — write a plain "
                    "member without parentheses instead",
                    position=open_pos,
                )
            return tuple(parts)
        return (self._member(),)

    def _parse_range(self, set_name: str) -> list[tuple[str, ...]]:
        """An inclusive integer range literal — ``set T := 1..96;``.

        Endpoints are (optionally signed) integer literals; the range declares the
        1-dimensional members ``lo, lo+1, ..., hi`` exactly as the equivalent brace
        literal would.
        """
        start_tok = self._peek()
        lo = self._range_endpoint(set_name)
        self._expect_op("..")
        hi = self._range_endpoint(set_name)
        if lo > hi:
            raise JModelError(
                f"range {lo}..{hi} in set {set_name!r} is empty — the lower endpoint "
                "must not exceed the upper endpoint",
                position=start_tok.pos,
            )
        size = hi - lo + 1
        if size > MAX_GROUNDED_ELEMENTS:
            raise JModelError(
                f"range {lo}..{hi} in set {set_name!r} has {size:,} members — more than "
                f"the {MAX_GROUNDED_ELEMENTS:,} grounded-element budget",
                position=start_tok.pos,
            )
        return [(str(value),) for value in range(lo, hi + 1)]

    def _range_endpoint(self, set_name: str) -> int:
        negative = self._accept_op("-")
        tok = self._advance()
        if tok.kind != "NUM" or not tok.value.isdigit():
            raise JModelError(
                f"range endpoints in set {set_name!r} must be integer literals "
                f"(got {tok.value or 'end of input'!r})",
                position=tok.pos,
            )
        value = int(tok.value)
        return -value if negative else value

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
            # Entries are read greedily (all tokens up to the last are key members,
            # the last is the value): once tuple sets exist, the FLAT key arity may
            # exceed the number of index sets, and set dimensions are only certain
            # after a dataset is applied — key shapes are validated at grounding.
            while True:
                key, value, key_pos = self._parse_param_entry(name_tok.value)
                if key in data:
                    raise JModelError(
                        f"param {name_tok.value!r} has duplicate entries for key {','.join(key)!r}",
                        position=key_pos,
                    )
                data[key] = value
                if self._accept_op(","):
                    continue
                break
            self._expect_op(";")
        model.check_unused_name(name_tok.value, name_tok.pos)
        model.params[name_tok.value] = ParamDecl(name_tok.value, index_sets, data, name_tok.pos)

    def _parse_param_entry(self, param_name: str) -> tuple[tuple[str, ...], float, int]:
        """One `member... value` entry of an indexed param body.

        Returns (key members, numeric value, position of the first token).
        """
        items: list[tuple[Token, bool]] = []  # (token, was_negated)
        while True:
            negative = self._accept_op("-")
            tok = self._advance()
            if tok.kind not in ("IDENT", "NUM"):
                raise JModelError(
                    f"expected a key member or a numeric value in param {param_name!r} "
                    f"(got {tok.value or 'end of input'!r})",
                    position=tok.pos,
                )
            items.append((tok, negative))
            nxt = self._peek()
            if nxt.kind == "OP" and nxt.value in (",", ";"):
                break
            if nxt.kind == "EOF":
                raise JModelError(
                    f"unterminated param {param_name!r} (missing ';')", position=nxt.pos
                )
        value_tok, value_negative = items[-1]
        if value_tok.kind != "NUM":
            raise JModelError(
                f"param {param_name!r} entry must end in a numeric value (got {value_tok.value!r})",
                position=value_tok.pos,
            )
        if len(items) == 1:
            raise JModelError(
                f"param {param_name!r} is indexed — each entry needs key member(s) "
                "before its value",
                position=value_tok.pos,
            )
        for tok, negated in items[:-1]:
            if negated:
                raise JModelError(
                    f"param {param_name!r} key members cannot be negative",
                    position=tok.pos,
                )
        value = self._finite_number(value_tok, value_tok.value)
        if value_negative:
            value = -value
        key = tuple(tok.value for tok, _ in items[:-1])
        return key, value, items[0][0].pos

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
        bindings: list[tuple[tuple[str, ...], str, int]] = []
        seen_indices: set[str] = set()
        while True:
            index_toks = self._parse_binding_indices()
            for tok in index_toks:
                if tok.value in seen_indices:
                    raise JModelError(
                        f"index {tok.value!r} is bound more than once in this qualifier",
                        position=tok.pos,
                    )
                seen_indices.add(tok.value)
            self._expect_kw("in")
            set_tok = self._advance()
            if set_tok.kind != "IDENT":
                raise JModelError(
                    f"expected a set name (got {set_tok.value!r})", position=set_tok.pos
                )
            bindings.append((tuple(tok.value for tok in index_toks), set_tok.value, set_tok.pos))
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

    def _parse_binding_indices(self) -> list[Token]:
        """The index side of a binding: `i` or the tuple-unpacking `(i, j)`."""
        if self._accept_op("("):
            toks = [self._expect_name()]
            while self._accept_op(","):
                toks.append(self._expect_name())
            self._expect_op(")")
            if len(toks) < 2:
                raise JModelError(
                    "a tuple binding needs at least two indices — write the index "
                    "without parentheses instead",
                    position=toks[0].pos,
                )
            return toks
        return [self._expect_name()]

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
            # unary minus binds LOOSER than '^' (as in AMPL): -x^2 == -(x^2)
            return Neg(self._parse_factor())
        if tok.kind == "OP" and tok.value == "+":
            self._advance()
            return self._parse_factor()
        if tok.kind == "OP" and tok.value == "(":
            # handled here (not in _parse_primary) to keep the recursion frames per
            # nesting level unchanged — _MAX_EXPR_DEPTH is calibrated against Python's
            # own recursion limit.
            self._advance()
            node = self._parse_expr()
            self._expect_op(")")
            return self._maybe_power(node)
        return self._maybe_power(self._parse_primary())

    def _parse_primary(self) -> Expr:
        tok = self._peek()
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
            if tok.value == "if":
                return self._parse_if_expr()
            name = self._advance().value
            idx: list[Token] = []
            if self._accept_op("["):
                idx.append(self._parse_idx_term())
                while self._accept_op(","):
                    idx.append(self._parse_idx_term())
                self._expect_op("]")
            return Ref(name, idx, tok.pos)
        raise self._error("expected a number, variable, param, sum, or '('")

    def _parse_if_expr(self) -> IfExpr:
        """``if cond [and cond]* then term [else term]`` — the branches bind to the
        following TERM (like ``sum``); parenthesize to widen them."""
        if_tok = self._advance()  # 'if'
        conds: list[tuple[CondOperand, str, CondOperand]] = []
        while True:
            left = self._parse_if_operand()
            op_tok = self._advance()
            if op_tok.kind != "OP" or op_tok.value not in _FILTER_OPS:
                raise JModelError(
                    f"expected a comparison operator in if-condition (got {op_tok.value!r})",
                    position=op_tok.pos,
                )
            right = self._parse_if_operand()
            conds.append((left, op_tok.value, right))
            if self._accept_kw("and"):
                continue
            break
        self._expect_kw("then")
        then_expr = self._parse_term()
        els_expr: Expr | None = None
        if self._accept_kw("else"):
            els_expr = self._parse_term()
        return IfExpr(conds, then_expr, els_expr, if_tok.pos)

    def _parse_if_operand(self) -> CondOperand:
        """An if-condition operand: index var, member/number literal, or a
        (possibly indexed) param reference."""
        tok = self._advance()
        if tok.kind not in ("IDENT", "NUM"):
            raise JModelError(
                f"expected an index, member, number, or param in if-condition "
                f"(got {tok.value or 'end of input'!r})",
                position=tok.pos,
            )
        idx: list[Token] = []
        if tok.kind == "IDENT" and self._accept_op("["):
            idx.append(self._parse_idx_term())
            while self._accept_op(","):
                idx.append(self._parse_idx_term())
            self._expect_op("]")
        return CondOperand(tok, idx)

    def _maybe_power(self, base: Expr) -> Expr:
        """An optional ``^ 2`` / ``** 2`` postfix on a primary (DSL-expressivity #1)."""
        tok = self._peek()
        if tok.kind != "OP" or tok.value not in ("^", "**"):
            return base
        self._advance()
        exp_tok = self._advance()
        if exp_tok.kind != "NUM" or not exp_tok.value.isdigit():
            raise JModelError(
                "exponent must be a positive integer literal "
                f"(got {exp_tok.value or 'end of input'!r})",
                position=exp_tok.pos,
            )
        exponent = int(exp_tok.value)
        if exponent not in (1, 2):
            raise JModelError(
                f"exponent {exponent} is out of range — only ^1 and ^2 are supported "
                "(the solve path caps expressions at degree 2)",
                position=exp_tok.pos,
            )
        nxt = self._peek()
        if nxt.kind == "OP" and nxt.value in ("^", "**"):
            raise JModelError("chained exponents are not supported", position=nxt.pos)
        return base if exponent == 1 else Pow(base, 2, tok.pos)


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
            set_def = model.sets.get(name)
            if set_def is None:
                raise JModelError(
                    f"dataset provides unknown set {name!r} — the model does not declare it"
                )
            if members and len(members[0]) != set_def.dimen:
                raise JModelError(
                    f"set {name!r} expects {set_def.dimen}-dimensional members but the "
                    f"dataset provides {len(members[0])} component(s) per member — "
                    f"declare `set {name} dimen {len(members[0])};` if the tuples are "
                    "intended"
                )
            if len(members) != len(set(members)):
                raise JModelError(f"dataset set {name!r} has duplicate members")
            set_def.members = list(members)
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
                # Exact key arity is checked at grounding (the flat arity of a param
                # over tuple sets is the sum of its sets' dimensions).
            decl.data = dict(values)
    # Computed sets (union/diff/cross) are evaluated AFTER dataset application, in
    # declaration order — the parser guarantees operands are declared earlier, so
    # every operand (inline, dataset-filled, or itself computed) is resolved by the
    # time its consumer runs. A dataset value for the computed set itself wins.
    for name, set_def in model.sets.items():
        if set_def.expr is not None and set_def.members is None:
            set_def.members = _eval_set_expr(set_def.expr, model, name)
    for name, set_def in model.sets.items():
        if set_def.members is None:
            raise JModelError(
                f"set {name!r} has no members — define them inline (:=) or provide a dataset"
            )
    for decl in model.params.values():
        if decl.data is None:
            raise JModelError(
                f"param {decl.name!r} has no values — define them inline (:=) or provide a dataset",
                position=decl.pos,
            )


def _eval_set_expr(node: SetExpr, model: ModelAst, target: str) -> list[tuple[str, ...]]:
    """Members of a computed set. ``union`` keeps first-appearance order and
    deduplicates; ``diff`` keeps the left operand's order; ``cross`` concatenates
    member tuples (left-outer order) and is budget-checked before materializing."""
    if isinstance(node, SetLiteralNode):
        return list(node.members)
    if isinstance(node, SetRefNode):
        operand = model.sets[node.name]
        if operand.members is None:
            raise JModelError(
                f"set {node.name!r} has no members — the computed set {target!r} needs "
                "them; define them inline (:=) or provide a dataset",
                position=node.pos,
            )
        return list(operand.members)
    left = _eval_set_expr(node.left, model, target)
    right = _eval_set_expr(node.right, model, target)
    if node.op == "union":
        seen = set(left)
        merged = list(left)
        for member in right:
            if member not in seen:
                seen.add(member)
                merged.append(member)
        return merged
    if node.op == "diff":
        removed = set(right)
        return [member for member in left if member not in removed]
    # cross
    if len(left) * len(right) > MAX_GROUNDED_ELEMENTS:
        raise JModelError(
            f"computed set {target!r} crosses {len(left):,} × {len(right):,} members — "
            f"more than the {MAX_GROUNDED_ELEMENTS:,} grounded-element budget",
            position=node.pos,
        )
    return [lm + rm for lm in left for rm in right]


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
    set_members: dict[str, frozenset[tuple[str, ...]]]
    all_members: frozenset[str]  # every scalar component, for filter-term validation
    budget: _Budget
    # Lazily-built equality-slice indexes: (set name, pinned positions) -> canonical
    # pinned values -> members, preserving declaration order (determinism).
    slice_cache: dict[tuple[str, tuple[int, ...]], dict[tuple[str, ...], list[tuple[str, ...]]]] = (
        field(default_factory=dict)
    )

    @staticmethod
    def build(model: ModelAst, max_grounded_elements: int) -> _Ctx:
        # The `is not None` narrow is for the type only: _apply_data ran before any
        # lowering, so every declared set has members here.
        set_members = {
            name: frozenset(set_def.members)
            for name, set_def in model.sets.items()
            if set_def.members is not None
        }
        components: set[str] = set()
        for members in set_members.values():
            for member in members:
                components.update(member)
        return _Ctx(model, set_members, frozenset(components), _Budget(max_grounded_elements))


@dataclass
class _LinForm:
    """A grounded degree-≤2 form: sum(coef*var) + sum(coef*var*var) + const.

    ``quad`` keys are alphabetically-ordered variable pairs (``v1 <= v2``), so
    ``x*y`` and ``y*x`` consolidate into one term; insertion order is preserved
    for deterministic emission. Terms are ordered by first appearance.
    """

    coeffs: dict[str, float]
    const: float
    quad: dict[tuple[str, str], float] = field(default_factory=dict)

    @staticmethod
    def number(value: float) -> _LinForm:
        return _LinForm({}, float(value))

    @staticmethod
    def variable(name: str) -> _LinForm:
        return _LinForm({name: 1.0}, 0.0)

    def is_const(self) -> bool:
        return all(c == 0 for c in self.coeffs.values()) and all(c == 0 for c in self.quad.values())

    def is_linear(self) -> bool:
        return all(c == 0 for c in self.quad.values())

    def scaled(self, k: float) -> _LinForm:
        return _LinForm(
            {v: c * k for v, c in self.coeffs.items()},
            self.const * k,
            {pair: c * k for pair, c in self.quad.items()},
        )

    def plus(self, other: _LinForm) -> _LinForm:
        merged = dict(self.coeffs)
        for var, coef in other.coeffs.items():
            merged[var] = merged.get(var, 0.0) + coef
        merged_quad = dict(self.quad)
        for pair, coef in other.quad.items():
            merged_quad[pair] = merged_quad.get(pair, 0.0) + coef
        return _LinForm(merged, self.const + other.const, merged_quad)

    def minus(self, other: _LinForm) -> _LinForm:
        return self.plus(other.scaled(-1.0))


def _multiply(left: _LinForm, right: _LinForm) -> _LinForm:
    """Product of two grounded forms, capped at total degree 2.

    Constants scale; linear × linear distributes into bilinear terms; anything
    that would exceed degree 2 (a factor that is already quadratic) is a
    structured compile error — the flat ``ExpressionParser`` caps at degree 2.
    """
    if left.is_const():
        return right.scaled(left.const)
    if right.is_const():
        return left.scaled(right.const)
    if not left.is_linear() or not right.is_linear():
        raise JModelError(
            "term of degree greater than 2 — a product may multiply at most two variables"
        )
    quad: dict[tuple[str, str], float] = {}
    for v1, c1 in left.coeffs.items():
        if c1 == 0:
            continue
        for v2, c2 in right.coeffs.items():
            if c2 == 0:
                continue
            pair = (v1, v2) if v1 <= v2 else (v2, v1)
            quad[pair] = quad.get(pair, 0.0) + c1 * c2
    coeffs: dict[str, float] = {}
    if right.const != 0:
        for var, coef in left.coeffs.items():
            coeffs[var] = coeffs.get(var, 0.0) + coef * right.const
    if left.const != 0:
        for var, coef in right.coeffs.items():
            coeffs[var] = coeffs.get(var, 0.0) + coef * left.const
    return _LinForm(coeffs, left.const * right.const, quad)


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


def _num_key(text: str) -> str | None:
    """Canonical numeric identity for member/index tokens.

    Integer literals canonicalize through ``int`` (arbitrary precision), so two
    distinct all-digit members beyond float64's ~15 significant digits never
    collapse to one key; ``"1"``, ``"1.0"`` and ``"1e0"`` still share the key
    ``"1"``. Returns ``None`` for non-numeric text.
    """
    try:
        return repr(int(text))
    except ValueError:
        pass
    num = _as_number(text)
    if num is None:
        return None
    if num.is_integer() and abs(num) < 2**53:
        return repr(int(num))
    return repr(num)


def _compare(left: str, op: str, right: str, position: int | None = None) -> bool:
    left_num, right_num = _as_number(left), _as_number(right)
    if op in ("==", "!="):
        left_key, right_key = _num_key(left), _num_key(right)
        if left_key is not None and right_key is not None:
            equal = left_key == right_key
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


def _eval_cond_operand(operand: CondOperand, env: dict[str, str], ctx: _Ctx) -> str:
    """Resolve an if-condition operand to its comparable string.

    An indexed reference must be a PARAM (its numeric value compares); a bare
    identifier is, in order: a bound index (its member), a scalar param (its
    value), or a declared set member (a literal, as in filters). Variables are
    rejected — an if-condition is decided at compile time, never by the solver.
    """
    tok = operand.token
    model = ctx.model
    if operand.idx:
        param = model.params.get(tok.value)
        if param is None:
            kind = "variable" if tok.value in model.vars else "unknown symbol"
            raise JModelError(
                f"{tok.value!r} in an if-condition is a {kind} — only params can be "
                "compared (conditions are decided at compile time)",
                position=tok.pos,
            )
        assert param.data is not None  # guaranteed by _apply_data
        expected = _flat_arity(param.index_sets, ctx)
        if len(operand.idx) != expected:
            raise JModelError(
                f"param {tok.value!r} indexed with {len(operand.idx)} subscript(s), "
                f"expected {expected}",
                position=tok.pos,
            )
        ref = Ref(tok.value, operand.idx, tok.pos)
        key = tuple(_resolve_members(ref, param.index_sets, env, ctx))
        if key not in param.data:
            raise JModelError(f"param {tok.value!r} has no value for index {key}", position=tok.pos)
        return str(param.data[key])
    if tok.kind == "NUM":
        return tok.value
    if tok.value in env:
        return env[tok.value]
    scalar = model.params.get(tok.value)
    if scalar is not None:
        assert scalar.data is not None  # guaranteed by _apply_data
        if scalar.index_sets:
            raise JModelError(
                f"param {tok.value!r} is indexed over {len(scalar.index_sets)} set(s) — "
                "subscript it in the if-condition",
                position=tok.pos,
            )
        return str(scalar.data[()])
    if tok.value in ctx.all_members:
        return tok.value
    kind = "a variable" if tok.value in model.vars else "not a bound index, param, or set member"
    raise JModelError(
        f"{tok.value!r} in an if-condition is {kind} — conditions compare indices "
        "and param values at compile time",
        position=tok.pos,
    )


def _validate_filter_terms(quals: Qualifiers, base_env: dict[str, str], ctx: _Ctx) -> None:
    """A filter identifier must be a bound index variable or a declared set member —
    anything else is a typo that would otherwise silently degrade to a literal string
    (making the filter a no-op)."""
    bound = set(base_env)
    for index_vars, _, _ in quals.bindings:
        bound.update(index_vars)
    for left, _, right in quals.filters:
        for tok in (left, right):
            if tok.kind == "IDENT" and tok.value not in bound and tok.value not in ctx.all_members:
                raise JModelError(
                    f"unknown index {tok.value!r} in filter — not a bound index variable "
                    "or a declared set member",
                    position=tok.pos,
                )


def _canon_idx(text: str) -> str:
    """Canonical form for slice-index keys, mirroring :func:`_compare`'s numeric-first
    equality (``"1"`` equals ``"1.0"`` numerically, so both must map to one key)."""
    key = _num_key(text)
    return key if key is not None else text


def _sliced_members(
    ctx: _Ctx, set_name: str, positions: tuple[int, ...], values: tuple[str, ...]
) -> list[tuple[str, ...]]:
    """Members of ``set_name`` whose components at ``positions`` equal ``values``.

    Backed by a lazily-built index per (set, positions) pair, so repeated slices —
    one per grounded constraint row — cost O(matched members) instead of a full scan.
    """
    cache_key = (set_name, positions)
    index = ctx.slice_cache.get(cache_key)
    if index is None:
        index = {}
        set_def = ctx.model.sets[set_name]
        assert set_def.members is not None  # guaranteed by _apply_data
        for member in set_def.members:
            key = tuple(_canon_idx(member[p]) for p in positions)
            index.setdefault(key, []).append(member)
        ctx.slice_cache[cache_key] = index
    return index.get(tuple(_canon_idx(v) for v in values), [])


def _split_filters(
    quals: Qualifiers,
) -> tuple[dict[int, list[tuple[int, Token]]], list[tuple[Token, str, Token]]]:
    """Partition filters into per-level equality SLICES and residual compares.

    An ``==`` filter pinning an index introduced at binding level ``b`` to a value
    resolvable before ``b`` (a literal, an outer/base index, or an index of an
    earlier binding) is hoisted into level ``b``'s member lookup. Everything else —
    ordering ops, ``!=``, or equalities between two indices of the same binding —
    stays a per-combination compare, exactly as before.
    """
    var_level: dict[str, int] = {}
    var_position: dict[str, int] = {}
    for level, (index_vars, _, _) in enumerate(quals.bindings):
        for position, var in enumerate(index_vars):
            var_level[var] = level
            var_position[var] = position

    def hoist(var_tok: Token, value_tok: Token) -> tuple[int, int] | None:
        """(level, position) when `var_tok == value_tok` can slice, else None."""
        if var_tok.kind != "IDENT" or var_tok.value not in var_level:
            return None
        level = var_level[var_tok.value]
        if value_tok.kind == "IDENT" and value_tok.value in var_level:
            # NOTE: an index var shadows a base_env name of the same spelling (the
            # binding overwrites it in the env), so this check must come first.
            if var_level[value_tok.value] >= level:
                return None
        return (level, var_position[var_tok.value])

    sliced: dict[int, list[tuple[int, Token]]] = {}
    residual: list[tuple[Token, str, Token]] = []
    for left, op, right in quals.filters:
        placed = None
        if op == "==":
            placed = hoist(left, right)
            if placed is not None:
                sliced.setdefault(placed[0], []).append((placed[1], right))
            else:
                placed = hoist(right, left)
                if placed is not None:
                    sliced.setdefault(placed[0], []).append((placed[1], left))
        if placed is None:
            residual.append((left, op, right))
    return sliced, residual


def _iter_env(quals: Qualifiers, base_env: dict[str, str], ctx: _Ctx) -> list[dict[str, str]]:
    member_lists: list[list[tuple[str, ...]]] = []
    for index_vars, set_name, set_pos in quals.bindings:
        set_def = ctx.model.sets.get(set_name)
        if set_def is None:
            raise JModelError(f"unknown set {set_name!r} in qualifier", position=set_pos)
        if len(index_vars) != set_def.dimen:
            raise JModelError(
                f"binding names {len(index_vars)} index(es) but set {set_name!r} has "
                f"{set_def.dimen}-dimensional members",
                position=set_pos,
            )
        assert set_def.members is not None  # guaranteed by _apply_data
        member_lists.append(set_def.members)
    _validate_filter_terms(quals, base_env, ctx)
    sliced, residual = _split_filters(quals)

    envs: list[dict[str, str]] = [dict(base_env)]
    if not quals.bindings:
        ctx.budget.consume(1, None)
    for level, (index_vars, set_name, set_pos) in enumerate(quals.bindings):
        level_slices = sorted(sliced.get(level, ()), key=lambda pv: pv[0])
        positions = tuple(position for position, _ in level_slices)
        next_envs: list[dict[str, str]] = []
        for env in envs:
            if level_slices:
                values = tuple(_resolve_idx(tok, env) for _, tok in level_slices)
                candidates = _sliced_members(ctx, set_name, positions, values)
            else:
                candidates = member_lists[level]
            ctx.budget.consume(len(candidates), set_pos)
            for member in candidates:
                env2 = dict(env)
                for index_var, component in zip(index_vars, member, strict=True):
                    env2[index_var] = component
                next_envs.append(env2)
        envs = next_envs
    if residual:
        envs = [
            env
            for env in envs
            if all(
                _compare(_resolve_idx(left, env), op, _resolve_idx(right, env), position=left.pos)
                for left, op, right in residual
            )
        ]
    return envs


def _flat_arity(decl_sets: list[str], ctx: _Ctx) -> int:
    """Total subscript count of a family indexed over ``decl_sets`` — the sum of the
    sets' dimensions (a tuple set contributes one subscript per component)."""
    return sum(ctx.model.sets[set_name].dimen for set_name in decl_sets)


def _resolve_members(node: Ref, decl_sets: list[str], env: dict[str, str], ctx: _Ctx) -> list[str]:
    """Resolve a Ref's index tokens and verify each member (grouped per declared set —
    a tuple set consumes its dimension's worth of subscripts) belongs to that set.
    A mismatch would otherwise emit a "ghost" name that exists in an expression but
    not in the declared variable expansion — for a tuple set this is also the guard
    that keeps references INSIDE the sparse member list."""
    members = [_resolve_idx(tok, env) for tok in node.idx]
    offset = 0
    for set_name in decl_sets:
        dimen = ctx.model.sets[set_name].dimen
        group = tuple(members[offset : offset + dimen])
        if group not in ctx.set_members.get(set_name, frozenset()):
            shown = group[0] if dimen == 1 else "(" + ", ".join(group) + ")"
            raise JModelError(
                f"{node.name!r} index {shown!r} is not a member of set {set_name!r}",
                position=node.pos,
            )
        offset += dimen
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
        return _multiply(left, right)
    if isinstance(node, Pow):
        base = _ground(node.base, env, ctx)
        return _multiply(base, base)  # parser guarantees exponent == 2
    if isinstance(node, IfExpr):
        taken = all(
            _compare(
                _eval_cond_operand(left, env, ctx),
                op,
                _eval_cond_operand(right, env, ctx),
                position=node.pos,
            )
            for left, op, right in node.conds
        )
        if taken:
            return _ground(node.then, env, ctx)
        if node.els is not None:
            return _ground(node.els, env, ctx)
        return _LinForm.number(0.0)
    if isinstance(node, Sum):
        # Accumulate into one mutable dict — building an immutable _LinForm per term
        # would copy the growing dict on every step (quadratic in the sum's length).
        coeffs: dict[str, float] = {}
        quad: dict[tuple[str, str], float] = {}
        const = 0.0
        for env2 in _iter_env(node.quals, env, ctx):
            form = _ground(node.body, env2, ctx)
            for var, coef in form.coeffs.items():
                coeffs[var] = coeffs.get(var, 0.0) + coef
            for pair, coef in form.quad.items():
                quad[pair] = quad.get(pair, 0.0) + coef
            const += form.const
        return _LinForm(coeffs, const, quad)
    # Ref
    model = ctx.model
    if node.name in model.vars:
        var_decl = model.vars[node.name]
        expected = _flat_arity(var_decl.index_sets, ctx)
        if len(node.idx) != expected:
            raise JModelError(
                f"variable {node.name!r} indexed with {len(node.idx)} subscript(s), "
                f"expected {expected}",
                position=node.pos,
            )
        members = _resolve_members(node, var_decl.index_sets, env, ctx)
        return _LinForm.variable(_mangle(node.name, members))
    if node.name in model.params:
        param_decl = model.params[node.name]
        assert param_decl.data is not None  # guaranteed by _apply_data
        expected = _flat_arity(param_decl.index_sets, ctx)
        if len(node.idx) != expected:
            raise JModelError(
                f"param {node.name!r} indexed with {len(node.idx)} subscript(s), "
                f"expected {expected}",
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
    for (v1, v2), coef in lf.quad.items():
        if coef == 0:
            continue
        base = f"{v1}^2" if v1 == v2 else f"{v1}*{v2}"
        term = base if abs(coef) == 1 else f"{_fmt_num(abs(coef))}*{base}"
        parts.append((coef < 0, term))
    if include_const and lf.const != 0:
        parts.append((lf.const < 0, _fmt_num(abs(lf.const))))
    if not parts:
        return "0"
    out = ("-" if parts[0][0] else "") + parts[0][1]
    for negative, term in parts[1:]:
        out += (" - " if negative else " + ") + term
    return out


# Feasibility tolerance for constant rows: parameter arithmetic leaves float
# residues (0.1+0.1+0.1-0.3 ≈ 5.6e-17), and exact comparison would reject a
# mathematically-satisfied model at compile time. Well below any solver's own
# feasibility tolerance (SCIP defaults to 1e-6).
_CONST_ROW_TOL = 1e-9


def _constant_row_is_satisfied(const: float, op: str) -> bool:
    """Truth of a fully-constant row ``const <op> 0`` (the grounded lhs-rhs form)."""
    if op == "<=":
        return const <= _CONST_ROW_TOL
    if op == ">=":
        return const >= -_CONST_ROW_TOL
    return abs(const) <= _CONST_ROW_TOL


def _lower(model: ModelAst, max_grounded_elements: int) -> OptimizationProblem:
    assert model.objective is not None  # guaranteed by parse()
    ctx = _Ctx.build(model, max_grounded_elements)

    # 1. variables — cartesian expansion across the declared index sets; a tuple set
    # contributes its ACTUAL member list (sparse), never a cartesian closure of its
    # components.
    variables: list[Variable] = []
    seen: set[str] = set()
    for name in model.var_order:
        decl = model.vars[name]
        member_lists: list[list[tuple[str, ...]]] = []
        for set_name in decl.index_sets:
            set_def = model.sets.get(set_name)
            if set_def is None:
                raise JModelError(
                    f"unknown set {set_name!r} in variable family {name!r}", position=decl.pos
                )
            assert set_def.members is not None  # guaranteed by _apply_data
            member_lists.append(set_def.members)
        size = math.prod(len(m) for m in member_lists) if member_lists else 1
        ctx.budget.consume(size, decl.pos)
        combos = product(*member_lists) if member_lists else [()]
        for combo in combos:
            flat = _mangle(name, [component for member in combo for component in member])
            if flat in seen:
                raise JModelError(
                    f"variable name collision after mangling: {flat!r}", position=decl.pos
                )
            seen.add(flat)
            # Carry the authoritative index structure onto the flat variable so
            # the solution can be regrouped as assign[v3, o107] downstream. One
            # index_tuple entry per index SET (a multi-component set member is
            # joined with "_"); genuine scalars (no combo) stay unstructured.
            index_tuple = ["_".join(member) for member in combo] if combo else None
            variables.append(
                Variable(
                    name=flat,
                    type=VariableType(decl.vtype),
                    lower_bound=decl.lb,
                    upper_bound=decl.ub,
                    family=name if combo else None,
                    index_tuple=index_tuple,
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

    # 1b. params — declared index sets must exist, every data key must have the flat
    # arity (sum of set dimensions), and every key group must be a member of the
    # corresponding set (a typo'd key would only surface — or worse, not — when that
    # exact index is referenced).
    for param in model.params.values():
        assert param.data is not None  # guaranteed by _apply_data
        group_specs: list[tuple[str, frozenset[tuple[str, ...]], int]] = []
        total_arity = 0
        for set_name in param.index_sets:
            members_frozen = ctx.set_members.get(set_name)
            if members_frozen is None:
                raise JModelError(
                    f"unknown set {set_name!r} in param {param.name!r}", position=param.pos
                )
            dimen = model.sets[set_name].dimen
            group_specs.append((set_name, members_frozen, dimen))
            total_arity += dimen
        for key in param.data:
            if len(key) != total_arity:
                raise JModelError(
                    f"param {param.name!r} data key {','.join(key)!r} has {len(key)} "
                    f"member(s), expected {total_arity}",
                    position=param.pos,
                )
            offset = 0
            for set_name, members_frozen, dimen in group_specs:
                group = tuple(key[offset : offset + dimen])
                if group not in members_frozen:
                    shown = group[0] if dimen == 1 else "(" + ", ".join(group) + ")"
                    raise JModelError(
                        f"param {param.name!r} data key {key} has member {shown!r} "
                        f"which is not in set {set_name!r}",
                        position=param.pos,
                    )
                offset += dimen

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
            suffix = [
                env[index_var]
                for index_vars, _, _ in con.quals.bindings
                for index_var in index_vars
            ]
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
            lhs_str = _fmt_linform(
                _LinForm(combined.coeffs, 0.0, combined.quad), include_const=False
            )
            rhs_num = _fmt_num(-combined.const)
            constraints.append(
                Constraint(
                    name=flat_name,
                    expression=f"{lhs_str} {con.op} {rhs_num}",
                    # Authoritative family, mirroring Variable.family: the declared
                    # constraint name IS the family; scalar rows stay unstructured.
                    family=con.name if suffix else None,
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


# --------------------------------------------------------------------------- #
# Declaration inspector (S2a) — the data-facing view of a source
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SetInfo:
    """A declared set, as the dataset editor needs to see it."""

    name: str
    has_inline_values: bool


@dataclass(frozen=True)
class ParamInfo:
    """A declared param: its index sets define the dataset key shape.

    ``arity`` is the FLAT key arity — the sum of the index sets' dimensions, which
    exceeds ``len(index_sets)`` once tuple sets are involved.
    """

    name: str
    index_sets: tuple[str, ...]
    arity: int
    has_inline_values: bool


@dataclass(frozen=True)
class ModelDeclarations:
    """The data-facing declarations (sets + params) of a JModel source."""

    sets: tuple[SetInfo, ...]
    params: tuple[ParamInfo, ...]


def inspect_declarations(src: str) -> ModelDeclarations:
    """Parse-only view of the source's sets/params (``POST /dsl/inspect``, S2a).

    NO data application and NO grounding, so it succeeds for declaration-only
    sources and for sources whose dataset is missing — exactly the states in which
    the editor needs a skeleton. Raises :class:`JModelError` on lex/parse errors only.
    """
    model = _Parser(tokenize(src)).parse()

    def flat_arity(index_sets: list[str]) -> int:
        # Unknown set names (a typo the compile will reject) count as dimension 1 —
        # this is best-effort guidance for the editor, not validation.
        return sum(model.sets[name].dimen if name in model.sets else 1 for name in index_sets)

    return ModelDeclarations(
        sets=tuple(
            # a computed (union/diff/cross) set is self-filling — the dataset
            # editor must not ask for its members
            SetInfo(name, set_def.members is not None or set_def.expr is not None)
            for name, set_def in model.sets.items()
        ),
        params=tuple(
            ParamInfo(p.name, tuple(p.index_sets), flat_arity(p.index_sets), p.data is not None)
            for p in model.params.values()
        ),
    )


# --------------------------------------------------------------------------- #
# LaTeX pretty-printer (B1) — symbolic math notation from the parsed AST
# --------------------------------------------------------------------------- #
#
# Renders the SYMBOLIC model (indexed sums, ∀-quantified constraint families,
# variable domains) from the AST BEFORE grounding — the structure that grounding
# flattens away into thousands of scalar rows. Deterministic, no data, no LLM.
# Output targets KaTeX (frontend split-pane), so every string is valid TeX math.

# Names that read as Greek letters render as their symbol (α, β, Σ, …); the TFM's
# "Min α ΣΣ …" comes straight from `minimize obj: alpha * sum{...} sum{...} …`.
_GREEK_LETTERS = frozenset(
    {
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
        "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma",
        "tau", "upsilon", "phi", "chi", "psi", "omega",
        "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon",
        "Phi", "Psi", "Omega",
    }
)  # fmt: skip

# Comparison operators → their TeX symbol (constraint relation and set-filters).
_TEX_OPS = {"<=": r"\le", ">=": r"\ge", "==": "=", "!=": r"\ne", "<": "<", ">": ">"}

# Expression node precedence: a child is parenthesized when its precedence is
# below the minimum its position requires. Additive < multiplicative/negation <
# sum (visually grouped) < atomic.
_PREC_ADD = 1
_PREC_MUL = 2
_PREC_SUM = 3
_PREC_ATOM = 4


@dataclass(frozen=True)
class LatexLine:
    """One rendered TeX line plus the source name (objective / constraint / var)."""

    latex: str
    label: str | None = None


@dataclass(frozen=True)
class LatexModel:
    """A JModel rendered as symbolic math: objective, constraint families, domains."""

    objective: LatexLine | None
    constraints: tuple[LatexLine, ...]
    variables: tuple[LatexLine, ...]


def _is_number_text(text: str) -> bool:
    return _as_number(text) is not None


def _tex_atom(name: str) -> str:
    """Render one identifier or literal as TeX.

    Greek-named symbols become their letter; a numeric literal is verbatim; a
    single character stays an italic math variable; a multi-character name is set
    upright (``\\mathrm``) with underscores escaped, so ``total_cost`` reads as a
    word rather than ``t·o·t·a·l`` with a spurious subscript.
    """
    if name in _GREEK_LETTERS:
        return "\\" + name
    if _is_number_text(name):
        return name
    if len(name) == 1:
        return name
    return "\\mathrm{" + name.replace("_", r"\_") + "}"


def _tex_ref(name: str, idx: list[Token]) -> str:
    """A (possibly indexed) symbol: ``x`` → ``x``, ``x[i,j]`` → ``x_{i,j}``."""
    base = _tex_atom(name)
    if not idx:
        return base
    sub = ",".join(_tex_atom(tok.value) for tok in idx)
    return f"{base}_{{{sub}}}"


def _emit(node: Expr, min_prec: int) -> str:
    """Render ``node``, wrapping it in ``\\left(…\\right)`` when its precedence is
    below ``min_prec`` (so operator grouping is preserved without over-bracketing)."""
    text, prec = _emit_prec(node)
    if prec < min_prec:
        return r"\left(" + text + r"\right)"
    return text


def _emit_prec(node: Expr) -> tuple[str, int]:
    if isinstance(node, Num):
        return _fmt_num(node.value), _PREC_ATOM
    if isinstance(node, Ref):
        return _tex_ref(node.name, node.idx), _PREC_ATOM
    if isinstance(node, Pow):
        return f"{_emit(node.base, _PREC_ATOM)}^{{{node.exponent}}}", _PREC_ATOM
    if isinstance(node, IfExpr):
        return _emit_if(node), _PREC_ATOM
    if isinstance(node, Sum):
        return _emit_sum(node), _PREC_SUM
    if isinstance(node, Neg):
        return f"-{_emit(node.expr, _PREC_MUL)}", _PREC_MUL
    if isinstance(node, BinOp):
        if node.op == "*":
            left = _emit(node.left, _PREC_MUL)
            # The right operand takes a tighter bound so a negation renders as
            # `x (−y)` not the subtraction-looking `x −y`; a sum stays bare.
            right = _emit(node.right, _PREC_SUM)
            if isinstance(node.left, Num) and isinstance(node.right, Num):
                return f"{left} \\cdot {right}", _PREC_MUL
            return f"{left} \\, {right}", _PREC_MUL
        left = _emit(node.left, _PREC_ADD)
        # `a - (b + c)` must keep its parens; `a + b + c` needs none.
        right = _emit(node.right, _PREC_MUL if node.op == "-" else _PREC_ADD)
        return f"{left} {node.op} {right}", _PREC_ADD
    # Defensive: the Expr union is closed, so this is unreachable in practice.
    raise JModelError("cannot render expression as LaTeX")


def _bindings_latex(quals: Qualifiers) -> str:
    """The ``i \\in I,\\ (u, v) \\in ARCS`` binding list of a sum/constraint family."""
    parts: list[str] = []
    for index_vars, set_name, _pos in quals.bindings:
        set_tex = _tex_atom(set_name)
        if len(index_vars) == 1:
            parts.append(f"{_tex_atom(index_vars[0])} \\in {set_tex}")
        else:
            tup = ", ".join(_tex_atom(v) for v in index_vars)
            parts.append(f"({tup}) \\in {set_tex}")
    return ",\\; ".join(parts)


def _filters_latex(quals: Qualifiers) -> str:
    """The set-filter conditions (``i \\ne j``) as a comma-joined clause, or ``''``."""
    return ",\\; ".join(
        f"{_tex_atom(left.value)} {_TEX_OPS.get(op, op)} {_tex_atom(right.value)}"
        for left, op, right in quals.filters
    )


def _emit_sum(node: Sum) -> str:
    bindings = _bindings_latex(node.quals)
    filters = _filters_latex(node.quals)
    if bindings and filters:
        sub = f"{bindings} \\,:\\, {filters}"
    else:
        sub = bindings or filters
    body = _emit(node.body, _PREC_MUL)  # body is a term; never top-level additive
    return f"\\sum_{{{sub}}} {body}" if sub else f"\\sum {body}"


def _emit_cond_operand(operand: CondOperand) -> str:
    return _tex_ref(operand.token.value, operand.idx)


def _emit_if(node: IfExpr) -> str:
    conds = " \\ \\text{and}\\ ".join(
        f"{_emit_cond_operand(left)} {_TEX_OPS.get(op, op)} {_emit_cond_operand(right)}"
        for left, op, right in node.conds
    )
    then = _emit(node.then, _PREC_ADD)
    els = _emit(node.els, _PREC_ADD) if node.els is not None else "0"
    return (
        f"\\begin{{cases}} {then} & \\text{{if }} {conds} \\\\ "
        f"{els} & \\text{{otherwise}} \\end{{cases}}"
    )


def _synth_indices(index_sets: list[str]) -> list[str]:
    """Invent readable single-letter index names for a variable's domain line.

    A ``var x{I, J}`` names no indices (they arise only where it is *used*), yet
    its domain reads best as ``x_{i,j} \\;\\forall i \\in I, j \\in J``. Use each
    set's initial, lowercased and de-duplicated, falling back to i, j, k, … .
    """
    used: set[str] = set()
    letters: list[str] = []
    for name in index_sets:
        cand = name[0].lower() if name and name[0].isalpha() else "i"
        if cand in used:
            cand = next((alt for alt in "ijklmnpqrstuvw" if alt not in used), f"i{len(letters)}")
        used.add(cand)
        letters.append(cand)
    return letters


def _bounds_suffix(var: VarDecl, var_tex: str) -> str:
    lb, ub = var.lb, var.ub
    if lb is not None and ub is not None:
        return f"{_fmt_num(lb)} \\le {var_tex} \\le {_fmt_num(ub)}"
    if lb is not None:
        return f"{var_tex} \\ge {_fmt_num(lb)}"
    if ub is not None:
        return f"{var_tex} \\le {_fmt_num(ub)}"
    return ""


def _vardomain_latex(var: VarDecl) -> LatexLine:
    letters = _synth_indices(var.index_sets)
    var_tex = f"{_tex_atom(var.name)}_{{{','.join(letters)}}}" if letters else _tex_atom(var.name)
    if var.vtype == "binary":
        domain = f"{var_tex} \\in \\{{0, 1\\}}"
    else:
        space = "\\mathbb{Z}" if var.vtype == "integer" else "\\mathbb{R}"
        domain = f"{var_tex} \\in {space}"
        bounds = _bounds_suffix(var, var_tex)
        if bounds:
            domain = f"{domain},\\; {bounds}"
    if letters:
        quant = ",\\; ".join(
            f"{letter} \\in {_tex_atom(set_name)}"
            for letter, set_name in zip(letters, var.index_sets, strict=True)
        )
        domain = f"{domain} \\quad \\forall\\, {quant}"
    return LatexLine(latex=domain, label=var.name)


def _objective_latex(obj: ObjectiveDecl) -> LatexLine:
    op = "\\min" if obj.sense == "minimize" else "\\max"
    return LatexLine(latex=f"{op} \\quad {_emit(obj.expr, _PREC_ADD)}", label=obj.name)


def _constraint_latex(con: ConstraintDecl) -> LatexLine:
    lhs = _emit(con.lhs, _PREC_ADD)
    rhs = _emit(con.rhs, _PREC_ADD)
    relation = _TEX_OPS.get(con.op, con.op)
    body = f"{lhs} {relation} {rhs}"
    bindings = _bindings_latex(con.quals)
    if bindings:
        filters = _filters_latex(con.quals)
        core = f"{bindings} \\,:\\, {filters}" if filters else bindings
        body = f"{body} \\quad \\forall\\, {core}"
    return LatexLine(latex=body, label=con.name)


def latexify(src: str) -> LatexModel:
    """Parse-only LaTeX pretty-print of a JModel source (``POST /dsl/latex``, B1).

    Renders the SYMBOLIC model — objective, constraint families with their
    ``\\forall`` quantifiers, and variable domains — from the parsed AST, BEFORE
    grounding, so the indexed sum/quantifier structure survives (grounding would
    flatten it to thousands of scalar rows). Needs no data, so it succeeds for
    declaration-only sources exactly like :func:`inspect_declarations`. Raises
    :class:`JModelError` on lex/parse errors only.
    """
    model = _Parser(tokenize(src)).parse()
    return LatexModel(
        objective=_objective_latex(model.objective) if model.objective else None,
        constraints=tuple(_constraint_latex(con) for con in model.constraints),
        variables=tuple(_vardomain_latex(model.vars[name]) for name in model.var_order),
    )
