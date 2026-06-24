#!/usr/bin/env python3
"""Coverage subset proof for Phase 12.3 — stdlib only.

Implements the D-02 line-coverage subset gate. Plans 02/03/04 invoke this
per TC-NN to justify a test deletion.

Usage:
    python scripts/cov_diff.py <legacy.json> <consolidated.json> <module-dotted>

Exit codes:
    0 — SUBSET (proof passes)
    1 — MISSING_LINES | LEGACY_EMPTY | MODULE_NOT_FOUND_LEGACY | MODULE_NOT_FOUND_CONSOLIDATED
    2 — I/O error (file missing, JSON malformed, wrong argc) OR an ambiguous
        module basename (>1 file key ends with the target suffix) — separates
        REJECT (1) from BLOCKER (2) for Plans 02/03/04. An ambiguous basename
        is a BLOCKER, never a silent pick: returning the first match could
        prove a bogus SUBSET against the wrong file.
"""

from __future__ import annotations

import json
import sys


class AmbiguousModuleKey(Exception):
    """More than one file key ends with the target suffix — cannot disambiguate.

    Raised by `_find_file_key` instead of arbitrarily returning the first match,
    which would risk validating coverage against the wrong file. Mapped to
    exit code 2 (BLOCKER) by `main`.
    """


def _normalize(path: str) -> str:
    """Backslash -> forward slash; normalize redundant separators."""
    return path.replace("\\", "/").replace("//", "/")


def _module_to_filepath(dotted: str) -> str:
    """`app.services.credits_service` -> `app/services/credits_service.py`."""
    return dotted.replace(".", "/") + ".py"


def _find_file_key(files: dict, target_path: str) -> str | None:
    """Locate the file key in `files` whose normalized path matches target_path.

    Exact normalized match wins. Otherwise fall back to a unique suffix match
    (`.../<target>`). If MORE THAN ONE key matches the suffix, the basename is
    ambiguous and we raise `AmbiguousModuleKey` rather than silently picking the
    first — picking arbitrarily could prove a SUBSET against the wrong file.
    """
    target_norm = _normalize(target_path)
    for key in files:
        if _normalize(key) == target_norm:
            return key
    suffix = "/" + target_norm
    suffix_matches = [key for key in files if _normalize(key).endswith(suffix)]
    if len(suffix_matches) > 1:
        raise AmbiguousModuleKey(
            f"ambiguous module basename: {len(suffix_matches)} file keys end with "
            f"'{suffix}': {sorted(suffix_matches)}. Pass a more specific module path "
            f"so exactly one file matches."
        )
    if suffix_matches:
        return suffix_matches[0]
    return None


def diff(legacy_path: str, consolidated_path: str, module: str) -> dict:
    target = _module_to_filepath(module)
    with open(legacy_path, encoding="utf-8") as f:
        legacy = json.load(f)
    with open(consolidated_path, encoding="utf-8") as f:
        cons = json.load(f)

    legacy_key = _find_file_key(legacy.get("files", {}), target)
    cons_key = _find_file_key(cons.get("files", {}), target)

    if legacy_key is None:
        return {
            "module": module,
            "module_file": target,
            "is_subset": False,
            "verdict": "MODULE_NOT_FOUND_LEGACY",
            "note": "Legacy test did not execute or import this module.",
        }
    if cons_key is None:
        return {
            "module": module,
            "module_file": target,
            "is_subset": False,
            "verdict": "MODULE_NOT_FOUND_CONSOLIDATED",
            "note": "Consolidated test did not execute or import this module.",
        }

    legacy_exec = set(legacy["files"][legacy_key]["executed_lines"])
    cons_exec = set(cons["files"][cons_key]["executed_lines"])
    missing = legacy_exec - cons_exec

    if not legacy_exec:
        return {
            "module": module,
            "module_file": target,
            "is_subset": False,
            "legacy_count": 0,
            "consolidated_count": len(cons_exec),
            "verdict": "LEGACY_EMPTY",
            "note": "Legacy test executed ZERO lines of target module — vacuous subset.",
        }

    is_subset = not missing
    return {
        "module": module,
        "module_file": target,
        "legacy_count": len(legacy_exec),
        "consolidated_count": len(cons_exec),
        "legacy_executed": sorted(legacy_exec),
        "consolidated_executed": sorted(cons_exec),
        "missing_in_consolidated": sorted(missing),
        "is_subset": is_subset,
        "verdict": "SUBSET" if is_subset else "MISSING_LINES",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "usage: cov_diff.py <legacy.json> <consolidated.json> <module-dotted>", file=sys.stderr
        )
        return 2
    try:
        result = diff(argv[1], argv[2], argv[3])
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cov_diff.py: I/O or parse error: {exc}", file=sys.stderr)
        return 2
    except AmbiguousModuleKey as exc:
        print(f"cov_diff.py: {exc}", file=sys.stderr)
        return 2
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if result.get("is_subset") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
