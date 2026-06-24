"""Tier-1 anti-pattern check. See tests/test_quality_proof.md S2.

Exit 1 if any test file in argv contains MagicMock(spec=Session),
patch(...get_session), patch(...get_current_user), or the equivalent
patch.object(...) forms, without a valid `# test-quality-skip: <reason
>=25 chars>` marker on the same line or up to 3 lines above. conftest.py
files are exempt (D-02).

Matching is done on the whole source with DOTALL so a `patch(` call that
ruff has wrapped across multiple lines (long dotted target on its own line)
is still caught; the violation is reported on the line where the match
begins. The skip marker is only honored when it lives in a REAL comment
(located via tokenize), never inside a string literal or assert message.
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

# DOTALL so a target argument wrapped onto a following line still matches.
# `findall`/`finditer` (not `search`) is used so multiple violations are all
# counted, including several on the same logical line.
PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"MagicMock\s*\(\s*spec\s*=\s*Session\s*\)", re.DOTALL),
        "MagicMock(spec=Session) fakes the DB session. See test_quality_proof.md S2.",
    ),
    (
        re.compile(r"patch\s*\([^)]*get_session\b", re.DOTALL),
        "patch(...get_session) substitutes the DB session. See test_quality_proof.md S2.",
    ),
    (
        re.compile(r"patch\s*\([^)]*get_current_user\b", re.DOTALL),
        "patch(...get_current_user) substitutes auth. See test_quality_proof.md S2.",
    ),
    (
        re.compile(r"patch\s*\.\s*object\s*\([^)]*get_session\b", re.DOTALL),
        "patch.object(...get_session) substitutes the DB session. See test_quality_proof.md S2.",
    ),
    (
        re.compile(r"patch\s*\.\s*object\s*\([^)]*get_current_user\b", re.DOTALL),
        "patch.object(...get_current_user) substitutes auth. See test_quality_proof.md S2.",
    ),
)

SKIP_RE = re.compile(r"#\s*test-quality-skip:\s*(?P<just>[^\n]+)")
FORBIDDEN_IN_JUST = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
LOOKBACK_LINES = 3


def _comment_lines(text: str) -> set[int]:
    """Return the set of line numbers that contain a REAL Python comment.

    Uses tokenize so a `# test-quality-skip:` substring living inside a string
    literal or an assert message is NOT treated as a comment (false-negative
    (c) in the review). On a tokenize error (syntactically invalid file) we
    return an empty set, which fails closed: no line is treated as carrying a
    skip marker, so nothing is silently exempted.
    """
    out: set[int] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                out.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return set()
    return out


def has_valid_skip(lines: list[str], comment_lines: set[int], lineno: int) -> bool:
    """True if a valid skip marker sits on `lineno` or within LOOKBACK_LINES above.

    The marker is only honored on lines that tokenize identified as carrying a
    real comment, so a skip marker embedded in a string/assert does not count.
    """
    start = max(0, lineno - 1 - LOOKBACK_LINES)
    for offset, candidate in enumerate(lines[start:lineno], start=start + 1):
        if offset not in comment_lines:
            continue
        m = SKIP_RE.search(candidate)
        if not m:
            continue
        just = m.group("just").strip()
        if len(just) >= 25 and not FORBIDDEN_IN_JUST.search(just):
            return True
    return False


def check_file(path: Path) -> int:
    if path.name == "conftest.py":
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    lines = text.splitlines()
    comment_lines = _comment_lines(text)
    violations = 0
    for pattern, msg in PATTERNS:
        for match in pattern.finditer(text):
            # 1-based line where the match begins (handles wrapped calls).
            lineno = text.count("\n", 0, match.start()) + 1
            if not has_valid_skip(lines, comment_lines, lineno):
                print(f"{path}:{lineno}: {msg}", file=sys.stderr)
                violations += 1
    return violations


def iter_target_files(argv: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in argv:
        p = Path(raw)
        if p.is_file() and p.suffix == ".py":
            out.append(p)
        elif p.is_dir():
            out.extend(sorted(p.rglob("*.py")))
    return out


def main(argv: list[str]) -> int:
    return 1 if sum(check_file(p) for p in iter_target_files(argv)) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
