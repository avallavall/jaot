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

UNREAD_INPUTS_RATCHET: frozenset[str] = frozenset()

FLAT_OBJECTIVE_RATCHET: frozenset[str] = frozenset(
    {
        # a round robin encoded as a shift roster: every team is an "employee"
        # with hourly_cost 1, so the objective counts shifts
        "tournament_scheduling",
    }
)


#: Cards whose objective genuinely carries one coefficient throughout. This is
#: NOT the ratchet: nothing here is debt, and an entry needs a reason that
#: survives reading. A single credit line has a single rate, so minimizing
#: "borrowing x rate" over the periods is the same thing as minimizing total
#: borrowing — and the period balance rows are what tell the variables apart.
FLAT_OBJECTIVE_IS_CORRECT: dict[str, str] = {
    "cash_flow_planning": "one credit line at one rate; the balance rows distinguish the periods",
}


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


def _model_moves(template, path, value, baseline: str) -> bool:
    """Does changing this one number change the model, in either direction?"""
    candidates: list[float | int] = []
    if isinstance(value, int):
        candidates = [value * 2 + 7, value // 2 - 1]
    else:
        candidates = [value * 1.37 + 3.1, value * 0.41 - 1.7]

    for changed in candidates:
        if changed == value:
            continue
        probe = copy.deepcopy(template.example_input)
        _set_path(probe, path, changed)
        try:
            moved = _fingerprint(
                get_generator(template.generator_type).generate(probe, template.generator_params)
            )
        except Exception:  # noqa: BLE001 - a rejected perturbation means it was read
            return True
        if moved != baseline:
            return True
    return False


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
        # Probe up AND down. A limit with slack in it does not move the model
        # when it is loosened, so raising alone would report a berth's depth or
        # a unit's seat count as unread when the model reads both.
        if _model_moves(template, path, value, baseline):
            continue
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
    if template.id in FLAT_OBJECTIVE_IS_CORRECT:
        pytest.skip(FLAT_OBJECTIVE_IS_CORRECT[template.id])
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
    # Each SKU in a slot of its own size class AND rated for its weight: the
    # 40 kg pallet has exactly one home (A-01, rated 45) and the 8 kg case is
    # shut out of the nearest bin (B-01, rated 6). 25 + 240 + 850 + 675 + 200
    # + 720 + 360.
    "warehouse_slotting": 3070.0,
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
    # 109 metres of order against 12-metre bars: ceil(109/12) = 10 is the
    # material lower bound, so the plan provably cannot do better.
    "one_d_cutting_stock": 10.0,
    # 6 + 12 + 18 + 18 months. The two pivotal arms cannot run together: each
    # draws 1600/18 = 88.9 patients a month against a site network of 175.
    "drug_trial_scheduling": 54.0,
    # 320 t of polyethylene and 200 t of polypropylene, both capped by
    # feedstock. Margins of 45 - 2.5x8 = 25 and 52 - 3.0x10 = 22, so 12400,
    # less 500 units on the cheapest reactor at 12/0.85 and the last 20 at
    # 15/0.9.
    "reactor_optimization": 5007.84316,
    # Brute force over all 255 subsets agrees: 7.8M of the 8M budget, weighted
    # risk 0.1104 against a 0.13 ceiling.
    "property_portfolio": 494100.0,
    # Everything ships except Rolls-Paper, the lowest value per cubic metre at
    # 500 against 527 and 533. 67700 - 2500.
    "container_loading": 65200.0,
    # Two headway clashes at the preferred times. IC-201 and IC-205 both reach
    # Leiden-Rotterdam at minute 20, and both carry priority 9, so the cheapest
    # repair is one of them moving the full 5-minute headway: 45. FR-801 then
    # enters that segment 3 minutes behind RE-503 and shifts 2 at priority 3: 6.
    "train_timetabling": 51.0,
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
