"""A listing's generator facet has to carry the parameters the generator reads.

``ModelProjectListing`` is the marketplace facet of an official card. It stored
``generator_type``, ``input_schema``, ``input_fields`` and ``example_input``,
and not ``generator_params`` — which the generator reads on every call. So
``listing_to_template_dict`` handed the engine a template with no params, and
``TemplateEngine.render`` called ``generate(user_input, {})``.

Two routes go through that dict, and both are the normal way a person uses the
platform:

* ``POST /solve/templates/{id}/solve`` with an ``official_``-prefixed id, which
  is the id the studio's template page uses. The YAML lookup is keyed on the
  bare id, so the prefixed one misses and falls through to the listing.
* Any project forked from an official listing, which is the whole "Use in
  studio" flow — ``_resolve_generator_template`` builds the same dict.

Seventeen of the hundred and two cards carry params. Measured with them
dropped: six raise, and eleven build a different model and still report
optimal. property_portfolio loses its risk ceiling; max_flow stops maximising
flow; fleet_dispatch_mining stops being a max-flow model at all.

# CONTRACT-TEST: the facet is complete (see test_quality_proof §6).
"""

import pytest

from app.data.templates import load_all_templates
from app.domains.solver.services.generators import get_generator
from app.models import ModelProjectListing
from app.services.template_resolver import listing_to_template_dict

pytestmark = pytest.mark.contract

TEMPLATES_WITH_PARAMS = [t for t in load_all_templates() if t.generator_params]


def test_some_templates_actually_carry_params() -> None:
    """Guards the guard: an empty list would make every test below vacuous."""
    assert TEMPLATES_WITH_PARAMS, "no template carries generator_params any more"


def test_the_listing_model_has_a_place_for_params() -> None:
    assert hasattr(ModelProjectListing, "generator_params"), (
        "ModelProjectListing lost its generator_params column; every official card "
        "that configures its generator will solve with an empty params dict."
    )


def test_the_template_dict_carries_the_params_it_was_given() -> None:
    listing = ModelProjectListing(
        model_project_id="official_example",
        name="Example",
        display_name="Example",
        description="d",
        generator_type="assignment",
        generator_params={"worker_rule": "exactly_one"},
    )
    assert listing_to_template_dict(listing)["generator_params"] == {"worker_rule": "exactly_one"}


def test_a_listing_without_params_renders_an_empty_dict() -> None:
    """A community listing has none, and the engine must still get a dict."""
    listing = ModelProjectListing(
        model_project_id="community_example",
        name="Example",
        display_name="Example",
        description="d",
        generator_type="knapsack",
        generator_params=None,
    )
    assert listing_to_template_dict(listing)["generator_params"] == {}


@pytest.mark.parametrize(
    "template", TEMPLATES_WITH_PARAMS, ids=[t.id for t in TEMPLATES_WITH_PARAMS]
)
def test_dropping_the_params_would_change_the_model(template) -> None:
    """Proves each of these cards genuinely needs its params.

    Without this the tests above could pass while the params were decorative.
    A card that raises without them is as much proof as one that changes shape.
    """
    generator = get_generator(template.generator_type)
    configured = generator.generate(template.example_input, template.generator_params)
    try:
        bare = generator.generate(template.example_input, {})
    except Exception:  # noqa: BLE001 - refusing to build is proof enough
        return
    assert (
        configured.objective.expression,
        [c.expression for c in configured.constraints],
    ) != (
        bare.objective.expression,
        [c.expression for c in bare.constraints],
    ), (
        f"{template.id} declares generator_params that change nothing. Either the "
        "generator stopped reading them or the card should drop them."
    )


@pytest.mark.parametrize(
    "template", TEMPLATES_WITH_PARAMS, ids=[t.id for t in TEMPLATES_WITH_PARAMS]
)
def test_the_seeded_listing_matches_the_yaml(template, db_session) -> None:
    """The seeder copies the facet; a field it forgets is a field that is lost."""
    from app.shared.db.seed_models import _apply_listing_fields

    listing = ModelProjectListing(model_project_id=f"official_{template.id}")
    _apply_listing_fields(listing, template, list(template.tags), "org_test")
    assert listing.generator_params == template.generator_params
    assert listing_to_template_dict(listing)["generator_params"] == template.generator_params
