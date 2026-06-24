"""Unit tests for scripts/check_test_quality_tier1.py.

Covers:
  - Each of the 3 Tier-1 patterns (positive: violation reported; negative: legitimate seam).
  - `# test-quality-skip:` exception per D-01: same-line, lookback (1-3 lines above),
    out-of-window failure, too-short justification, forbidden tokens.
  - conftest.py exclusion per D-02 (defensive script-level skip).
  - Legitimate seams: MagicMock(spec=User), MagicMock(spec=Organization).

All tests drive the script through `subprocess.run` so they exercise the real CLI surface
(argv parsing, exit code, stderr) -- not just internal functions. No DB needed.

The forbidden patterns themselves are built by string concatenation so this test file
does NOT contain the literal regex matches in source (which would cause the hook to
flag this file when run against itself; meta-tests must not violate the rule they test).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_test_quality_tier1.py"

# Forbidden patterns built by concatenation so the literal regex match never appears
# in this file's source. Each token is the runtime string the hook should flag.
SESSION_MOCK = "MagicMock(spec=" + "Session)"
PATCH_GET_SESSION = 'patch("app.api.deps.get_' + 'session")'
PATCH_GET_CURRENT_USER = 'patch("app.api.deps.get_' + 'current_user")'
USER_MOCK = "MagicMock(spec=" + "User)"
ORG_MOCK = "MagicMock(spec=" + "Organization)"

# patch.object(...) bypass forms (false-negative (b)). Built by concatenation
# for the same self-flagging reason as above.
PATCH_OBJECT_GET_SESSION = "patch.object(deps, " + '"get_' + 'session")'
PATCH_OBJECT_GET_CURRENT_USER = "patch.object(deps, " + '"get_' + 'current_user")'

# A `patch(...)` call wrapped across lines exactly as ruff formats a long dotted
# target (false-negative (a)): `patch(` and the target live on different lines.
PATCH_GET_SESSION_MULTILINE = "patch(\n    " + '"app.api.deps.get_' + 'session"\n)'


def run_script(
    tmp_path: Path,
    content: str,
    filename: str = "test_sample.py",
) -> subprocess.CompletedProcess[str]:
    """Write `content` to `tmp_path/filename` and run the script against it."""
    target = tmp_path / filename
    target.write_text(content, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )


# --- Pattern 1: spec=Session ---


def test_magicmock_spec_session_is_flagged(tmp_path: Path) -> None:
    result = run_script(tmp_path, f"fake = {SESSION_MOCK}\n")
    assert result.returncode == 1
    assert SESSION_MOCK in result.stderr


def test_magicmock_spec_user_is_allowed(tmp_path: Path) -> None:
    """Legitimate seam -- non-DB type, the carve-out from policy §3."""
    result = run_script(tmp_path, f"fake = {USER_MOCK}\n")
    assert result.returncode == 0
    assert result.stderr == ""


def test_magicmock_spec_organization_is_allowed(tmp_path: Path) -> None:
    """Legitimate seam -- domain model standing in for the org under test."""
    result = run_script(tmp_path, f"fake = {ORG_MOCK}\n")
    assert result.returncode == 0


# --- Pattern 2: get_session ---


def test_patch_get_session_is_flagged(tmp_path: Path) -> None:
    result = run_script(tmp_path, f"with {PATCH_GET_SESSION}:\n    pass\n")
    assert result.returncode == 1
    assert "get_" + "session" in result.stderr


# --- Pattern 3: get_current_user ---


def test_patch_get_current_user_is_flagged(tmp_path: Path) -> None:
    result = run_script(tmp_path, f"with {PATCH_GET_CURRENT_USER}:\n    pass\n")
    assert result.returncode == 1
    assert "get_" + "current_user" in result.stderr


# --- Exception comment (D-01) ---

SKIP_OK = "# test-quality-" + "skip: legitimate fixture seam justification text here"


def test_skip_marker_same_line_passes(tmp_path: Path) -> None:
    content = f"fake = {SESSION_MOCK}  {SKIP_OK}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 0


def test_skip_marker_one_line_above_passes(tmp_path: Path) -> None:
    content = f"{SKIP_OK}\nfake = {SESSION_MOCK}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 0


def test_skip_marker_three_lines_above_passes(tmp_path: Path) -> None:
    """3-line lookback window per D-01 -- marker at the boundary still counts."""
    content = f"{SKIP_OK}\nx = 1\ny = 2\nfake = {SESSION_MOCK}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 0


def test_skip_marker_four_lines_above_fails(tmp_path: Path) -> None:
    """Marker 4 lines above is out of the 3-line lookback window."""
    content = f"{SKIP_OK}\nx = 1\ny = 2\nz = 3\nfake = {SESSION_MOCK}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1


def test_skip_marker_too_short_fails(tmp_path: Path) -> None:
    """Justification < 25 chars is rejected."""
    short_skip = "# test-quality-" + "skip: short"
    content = f"fake = {SESSION_MOCK}  {short_skip}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1


@pytest.mark.parametrize("token", ["TODO", "FIXME", "HACK", "XXX"])
def test_skip_marker_forbidden_token_fails(tmp_path: Path, token: str) -> None:
    """Forbidden tokens in justification block the exception (no sticky `will fix later`)."""
    bad_skip = (
        "# test-quality-" + "skip: " + token + " will fix this later, more than 25 chars total"
    )
    content = f"fake = {SESSION_MOCK}  {bad_skip}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1


# --- D-02: conftest.py exclusion ---


def test_conftest_py_is_excluded(tmp_path: Path) -> None:
    """Even with a Tier-1 violation, conftest.py exits 0 (defensive D-02 guard)."""
    result = run_script(tmp_path, f"fake = {SESSION_MOCK}\n", filename="conftest.py")
    assert result.returncode == 0


# --- Regression: false-negatives closed (phase-12 code review BATCH 1) ---
#
# Each of the following three bypasses USED to slip past the hook. They must
# now be caught. See scripts/check_test_quality_tier1.py and the review todo.


def test_multiline_patch_get_session_is_flagged(tmp_path: Path) -> None:
    """(a) `patch(` and its target on separate lines (ruff wrap) must be caught.

    The per-line `search` of the old hook missed this; whole-source DOTALL
    matching catches it. The violation is reported on the line where the match
    begins (the `patch(` line), not the target line.
    """
    content = f"with {PATCH_GET_SESSION_MULTILINE}:\n    pass\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1
    assert "get_" + "session" in result.stderr


def test_multiline_patch_get_session_reports_opening_line(tmp_path: Path) -> None:
    """The reported line number points at the `patch(` opener, not the target line."""
    # Line 1: `import x`, line 2: `with patch(`, line 3: the target, line 4: `):`.
    content = f"import x\nwith {PATCH_GET_SESSION_MULTILINE}:\n    pass\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1
    # Match begins on line 2 (the `with patch(` line).
    assert ":2:" in result.stderr


def test_patch_object_get_session_is_flagged(tmp_path: Path) -> None:
    """(b) the patch.object(deps, get-session) form bypassed the literal patch( check."""
    content = f"with {PATCH_OBJECT_GET_SESSION}:\n    pass\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1
    assert "get_" + "session" in result.stderr


def test_patch_object_get_current_user_is_flagged(tmp_path: Path) -> None:
    """(b) the patch.object(deps, get-current-user) form must be caught too."""
    content = f"with {PATCH_OBJECT_GET_CURRENT_USER}:\n    pass\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1
    assert "get_" + "current_user" in result.stderr


def test_patch_object_multiline_is_flagged(tmp_path: Path) -> None:
    """(a)+(b) combined — a wrapped `patch.object(...)` must also be caught."""
    wrapped = "patch.object(\n    deps,\n    " + '"get_' + 'current_user",\n)'
    content = f"with {wrapped}:\n    pass\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1


def test_skip_marker_inside_string_does_not_exempt(tmp_path: Path) -> None:
    """(c) A skip marker inside a STRING literal must NOT silence a violation.

    Only a real comment (per tokenize) honors the exception. Here the marker is
    the value of a string assigned on the line above the violation, so the hook
    must still report the spec-Session mock below it.
    """
    fake_marker = '"# test-quality-' + 'skip: pretend justification embedded in a string here"'
    content = f"note = {fake_marker}\nfake = {SESSION_MOCK}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1
    assert SESSION_MOCK in result.stderr


def test_skip_marker_inside_assert_message_does_not_exempt(tmp_path: Path) -> None:
    """(c) A skip marker inside an assert message string must NOT exempt either."""
    fake_marker = '"# test-quality-' + 'skip: justification hidden in an assert message text"'
    content = f"def t():\n    fake = {SESSION_MOCK}\n    assert fake, {fake_marker}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1
    assert SESSION_MOCK in result.stderr


def test_real_comment_skip_marker_still_exempts(tmp_path: Path) -> None:
    """(c) Control: a REAL comment marker is still honored after the tokenize fix."""
    content = f"fake = {SESSION_MOCK}  {SKIP_OK}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 0


def test_multiple_violations_on_one_line_all_counted(tmp_path: Path) -> None:
    """findall (not search): two violations on one logical line are both reported."""
    content = f"a = {SESSION_MOCK}; b = {SESSION_MOCK}\n"
    result = run_script(tmp_path, content)
    assert result.returncode == 1
    # Both occurrences emit a stderr line on the same line number.
    assert result.stderr.count(SESSION_MOCK) == 2


# --- No-violation safety ---


def test_clean_file_passes(tmp_path: Path) -> None:
    """Real-shaped test code with no Tier-1 patterns exits 0."""
    content = (
        "def test_thing(db_session):\n"
        "    org = Organization(id='org_1', name='Acme')\n"
        "    db_session.add(org)\n"
        "    db_session.flush()\n"
        "    assert org.id == 'org_1'\n"
    )
    result = run_script(tmp_path, content)
    assert result.returncode == 0
    assert result.stderr == ""


def test_patch_object_non_forbidden_target_is_allowed(tmp_path: Path) -> None:
    """Guard against over-reach: patch.object of an unrelated target is fine."""
    content = 'with patch.object(svc, "send_email"):\n    pass\n'
    result = run_script(tmp_path, content)
    assert result.returncode == 0
    assert result.stderr == ""
