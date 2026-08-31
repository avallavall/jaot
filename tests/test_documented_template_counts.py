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
"""

import pathlib
import re

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


def _all_counts() -> dict[str, int]:
    return {**_counts(), "pinned_optima": _pinned_optima()}


CLAIMS: list[tuple[str, str, str]] = [
    ("CLAUDE.md", r"(\d+) templates \(YAML-only, unified across (?:\d+) files\)", "templates"),
    ("CLAUDE.md", r"unified across (\d+) files", "template_files"),
    ("CLAUDE.md", r"(\d+) problem generators", "generators"),
    ("CLAUDE.md", r"registered under (\d+) names", "registry_names"),
    ("CLAUDE.md", r"(\d+) of the\n  generators are used by a template", "generators_in_use"),
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
    assert int(match.group(1)) == expected, (
        f"{path} says {match.group(1)} for '{key}'; the code has {expected}."
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
