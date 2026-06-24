"""Unit tests for scripts/cov_diff.py (D-02 subset gate; see PATTERNS Pattern 2).

Exit codes: 0 SUBSET / 1 REJECT-verdicts / 2 BLOCKER. Pattern adapted from
tests/scripts/test_check_test_quality_tier1.py. Subprocess-driven; no DB.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cov_diff.py"

DEFAULT_MODULE = "app.services.credits_service"
DEFAULT_FILEPATH = "app/services/credits_service.py"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke cov_diff.py with the given argv tail."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_cov_json(
    tmp_path: Path,
    executed_lines: list[int] | None,
    name: str = "cov.json",
    module_path: str = DEFAULT_FILEPATH,
) -> Path:
    """Write a minimal pytest-cov shaped JSON fixture.

    `executed_lines=None` means the module is absent from the `files` mapping
    (simulates MODULE_NOT_FOUND); empty list `[]` means the module is present
    with zero executed lines (simulates LEGACY_EMPTY).
    """
    files: dict[str, dict] = {}
    if executed_lines is not None:
        files[module_path] = {"executed_lines": executed_lines}
    payload = {"files": files}
    target = tmp_path / name
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def write_cov_json_keys(
    tmp_path: Path,
    keyed_lines: dict[str, list[int]],
    name: str = "cov.json",
) -> Path:
    """Write a pytest-cov shaped JSON fixture with arbitrary file keys.

    Used to construct ambiguous-basename fixtures: two distinct keys that both
    end with the same `/app/services/credits_service.py` suffix.
    """
    files = {key: {"executed_lines": lines} for key, lines in keyed_lines.items()}
    target = tmp_path / name
    target.write_text(json.dumps({"files": files}), encoding="utf-8")
    return target


# --- argc / I/O error path (exit 2) -----------------------------------------


def test_wrong_argc_too_few_args_exits_2() -> None:
    result = run_script("only-one-arg")
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_wrong_argc_no_args_exits_2() -> None:
    result = run_script()
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_missing_file_exits_2(tmp_path: Path) -> None:
    legacy = tmp_path / "does-not-exist.json"
    cons = write_cov_json(tmp_path, [10, 11], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 2
    assert "I/O" in result.stderr or "parse error" in result.stderr


def test_malformed_json_exits_2(tmp_path: Path) -> None:
    legacy = tmp_path / "bad.json"
    legacy.write_text("{not-json", encoding="utf-8")
    cons = write_cov_json(tmp_path, [10, 11], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 2
    assert "parse error" in result.stderr or "I/O" in result.stderr


# --- SUBSET (exit 0) --------------------------------------------------------


def test_subset_exact_match(tmp_path: Path) -> None:
    legacy = write_cov_json(tmp_path, [10, 11, 12], name="legacy.json")
    cons = write_cov_json(tmp_path, [10, 11, 12], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 0
    assert '"verdict": "SUBSET"' in result.stdout


def test_subset_proper_subset(tmp_path: Path) -> None:
    """legacy ⊂ consolidated — consolidated covers everything plus extras."""
    legacy = write_cov_json(tmp_path, [10, 11], name="legacy.json")
    cons = write_cov_json(tmp_path, [10, 11, 12, 13, 14], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 0
    assert '"verdict": "SUBSET"' in result.stdout


def test_subset_windows_backslash_path(tmp_path: Path) -> None:
    """R6 mitigation — Windows backslash path key must equate to forward-slash."""
    legacy = write_cov_json(
        tmp_path,
        [10, 11],
        name="legacy.json",
        module_path="app\\services\\credits_service.py",
    )
    cons = write_cov_json(tmp_path, [10, 11], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 0
    assert '"verdict": "SUBSET"' in result.stdout


# --- Failure verdicts (exit 1) ----------------------------------------------


def test_subset_violation_missing_lines(tmp_path: Path) -> None:
    """Consolidated misses lines the legacy executed."""
    legacy = write_cov_json(tmp_path, [10, 11, 12], name="legacy.json")
    cons = write_cov_json(tmp_path, [10, 11], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 1
    assert '"verdict": "MISSING_LINES"' in result.stdout


def test_disjoint_sets_missing_lines(tmp_path: Path) -> None:
    """No overlap → MISSING_LINES (all legacy lines are missing)."""
    legacy = write_cov_json(tmp_path, [10, 11, 12], name="legacy.json")
    cons = write_cov_json(tmp_path, [20, 21, 22], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 1
    assert '"verdict": "MISSING_LINES"' in result.stdout


def test_legacy_empty_is_hard_reject(tmp_path: Path) -> None:
    """RESEARCH § 1.3: vacuous subset is a hard reject (4th canonical fail)."""
    legacy = write_cov_json(tmp_path, [], name="legacy.json")
    cons = write_cov_json(tmp_path, [10, 11], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 1
    assert '"verdict": "LEGACY_EMPTY"' in result.stdout


def test_module_not_in_legacy(tmp_path: Path) -> None:
    legacy = write_cov_json(tmp_path, None, name="legacy.json")
    cons = write_cov_json(tmp_path, [10, 11], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 1
    assert '"verdict": "MODULE_NOT_FOUND_LEGACY"' in result.stdout


def test_module_not_in_consolidated(tmp_path: Path) -> None:
    legacy = write_cov_json(tmp_path, [10, 11], name="legacy.json")
    cons = write_cov_json(tmp_path, None, name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 1
    assert '"verdict": "MODULE_NOT_FOUND_CONSOLIDATED"' in result.stdout


# --- Ambiguous basename (exit 2 BLOCKER, fail-closed) -----------------------


def test_ambiguous_basename_in_legacy_exits_2(tmp_path: Path) -> None:
    """Two legacy keys ending with the same suffix → BLOCKER, not a silent pick.

    Picking the first arbitrarily could prove a bogus SUBSET against the wrong
    file. The fix fails closed with exit 2 and an explanatory message.
    """
    legacy = write_cov_json_keys(
        tmp_path,
        {
            "src/app/services/credits_service.py": [10, 11],
            "vendor/app/services/credits_service.py": [10, 11],
        },
        name="legacy.json",
    )
    cons = write_cov_json(tmp_path, [10, 11], name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 2
    assert "ambiguous" in result.stderr.lower()


def test_ambiguous_basename_in_consolidated_exits_2(tmp_path: Path) -> None:
    """Ambiguity on the consolidated side is equally a BLOCKER."""
    legacy = write_cov_json(tmp_path, [10, 11], name="legacy.json")
    cons = write_cov_json_keys(
        tmp_path,
        {
            "src/app/services/credits_service.py": [10, 11],
            "build/app/services/credits_service.py": [10, 11],
        },
        name="cons.json",
    )
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 2
    assert "ambiguous" in result.stderr.lower()


def test_unique_suffix_match_still_resolves(tmp_path: Path) -> None:
    """Control: a SINGLE non-exact suffix match still resolves (fallback intact).

    Guards against over-correcting — only >1 match is ambiguous; exactly one
    prefixed key must still be found and proven a SUBSET.
    """
    legacy = write_cov_json_keys(
        tmp_path,
        {"workspace/app/services/credits_service.py": [10, 11]},
        name="legacy.json",
    )
    cons = write_cov_json_keys(
        tmp_path,
        {"workspace/app/services/credits_service.py": [10, 11, 12]},
        name="cons.json",
    )
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == 0
    assert '"verdict": "SUBSET"' in result.stdout


# --- Parametrized verdict matrix (sanity check on the verdict→exit-code map) -


@pytest.mark.parametrize(
    "legacy_lines, cons_lines, expected_exit, expected_verdict",
    [
        ([10, 11], [10, 11], 0, "SUBSET"),
        ([10, 11], [10, 11, 12], 0, "SUBSET"),
        ([10, 11, 12], [10, 11], 1, "MISSING_LINES"),
        ([], [10, 11], 1, "LEGACY_EMPTY"),
        (None, [10, 11], 1, "MODULE_NOT_FOUND_LEGACY"),
        ([10, 11], None, 1, "MODULE_NOT_FOUND_CONSOLIDATED"),
    ],
    ids=["exact", "proper-subset", "missing", "empty", "no-legacy", "no-cons"],
)
def test_verdict_matrix(
    tmp_path: Path,
    legacy_lines: list[int] | None,
    cons_lines: list[int] | None,
    expected_exit: int,
    expected_verdict: str,
) -> None:
    legacy = write_cov_json(tmp_path, legacy_lines, name="legacy.json")
    cons = write_cov_json(tmp_path, cons_lines, name="cons.json")
    result = run_script(str(legacy), str(cons), DEFAULT_MODULE)
    assert result.returncode == expected_exit
    assert f'"verdict": "{expected_verdict}"' in result.stdout
