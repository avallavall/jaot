"""AMPL ``.dat`` subset parser (S2c) — data files for JModel datasets.

Parses the small, dataset-shaped subset of AMPL's data format:

    set I := a b c;                 # members separated by spaces (commas optional)
    set ARCS := (a,b) (b,c);        # tuple members of an N-dimensional set
    param cap := 10;                # scalar
    param w := a 2, b 3, c 4;       # 1-D: key value pairs, comma-separated
    param c := a p 1, a q 2;        # N-D: N key tokens + value; arity inferred

and produces OUR dataset ``data_json`` shape (``{"sets": {...}, "params": {...}}``,
composite param keys comma-joined — the same encoding the datasets API stores).
``#`` starts a comment. Errors raise :class:`JModelError` with a character position.

Pure module: imports only the compiler's error type — it must stay inside the
``DSL domain imports only app.schemas`` import-linter contract.
"""

from __future__ import annotations

import re
from typing import Any

from app.domains.dsl.compiler import JModelError

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>\#[^\n]*)
  | (?P<assign>:=)
  | (?P<comma>,)
  | (?P<semi>;)
  | (?P<lparen>\()
  | (?P<rparen>\))
  | (?P<word>[A-Za-z0-9_.+\-]+)
    """,
    re.VERBOSE,
)

_NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def _tokenize(src: str) -> list[tuple[str, str, int]]:
    """(kind, text, pos) tokens, whitespace/comments dropped."""
    tokens: list[tuple[str, str, int]] = []
    i = 0
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m:
            raise JModelError(f"illegal character {src[i]!r} in .dat file", position=i)
        kind = m.lastgroup or ""
        if kind not in ("ws", "comment"):
            tokens.append((kind, m.group(), i))
        i = m.end()
    return tokens


class _DatParser:
    def __init__(self, tokens: list[tuple[str, str, int]], src_len: int) -> None:
        self.tokens = tokens
        self.i = 0
        self.src_len = src_len

    def _peek(self) -> tuple[str, str, int]:
        if self.i < len(self.tokens):
            return self.tokens[self.i]
        return ("eof", "", self.src_len)

    def _next(self) -> tuple[str, str, int]:
        tok = self._peek()
        self.i += 1
        return tok

    def _expect(self, kind: str, what: str) -> tuple[str, str, int]:
        tok = self._next()
        if tok[0] != kind:
            raise JModelError(f"expected {what} (got {tok[1] or 'end of file'!r})", position=tok[2])
        return tok

    def parse(self) -> dict[str, Any]:
        sets: dict[str, list[str]] = {}
        params: dict[str, Any] = {}
        while self._peek()[0] != "eof":
            kind, text, pos = self._next()
            if kind != "word" or text not in ("set", "param"):
                raise JModelError(
                    f"expected 'set' or 'param' (got {text or 'end of file'!r})", position=pos
                )
            _, name, name_pos = self._expect("word", "a name")
            if (name in sets) or (name in params):
                raise JModelError(f"duplicate symbol {name!r}", position=name_pos)
            self._expect("assign", "':='")
            if text == "set":
                sets[name] = self._parse_set_members(name)
            else:
                params[name] = self._parse_param_value(name)
        return {"sets": sets, "params": params}

    def _parse_set_members(self, name: str) -> list[str]:
        members: list[str] = []
        while True:
            kind, text, pos = self._next()
            if kind == "semi":
                if not members:
                    raise JModelError(f"set {name!r} has no members", position=pos)
                return members
            if kind == "comma":
                continue
            if kind == "word":
                members.append(text)
                continue
            if kind == "lparen":
                # `(a, b)` — a tuple member of an N-dimensional set; stored in the
                # dataset shape's comma-joined encoding ("a,b").
                members.append(self._parse_tuple_member(name, pos))
                continue
            raise JModelError(
                f"expected a member or ';' in set {name!r} (got {text or 'end of file'!r})",
                position=pos,
            )

    def _parse_tuple_member(self, name: str, open_pos: int) -> str:
        parts: list[str] = []
        expect_word = True
        while True:
            kind, text, pos = self._next()
            if kind == "word" and expect_word:
                parts.append(text)
                expect_word = False
                continue
            if kind == "comma" and not expect_word:
                expect_word = True
                continue
            if kind == "rparen" and not expect_word:
                if len(parts) < 2:
                    raise JModelError(
                        f"tuple member in set {name!r} needs at least two components",
                        position=open_pos,
                    )
                return ",".join(parts)
            raise JModelError(
                f"malformed tuple member in set {name!r} (got {text or 'end of file'!r})",
                position=pos,
            )

    def _parse_param_value(self, name: str) -> Any:
        """Scalar number, or comma-separated entries of N key tokens + a value."""
        entries: list[tuple[list[str], float, int]] = []  # (key parts, value, pos)
        group: list[tuple[str, int]] = []
        while True:
            kind, text, pos = self._next()
            if kind in ("semi", "comma"):
                if not group:
                    raise JModelError(
                        f"empty entry in param {name!r} (stray {text!r})", position=pos
                    )
                entries.append(self._close_entry(name, group))
                group = []
                if kind == "semi":
                    break
                continue
            if kind == "word":
                group.append((text, pos))
                continue
            raise JModelError(
                f"unterminated param {name!r} (missing ';')",
                position=pos,
            )

        if len(entries) == 1 and not entries[0][0]:
            return entries[0][1]  # scalar

        arity = len(entries[0][0])
        if arity == 0:
            raise JModelError(
                f"param {name!r} mixes a scalar with keyed entries", position=entries[0][2]
            )
        values: dict[str, float] = {}
        for key_parts, value, pos in entries:
            if len(key_parts) != arity:
                raise JModelError(
                    f"param {name!r} entries disagree on arity "
                    f"({len(key_parts)} keys here, {arity} in the first entry)",
                    position=pos,
                )
            key = ",".join(key_parts)
            if key in values:
                raise JModelError(f"param {name!r} has a duplicate key {key!r}", position=pos)
            values[key] = value
        return values

    def _close_entry(self, name: str, group: list[tuple[str, int]]) -> tuple[list[str], float, int]:
        """Split a token group into (key parts, numeric value); last token = value."""
        value_text, value_pos = group[-1]
        if not _NUM_RE.match(value_text):
            raise JModelError(
                f"param {name!r} entry must end in a number (got {value_text!r})",
                position=value_pos,
            )
        value = float(value_text)
        keys = [text for text, _ in group[:-1]]
        return (keys, value, group[0][1])


def parse_dat(src: str) -> dict[str, Any]:
    """Parse an AMPL ``.dat`` subset into the dataset ``data_json`` shape.

    Raises :class:`JModelError` (message + character position) on any lex or
    parse error. The result still goes through the normal dataset validation
    (:class:`JModelData`) before being stored.
    """
    return _DatParser(_tokenize(src), len(src)).parse()
