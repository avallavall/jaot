"""Does each template's model actually answer the question its card asks?

``test_template_solve.py`` checks that a template generates and that the solver
returns "optimal". Neither of those catches the failure that mattered most: a
generator that reads the item names, ignores every price, capacity and demand,
and hands back a model that is optimal for a question nobody asked. Eleven
templates shipped like that, and 596 passing tests said nothing.

Three gates here, strongest first.

1. Input sensitivity. Change one number in ``example_input``, rebuild, compare.
   If the model is byte-identical, that number never reached it. A card may
   carry descriptive data it does not optimise over, but it has to say so in
   ``context_fields`` — the point is that the exception is written down.

2. A non-degenerate objective. If every objective coefficient is the same, the
   objective is a constant over any solution with a fixed number of terms, so
   every feasible answer ties for "optimal" and the solver's choice is
   arbitrary. That is what a hardcoded default cost of 1 produces.

3. Known answers. The optimum for a card small enough to check by hand is
   pinned here. These are the tests that fail when a formulation quietly
   changes meaning, which no structural check can see.
"""

import copy
import json
import re

import pytest

from app.data.templates import load_all_templates
from app.domains.solver.adapters import register_default_adapters
from app.domains.solver.services.generators import get_generator

ALL_TEMPLATES = load_all_templates()
register_default_adapters()

# ---------------------------------------------------------------------------
# The ratchet.
#
# These templates fail a gate today. Listing one marks it xfail(strict=True),
# so the build stays green while the debt is visible — and the moment a listed
# template starts passing, pytest reports XPASS and the build FAILS until the
# name is deleted. The list can only shrink. It is not an exemption: nothing
# may be added to it without a repair going the other way, and a NEW template
# is never allowed in at all.
#
# Do not confuse this with the _SOLVER_KNOWN_ISSUES set this file replaced.
# That one asserted "the solver did not crash", grew silently, and still named
# eleven templates that had been fixed months earlier.
# ---------------------------------------------------------------------------

UNREAD_INPUTS_RATCHET: frozenset[str] = frozenset(
    {
        # routing: the distance matrix and every demand go unread
        "vehicle_routing",
        "drug_distribution",
        "pick_route_optimization",
        # bin packing / cutting: item sizes and order quantities go unread
        "container_loading",
        "one_d_cutting_stock",
        "fabric_cutting",
        # portfolio: risk and exposure figures go unread
        "media_mix_optimization",
        "risk_pool_optimization",
        "property_portfolio",
        "tenant_mix_optimization",
        # scheduling: durations, deadlines and resource needs go unread
        "project_scheduling",
        "production_line_scheduling",
        "dye_batch_scheduling",
        "drug_trial_scheduling",
        "train_timetabling",
        "vessel_scheduling",
        # network: arc costs and contamination levels go unread
        "max_flow",
        "network_redundancy",
        "wastewater_treatment_allocation",
        # production / blending: throughput and one composition component
        "reactor_optimization",
        "chemical_blending",
        "markdown_pricing",
        "ad_campaign_budget",
        "emergency_response_allocation",
        # Repaired cards still carrying descriptive figures their model does not
        # optimise over. Each needs either a use or a context_fields entry.
        "cell_tower_placement",
        "public_facility_location",
        "claims_adjuster_assignment",
        "fleet_dispatch_mining",
        "harvest_scheduling",
        "port_berth_allocation",
        "rolling_stock_assignment",
        "track_maintenance_scheduling",
        "warehouse_slotting",
        "wildfire_resource_deployment",
    }
)

FLAT_OBJECTIVE_RATCHET: frozenset[str] = frozenset(
    {
        "cash_flow_planning",
        "drug_distribution",
        "pick_route_optimization",
        "tournament_scheduling",
        "train_timetabling",
        "vessel_scheduling",
        "wastewater_treatment_allocation",
    }
)


def _build(template):
    return get_generator(template.generator_type).generate(
        template.example_input, template.generator_params
    )


def _fingerprint(problem) -> str:
    """Everything about the model a changed input could move."""
    return json.dumps(
        {
            "v": [(v.name, v.type.value, v.lower_bound, v.upper_bound) for v in problem.variables],
            "o": (problem.objective.sense.value, problem.objective.expression),
            "c": [(c.name, c.expression) for c in problem.constraints],
        },
        sort_keys=True,
    )


