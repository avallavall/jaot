"""Do the counts written in the docs match the code?

A number in prose rots quietly. "33 problem generators" was written when there
were 31 and stayed through two additions; "102 templates" happened to survive
only because nobody added one. The August documentation pass found the same
failure shape everywhere, and the fix that sticks is a test that reads the
sentence and counts the thing.

Each row below names a file, a pattern with one capturing group, and what the
number has to be. A pattern that stops matching fails too: the claim was
reworded and this test stopped guarding it, which is exactly how a gate ends up
running against nothing.

Only files that are **committed** may appear here. The first version of this
test also read the repository's ``CLAUDE.md``, which is gitignored: it is
present on a developer's machine and absent from a fresh checkout, so the
suite was green locally and red on CI with five ``FileNotFoundError``s.
``test_every_file_this_gate_reads_is_in_the_repository`` now catches that
before a push.
"""

import pathlib
import re
from functools import lru_cache

import pytest

from app.data.templates import load_all_templates
from app.domains.solver.services.generators import GeneratorRegistry

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = load_all_templates()


def _counts() -> dict[str, int]:
    registry = GeneratorRegistry._generators
    classes = {cls.__name__ for cls in registry.values()}
    return {
        "templates": len(TEMPLATES),
        "template_files": len(list((ROOT / "app/data/templates").glob("*.yaml"))),
        # the generic passthrough is not a problem generator
        "generators": len(classes - {"GenericGenerator"}),
        "registry_names": len(registry),
        "generators_in_use": len({t.generator_type for t in TEMPLATES}),
    }


def _pinned_optima() -> int:
    from tests.test_template_model_quality import KNOWN_OPTIMA

    return len(KNOWN_OPTIMA)


@lru_cache(maxsize=1)
def _test_suite_shape() -> dict[str, int]:
    """How many test files and test functions the repo actually holds.

    Cached: four parametrised rows pin a number from this dict, and each case
    re-parsed every test file in the repo — the same AST walk 18 times over,
    4.6 s of a suite that measures nothing new on the second pass.
    """
    import ast

    files = sorted((ROOT / "tests").rglob("test_*.py"))
    module_level = methods = 0
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                module_level += 1
            elif isinstance(node, ast.ClassDef):
                methods += sum(
                    1
                    for m in node.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and m.name.startswith("test_")
                )
    return {
        "test_files": len(files),
        "test_functions": module_level + methods,
        "module_level_tests": module_level,
        "class_method_tests": methods,
    }


def _all_counts() -> dict[str, int]:
    return {**_counts(), **_test_suite_shape(), "pinned_optima": _pinned_optima()}


CLAIMS: list[tuple[str, str, str]] = [
    ("README.md", r"(\d+) templates \+ \d+ problem generators", "templates"),
    ("README.md", r"\d+ templates \+ (\d+) problem generators", "generators"),
    ("docs/ARCHITECTURE/OVERVIEW.md", r"\*\*(\d+) problem generators\*\*", "generators"),
    ("docs/ARCHITECTURE/OVERVIEW.md", r"registry holds (\d+) names", "registry_names"),
    ("docs/ARCHITECTURE/OVERVIEW.md", r"(\d+) are reached by a template", "generators_in_use"),
    (
        "docs/ARCHITECTURE/02-backend/08-templates-and-generators.md",
        r"There are (\d+) templates across",
        "templates",
    ),
    (
        "docs/ARCHITECTURE/02-backend/08-templates-and-generators.md",
        r"across (\d+) YAML files",
        "template_files",
    ),
    (
        "docs/ARCHITECTURE/02-backend/08-templates-and-generators.md",
        r"and (\d+) problem generators plus",
        "generators",
    ),
    (
        "docs/ARCHITECTURE/02-backend/08-templates-and-generators.md",
        r"registry holds (\d+) names",
        "registry_names",
    ),
    (
        "docs/ARCHITECTURE/02-backend/08-templates-and-generators.md",
        r"(\d+) generators are reached by a template",
        "generators_in_use",
    ),
    (
        "docs/ARCHITECTURE/02-backend/08-templates-and-generators.md",
        r"(\d+) optima are pinned",
        "pinned_optima",
    ),
    ("docs/TESTING.md", r"\*\*Known optima\.\*\* (\d+) cards", "pinned_optima"),
    ("README.md", r"(\d+) of\s+them are pinned", "pinned_optima"),
    # docs/TESTING.md "By the numbers". The collected total is a measured
    # snapshot and cannot be counted without running the suite; these four can,
    # so a drift in the parts is caught even when the total is not re-measured.
    ("docs/TESTING.md", r"collected across ([\d,]+) files", "test_files"),
    ("docs/TESTING.md", r"That is ([\d,]+) test functions", "test_functions"),
    ("docs/TESTING.md", r"([\d,]+) written at module level", "module_level_tests"),
    ("docs/TESTING.md", r"and ([\d,]+) as methods on test classes", "class_method_tests"),
]


@pytest.mark.parametrize("path,pattern,key", CLAIMS, ids=[f"{p}:{k}" for p, _, k in CLAIMS])
def test_a_documented_count_matches_the_code(path: str, pattern: str, key: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(pattern, text)
    assert match, (
        f"{path}: the sentence matching /{pattern}/ is gone, so this check now guards "
        "nothing. Update the pattern together with the prose."
    )
    expected = _all_counts()[key]
    assert int(match.group(1).replace(",", "")) == expected, (
        f"{path} says {match.group(1)} for '{key}'; the code has {expected}."
    )


def test_every_file_this_gate_reads_is_in_the_repository() -> None:
    """A gitignored file is present locally and missing from a fresh checkout.

    Pointing a claim at one makes this suite pass on a developer's machine and
    fail on CI, which is the slowest possible way to learn it.
    """
    import subprocess

    try:
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available here; run this check where it is")

    committed = {path.replace("\\", "/") for path in tracked}
    untracked = sorted({path for path, _pattern, _key in CLAIMS if path not in committed})
    assert not untracked, (
        f"this gate reads {untracked}, which git does not track. A gitignored file is "
        "there locally and gone on CI, so the claim would only fail after a push."
    )


def test_the_ratchet_is_empty() -> None:
    """The docs say both ratchet sets are empty. They have to stay that way.

    A name can only be added back with a repair going the other way, and this
    test is where that trade gets noticed.
    """
    from tests.test_template_model_quality import (
        FLAT_OBJECTIVE_RATCHET,
        UNREAD_INPUTS_RATCHET,
    )

    assert not UNREAD_INPUTS_RATCHET and not FLAT_OBJECTIVE_RATCHET, (
        "docs/TESTING.md states both ratchets are empty. They are not: "
        f"unread={sorted(UNREAD_INPUTS_RATCHET)}, flat={sorted(FLAT_OBJECTIVE_RATCHET)}. "
        "Either finish the repair or correct the documentation."
    )
