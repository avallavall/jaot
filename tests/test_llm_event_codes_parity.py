"""Cross-language parity test for the LLM event code contract.

``LLMErrorCode`` and ``LLMStatusCode`` are defined twice — once as a
Python enum in ``app/services/llm/errors.py`` and once as a TypeScript
string union in ``frontend/src/lib/llm-event-codes.ts``. This test
diffs the two and fails if a code is added on one side without being
added on the other, so we catch frontend/backend drift at test time
instead of discovering it from a missing-message toast in production.

Also verifies that every Python code has a matching i18n key entry in
``ERROR_I18N_KEY`` / ``STATUS_I18N_KEY`` so ``resolveErrorKey()`` and
``resolveStatusKey()`` can never lose a code on the lookup side.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.llm.errors import LLMErrorCode, LLMStatusCode

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TS_FILE = _REPO_ROOT / "frontend" / "src" / "lib" / "llm-event-codes.ts"


def _ts_source() -> str:
    if not _TS_FILE.exists():
        pytest.fail(f"llm-event-codes.ts not found at {_TS_FILE}")
    return _TS_FILE.read_text(encoding="utf-8")


def _extract_union(src: str, name: str) -> set[str]:
    """Parse ``export type Name = \"a\" | \"b\" | ...`` into a set of values."""
    match = re.search(
        rf'export type {name}\s*=\s*((?:\s*\|?\s*"[^"]+")+)',
        src,
    )
    if not match:
        pytest.fail(f"{name} union not found in {_TS_FILE.name}")
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _extract_record_keys(src: str, name: str) -> set[str]:
    """Parse ``export const NAME: Record<X, string> = { key: \"...\", ... }``."""
    # Match non-greedy up to the closing brace of the record literal
    match = re.search(
        rf"export const {name}\s*:\s*Record<[^>]+>\s*=\s*\{{([^}}]*)\}}",
        src,
    )
    if not match:
        pytest.fail(f"{name} record not found in {_TS_FILE.name}")
    body = match.group(1)
    return set(re.findall(r"(\w+)\s*:", body))


def test_llm_error_code_parity_with_frontend() -> None:
    """Backend LLMErrorCode values must match frontend LLMErrorCode union."""
    src = _ts_source()
    ts_codes = _extract_union(src, "LLMErrorCode")
    py_codes = {c.value for c in LLMErrorCode}
    assert ts_codes == py_codes, (
        f"LLMErrorCode drift:\n"
        f"  only in frontend: {sorted(ts_codes - py_codes)}\n"
        f"  only in backend:  {sorted(py_codes - ts_codes)}"
    )


def test_llm_status_code_parity_with_frontend() -> None:
    """Backend LLMStatusCode values must match frontend LLMStatusCode union."""
    src = _ts_source()
    ts_codes = _extract_union(src, "LLMStatusCode")
    py_codes = {c.value for c in LLMStatusCode}
    assert ts_codes == py_codes, (
        f"LLMStatusCode drift:\n"
        f"  only in frontend: {sorted(ts_codes - py_codes)}\n"
        f"  only in backend:  {sorted(py_codes - ts_codes)}"
    )


def test_every_error_code_has_i18n_key_mapping() -> None:
    """Each LLMErrorCode must have an entry in ERROR_I18N_KEY so
    ``resolveErrorKey()`` returns a real string and never undefined."""
    src = _ts_source()
    record_keys = _extract_record_keys(src, "ERROR_I18N_KEY")
    py_codes = {c.value for c in LLMErrorCode}
    missing = py_codes - record_keys
    assert not missing, f"ERROR_I18N_KEY is missing entries for: {sorted(missing)}"


def test_every_status_code_has_i18n_key_mapping() -> None:
    """Each LLMStatusCode must have an entry in STATUS_I18N_KEY."""
    src = _ts_source()
    record_keys = _extract_record_keys(src, "STATUS_I18N_KEY")
    py_codes = {c.value for c in LLMStatusCode}
    missing = py_codes - record_keys
    assert not missing, f"STATUS_I18N_KEY is missing entries for: {sorted(missing)}"