def _numeric_paths(obj, path=()):
    """(path, value) for every int/float leaf, bools excluded."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _numeric_paths(value, path + (key,))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _numeric_paths(value, path + (i,))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield path, obj


def _set_path(obj, path, value) -> None:
    cursor = obj
    for step in path[:-1]:
        cursor = cursor[step]
    cursor[path[-1]] = value


def _field_name(path) -> str:
    """The last non-index element of a path — the field the number belongs to."""
    for step in reversed(path):
        if isinstance(step, str):
            return step
    return ".".join(str(p) for p in path)


@pytest.mark.parametrize(
    "template",
    [
        pytest.param(
            t,
            marks=pytest.mark.xfail(
                strict=True, reason="on the unread-inputs ratchet; delete the name when fixed"
            ),
        )
        if t.id in UNREAD_INPUTS_RATCHET
        else t
        for t in ALL_TEMPLATES
    ],
    ids=[t.id for t in ALL_TEMPLATES],
)
def test_every_number_in_the_example_reaches_the_model(template) -> None:
    """A number the model never reads is data the card only pretends to use."""
    baseline = _fingerprint(_build(template))
    declared = set(template.context_fields)

    ignored: list[str] = []
    for path, value in _numeric_paths(template.example_input):
        if _field_name(path) in declared:
            continue
        probe = copy.deepcopy(template.example_input)
        changed = int(value * 2 + 7) if isinstance(value, int) else value * 1.37 + 3.1
        if changed == value:
            changed = value + 1
        _set_path(probe, path, changed)
        try:
            moved = _fingerprint(
                get_generator(template.generator_type).generate(probe, template.generator_params)
            )
        except Exception:  # noqa: BLE001 - a rejected perturbation means it was read
            continue
        if moved == baseline:
            ignored.append(".".join(str(p) for p in path))

    assert not ignored, (
        f"{template.id}: changing these numbers leaves the model identical, so the "
        f"generator never reads them: {', '.join(ignored[:8])}"
        f"{f' (+{len(ignored) - 8} more)' if len(ignored) > 8 else ''}. "
        "Either read them in the generator, or list the field in the template's "
        "context_fields to say the model deliberately ignores it."
    )


@pytest.mark.parametrize(
    "template",
    [
        pytest.param(
            t,
            marks=pytest.mark.xfail(
                strict=True, reason="on the flat-objective ratchet; delete the name when fixed"
            ),
        )
        if t.id in FLAT_OBJECTIVE_RATCHET
        else t
        for t in ALL_TEMPLATES
    ],
    ids=[t.id for t in ALL_TEMPLATES],
)
def test_objective_distinguishes_between_solutions(template) -> None:
    """One repeated coefficient means every answer ties, and "optimal" means nothing."""
    problem = _build(template)
    coefficients = re.findall(r"(-?\d+(?:\.\d+)?)\s*\*", problem.objective.expression)
    if len(coefficients) < 2:
        pytest.skip("objective has fewer than two terms")
    assert len(set(coefficients)) > 1, (
        f"{template.id}: every objective coefficient is {coefficients[0]}, so the objective "
        "cannot tell two solutions apart and any feasible answer comes back optimal. "
        "This is what a hardcoded default cost looks like."
    )


# Optima worked out by hand from the example input. Each one pins a formulation,
# not just a number: change what the model means and these move.
KNOWN_OPTIMA: dict[str, float] = {
    # 30x5 + 5x8 + 85x10 + 45x15 + 10x20 + 60x12 + 20x18, each SKU in a slot of
    # its own size class.
    "warehouse_slotting": 2995.0,
    # The four complexities, every claim reaching an in-region specialist, so no
    # urgency-scaled travel penalty is paid.
    "claims_adjuster_assignment": 16.0,
    # One idle excavator at 200 (three cost the same and two are needed) plus
    # the two moves the yard forces.
    "equipment_allocation": 202.0,
    # The single repositioning the fleet cannot avoid.
    "rolling_stock_assignment": 1.0,
    # Tanker+engine on Ridge, helicopter on Valley, a hotshot crew on Lake.
    "wildfire_resource_deployment": 145000.0,
    # 9500 opening + 1295 transport + 50 for the 10 units of cluster_4 that
    # centre A has no room for.
    "service_center_placement": 10845.0,
    # Suburb-D is the only site reaching Zone-West; Mall-E covers the other
    # three zones for 70000.
    "cell_tower_placement": 180000.0,
    # Eastside and Southend are each the only cover for one district; Northgate
    # takes the remaining two.
    "public_facility_location": 4500000.0,
    # Berth A is the only one deep enough for both 14.5 m and 15.0 m vessels.
    "port_berth_allocation": 22.0,
    # Drops exactly the two lowest priorities, 60 and 50, from 595.
    "satellite_scheduling": 485.0,
    # Cheapest-first under each capacity and minimum order.
    "ingredient_sourcing": 48910.0,
    # Earth-Obs + IoT + Tech-Demo + University: 490 kg and 3.4 m3.
    "launch_vehicle_payload": 11050000.0,
    # 510 tonnes for the least money, against a 500 tonne target.
    "emission_reduction_planning": 190000.0,
    # Every shovel saturated, both dumps inside capacity.
    "fleet_dispatch_mining": 2350.0,
}

_BY_ID = {t.id: t for t in ALL_TEMPLATES}


@pytest.mark.slow
@pytest.mark.parametrize("template_id,expected", sorted(KNOWN_OPTIMA.items()))
def test_known_optimum(template_id: str, expected: float) -> None:
    """The answer a person worked out on paper is the answer the platform gives."""
    from app.domains.solver.services.solver_service import SolverService

    template = _BY_ID[template_id]
    problem = _build(template)
    problem.options.time_limit_seconds = 60
    problem.options.verbose = False

    result = SolverService().solve(problem)

    assert str(result.status).endswith("OPTIMAL"), f"{template_id}: status {result.status}"
    assert result.objective_value == pytest.approx(expected, rel=1e-6), (
        f"{template_id}: expected {expected}, got {result.objective_value}. "
        "Either the formulation changed meaning or the example data did."
    )


def test_known_optima_cover_every_generator_that_was_repaired() -> None:
    """Guards the pins themselves: a card that loses its pin loses its cover."""
    missing = sorted(set(KNOWN_OPTIMA) - set(_BY_ID))
    assert not missing, f"KNOWN_OPTIMA names templates that no longer exist: {missing}"


def test_ratchets_only_name_templates_that_exist() -> None:
    """A stale name on the ratchet hides a gate that is no longer running."""
    known = set(_BY_ID)
    for label, names in (
        ("UNREAD_INPUTS_RATCHET", UNREAD_INPUTS_RATCHET),
        ("FLAT_OBJECTIVE_RATCHET", FLAT_OBJECTIVE_RATCHET),
    ):
        stale = sorted(names - known)
        assert not stale, f"{label} names templates that no longer exist: {stale}"
