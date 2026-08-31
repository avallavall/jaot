"""Does the studio form send the problem the card's example describes?

A template carries three descriptions of its own input, and only one of them is
executed. ``example_input`` is what the generator is tested against.
``input_fields`` is what the studio renders as a form. ``input_schema`` is what
the API documentation shows. Nothing kept them in step, and they drifted:
twenty-five of a hundred and two disagreed.

The drift is not cosmetic, because of two lines in the studio. Both
``handleLoadExample`` and ``collectCleanValues`` in
``frontend/src/components/builder/DynamicFormRenderer.tsx`` walk
``inputFields``, not the example. So a key the example carries and the form
does not know about is dropped between "Load example" and "Solve". Measured on
the eight templates that had one: four then failed outright, and four came back
OPTIMAL with a different answer. ``mine_production_scheduling`` returned 600000
where its own example means 445909, and said optimal both times.

The row editor has the same hole one level down. ``updateRow`` spreads the
existing row, so editing a loaded example keeps a key the form cannot see, but
``makeEmptyRow`` builds a new row from the declared item properties alone. A
row the user ADDS is therefore missing every undeclared column. Measured on the
ten array fields that had one: four raised, and six built a model anyway on
silent defaults.

Six rules here. The first is the one that catches meaning; the rest catch the
shapes that lead to it.
"""

import copy
import json

import pytest

from app.data.templates import load_all_templates
from app.domains.solver.services.generators import get_generator

ALL_TEMPLATES = load_all_templates()


def _fingerprint(problem) -> str:
    """Everything about the model a dropped input could move."""
    return json.dumps(
        {
            "v": [(v.name, v.type.value, v.lower_bound, v.upper_bound) for v in problem.variables],
            "o": (problem.objective.sense.value, problem.objective.expression),
            "c": [(c.name, c.expression) for c in problem.constraints],
        },
        sort_keys=True,
    )


def _field_names(template) -> set[str]:
    return {f.name for f in (template.input_fields or [])}


def _as_the_form_sends_it(template) -> dict:
    """The payload the studio submits after "Load example", key for key."""
    names = _field_names(template)
    return {k: copy.deepcopy(v) for k, v in (template.example_input or {}).items() if k in names}


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=[t.id for t in ALL_TEMPLATES])
def test_the_form_submits_the_whole_example(template) -> None:
    """Loading the example in the studio must build the model the card means."""
    generator = get_generator(template.generator_type)
    params = template.generator_params

    expected = _fingerprint(generator.generate(copy.deepcopy(template.example_input), params))
    try:
        actual = _fingerprint(generator.generate(_as_the_form_sends_it(template), params))
    except Exception as exc:  # noqa: BLE001 - the studio would show this failure
        dropped = sorted(set(template.example_input) - _field_names(template))
        pytest.fail(
            f"{template.id}: the studio drops {dropped} from the example, and the model then "
            f"fails to build at all: {exc}"
        )

    assert actual == expected, (
        f"{template.id}: the model the studio builds from its own example is not the model "
        f"the card describes. The form has no field for "
        f"{sorted(set(template.example_input) - _field_names(template))}, so the studio drops "
        "those keys on submit and solves a different problem."
    )


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=[t.id for t in ALL_TEMPLATES])
def test_every_form_field_is_filled_by_the_example(template) -> None:
    """A field the example never fills is a field nobody has tried."""
    example = template.example_input or {}
    blank = [f.name for f in (template.input_fields or []) if f.name not in example]
    required_blank = [
        f.name for f in (template.input_fields or []) if f.required and f.name not in example
    ]
    assert not required_blank, (
        f"{template.id}: the form marks {required_blank} required, and the example does not "
        "fill it, so loading the example and pressing Solve fails validation."
    )
    assert not blank, (
        f"{template.id}: the form shows {blank}, and the example leaves it empty. Either give "
        "the example a value for it, or drop the field."
    )


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=[t.id for t in ALL_TEMPLATES])
def test_input_schema_agrees_with_the_form(template) -> None:
    """The documented input and the rendered input are the same input."""
    schema = template.input_schema or {}
    documented = set(schema.get("properties", {}))
    rendered = _field_names(template)
    assert documented == rendered, (
        f"{template.id}: input_schema documents {sorted(documented)} and the form renders "
        f"{sorted(rendered)}. Only one of them can be right."
    )
    unfilled = sorted(set(schema.get("required", [])) - set(template.example_input or {}))
    assert not unfilled, (
        f"{template.id}: input_schema calls {unfilled} required, and the example omits it."
    )


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=[t.id for t in ALL_TEMPLATES])
def test_row_columns_match_the_rows_the_example_carries(template) -> None:
    """A column the form does not declare is a column a new row will not have."""
    example = template.example_input or {}
    for field in template.input_fields or []:
        rows = example.get(field.name)
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            continue
        declared = set(((field.items or {}).get("properties") or {}))
        if not declared:
            continue
        carried = set().union(*(set(r) for r in rows if isinstance(r, dict)))
        assert not carried - declared, (
            f"{template.id}: rows of '{field.name}' carry {sorted(carried - declared)}, which "
            "the form does not declare. The studio cannot show those columns, so a row the "
            "user adds will be missing them."
        )
        assert not declared - carried, (
            f"{template.id}: the form declares {sorted(declared - carried)} on '{field.name}' "
            "and no example row fills it. Either fill it or drop the column."
        )


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=[t.id for t in ALL_TEMPLATES])
def test_number_lists_are_declared_as_numbers(template) -> None:
    """A list of numbers with no declared item type renders as text boxes.

    ``FormFieldRenderer`` reads ``field.items?.type ?? "string"``, so an
    undeclared list gets text inputs: editing a value turns 120 into "120", and
    adding one appends an empty string the generator then tries to do
    arithmetic on.
    """
    example = template.example_input or {}
    for field in template.input_fields or []:
        values = example.get(field.name)
        if not isinstance(values, list) or not values or isinstance(values[0], dict):
            continue
        numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
        if not numeric:
            continue
        declared = (field.items or {}).get("type")
        assert declared in ("number", "integer"), (
            f"{template.id}: '{field.name}' holds numbers and declares items type "
            f"{declared!r}, so the studio renders it as text boxes."
        )


def test_every_template_has_a_form() -> None:
    """A card with no fields renders an empty studio page."""
    empty = [t.id for t in ALL_TEMPLATES if not t.input_fields]
    assert not empty, f"templates with no input_fields: {empty}"
