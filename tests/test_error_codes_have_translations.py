"""Every error code the API raises has words in the frontend.

A ``CodedHTTPException`` carries an English ``detail`` and a ``code``. The page
renders the code from ``errors.codes`` in the reader's language and falls back
to the English detail when the code has no entry, silently. Three review
refusals had no code at all and reached every locale in English (found driving
the marketplace, 2026-09-25).

``check-i18n`` makes the five locales agree with each other; this test makes the
English file agree with the backend.

# CONTRACT-TEST: every literal code passed to CodedHTTPException has an
# ``errors.codes`` entry in frontend/messages/en.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_MESSAGES = _REPO / "frontend" / "messages" / "en.json"
_RAISE = re.compile(r"CodedHTTPException\((?P<args>.*?)\n\s*\)", re.S)
_CODE = re.compile(r'\bcode="(?P<code>[a-z0-9_]+(?:\.[a-z0-9_]+)+)"')


def _raised_codes() -> dict[str, str]:
    """``{code: file}`` for every literal code in a CodedHTTPException call."""
    found: dict[str, str] = {}
    for path in (_REPO / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "CodedHTTPException(" not in source:
            continue
        for call in _RAISE.finditer(source):
            for match in _CODE.finditer(call.group("args")):
                found.setdefault(match.group("code"), str(path.relative_to(_REPO)))
    return found


def _translated(codes: dict, dotted: str) -> bool:
    node = codes
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, str) and bool(node.strip())


def test_the_scan_finds_the_codes_it_should() -> None:
    codes = _raised_codes()
    # Known codes from different routers, so a broken regex cannot pass empty.
    assert "review.own_model" in codes
    assert "review.requires_use" in codes
    assert len(codes) > 10


def test_every_raised_code_has_words() -> None:
    catalogue = json.loads(_MESSAGES.read_text(encoding="utf-8"))["errors"]["codes"]
    missing = sorted(
        f"{code} ({where})"
        for code, where in _raised_codes().items()
        if not _translated(catalogue, code)
    )
    assert missing == [], f"codes with no errors.codes entry in en.json: {missing}"


# The JModel compiler names its failures the same way, without the HTTP class:
# `JModelError(..., code="jmodel.…")`, rendered by the editor from errors.codes.
# "model grounds to zero variables" had no code and was English in every
# locale (found driving the studio, 2026-09-24).
_JMODEL_CODE = re.compile(r'\bcode="(?P<code>jmodel\.[a-z0-9_]+)"')


def _jmodel_codes() -> dict[str, str]:
    """``{code: file}`` for every literal ``jmodel.*`` code in the backend."""
    found: dict[str, str] = {}
    for path in (_REPO / "app").rglob("*.py"):
        for match in _JMODEL_CODE.finditer(path.read_text(encoding="utf-8")):
            found.setdefault(match.group("code"), str(path.relative_to(_REPO)))
    return found


def test_every_jmodel_code_has_words() -> None:
    codes = _jmodel_codes()
    assert "jmodel.unknown_symbol" in codes, "the scan found nothing"
    assert "jmodel.zero_variables" in codes

    catalogue = json.loads(_MESSAGES.read_text(encoding="utf-8"))["errors"]["codes"]
    missing = sorted(
        f"{code} ({where})" for code, where in codes.items() if not _translated(catalogue, code)
    )
    assert missing == [], f"JModel codes with no errors.codes entry in en.json: {missing}"
