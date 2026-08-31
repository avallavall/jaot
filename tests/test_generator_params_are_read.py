"""Does the generator actually read every key the card's generator_params sets?

``generator_params`` is a free-form dict. A generator reads the keys it knows
and ignores the rest in silence, so one misspelled key produces a model built
without that rule — no error, no warning, and an answer the solver still calls
optimal. Measured across the 17 param-carrying cards, misspelling a single key
silently changed the model for 23 of 43 keys, including ``mode``, where losing
it reverts ``serve_all`` to ``select`` and the plan stops having to serve
anything.

The check reads each generator module's source and collects every literal key
it takes off ``params`` (``params.get("x")`` and ``params["x"]``), then compares
each card's declared keys against that set. It is a static read, so it costs
nothing at runtime and it fails in CI rather than in front of a user.
"""

import ast
import pathlib

import pytest

from app.data.templates import load_all_templates
from app.domains.solver.services.generators import GeneratorRegistry

ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATORS_DIR = ROOT / "app" / "domains" / "solver" / "services" / "generators"

ALL_TEMPLATES = load_all_templates()
PARAMETRIZED = [t for t in ALL_TEMPLATES if t.generator_params]


def _keys_read_off_params(module_path: pathlib.Path) -> set[str]:
    """Every literal key the module takes off a local named ``params``."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "params"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "params"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def _module_for(generator_type: str) -> pathlib.Path | None:
    generator_class = GeneratorRegistry._generators.get(generator_type)
    if generator_class is None:
        return None
    path = GENERATORS_DIR / f"{generator_class.__module__.rsplit('.', 1)[-1]}.py"
    return path if path.exists() else None


@pytest.mark.parametrize("template", PARAMETRIZED, ids=[t.id for t in PARAMETRIZED])
def test_every_generator_param_the_card_sets_is_read(template) -> None:
    """A key the generator never looks at is a rule the card only pretends to set."""
    module = _module_for(template.generator_type)
    assert module is not None, (
        f"{template.id}: generator_type {template.generator_type!r} resolves to no module, "
        "so its params cannot be checked and GeneratorRegistry.get would fall back "
        "to the generic passthrough."
    )

    accepted = _keys_read_off_params(module)
    unread = sorted(set(template.generator_params) - accepted)
    assert not unread, (
        f"{template.id}: generator_params sets {unread}, which {module.name} never reads. "
        f"It reads {sorted(accepted)}. A key nobody reads is silently dropped, and the "
        "card renders a different model that still solves to 'optimal'."
    )
