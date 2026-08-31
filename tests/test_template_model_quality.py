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
import re

import pytest

from app.data.templates import load_all_templates
from app.domains.solver.adapters import register_default_adapters
from app.domains.solver.services.generators import get_generator
from tests._helpers.model_fingerprint import fingerprint

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

# The three below were added when this gate's coefficient reader was repaired.
# It used to scan for "N*" and therefore scored ZERO coefficients on an
# objective written as bare variable names, so it skipped instead of failing on
# 15 of 102 cards — the shape "every coefficient is 1" is precisely what it
# exists to catch. These three were hidden that whole time. Each one optimises a
# TOTAL that its own constraints already pin, so the total is decided and the
# schedule the card promises is picked arbitrarily among ties. Fixing them means
# giving each card a per-row weight it does not currently carry, which is a
# modelling decision about the product, not a repair to existing code.
FLAT_OBJECTIVE_RATCHET: frozenset[str] = frozenset(
    {
        # demand rows are ">= 40" etc. and the objective minimizes total water,
        # so the optimum total is the sum of demands no matter how the water is
        # split across early_morning / midday / evening. Every schedule ties.
        # Slots need a loss or cost per time of day for "scheduling" to mean
        # anything.
        "irrigation_scheduling",
        # alloc + curtail == forecast per generator-period, so total curtailment
        # is fixed by the grid caps. WHICH generator is curtailed is arbitrary.
        # Needs a per-generator curtailment cost or priority.
        "renewable_curtailment",
        # maximize the sum of releases against balance rows: the total drainable
        # volume is fixed, and which period gets the water is a tie. Needs a
        # value per period (irrigation value, or head).
        "reservoir_operation",
    }
)


#: Cards whose objective genuinely carries one coefficient throughout. This is
#: NOT the ratchet: nothing here is debt, and an entry needs a reason that
#: survives reading. A single credit line has a single rate, so minimizing
#: "borrowing x rate" over the periods is the same thing as minimizing total
#: borrowing — and the period balance rows are what tell the variables apart.
#:
#: The rest count a resource whose total is NOT pinned by any constraint, so a
#: coefficient of 1 throughout is the real objective and different answers
#: score differently. That is the opposite of the assignment bug this gate was
#: built for, where "exactly one worker per task" fixed the number of selected
#: pairs and a flat cost made every assignment tie.
FLAT_OBJECTIVE_IS_CORRECT: dict[str, str] = {
    "cash_flow_planning": "one credit line at one rate; the balance rows distinguish the periods",
    "bin_packing": "minimize how many bins are opened; nothing pins that count",
    "two_d_cutting": "minimize how many sheets are opened; nothing pins that count",
    "one_d_cutting_stock": "minimize how many stock lengths are cut; the demand rows are >=",
    "fabric_cutting": "minimize how many rolls are cut; the demand rows are >=",
    "max_flow": "the objective IS the flow value; a unit is a unit",
    "fleet_dispatch_mining": "max-flow mode: maximize tonnes moved, and a tonne is a tonne",
}


#: One objective term: an optional sign, an optional "coefficient*", a name.
#: The coefficient pattern accepts an exponent so "5e-05*x" reads as one term.
_OBJECTIVE_TERM = re.compile(
    r"(?P<sign>[+-]?)\s*"
    r"(?:(?P<coef>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*\*\s*)?"
    r"(?P<var>[A-Za-z_]\w*)"
)


def _objective_coefficients(expression: str) -> list[float]:
    """The coefficient of every term, counting a bare variable name as 1.

    Two readings that look right and are not. A plain ``findall`` for "N*" sees
    no coefficients at all in "x + y + z", so the gate skipped the very shape it
    exists to catch — every coefficient equal to 1 — on 15 of 102 cards. And
    ``ExpressionParser`` consolidates, which drops every term whose coefficient
    is zero: "0 for this pair, 1 for that one" then looks flat when it is the
    distinction the model turns on. No objective in the catalogue multiplies two
    variables, so scanning terms is exact here.
    """
    coefficients: list[float] = []
    for match in _OBJECTIVE_TERM.finditer(expression):
        raw = match.group("coef")
        value = float(raw) if raw is not None else 1.0
        coefficients.append(-value if match.group("sign") == "-" else value)
    return coefficients


def _build(template):
    return get_generator(template.generator_type).generate(
        template.example_input, template.generator_params
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
            moved = fingerprint(
                get_generator(template.generator_type).generate(probe, template.generator_params)
            )
        except ValueError:
            # A ValueError is the generators' deliberate refusal, so the number
            # reached a check and counts as read. Anything else — KeyError,
            # TypeError, IndexError — is the perturbation breaking the generator,
            # which proves nothing about whether the number is used. Catching
            # bare Exception here scored 11 of 2308 leaves as "read" on a crash.
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
    baseline = fingerprint(_build(template))
    declared = set(template.context_fields)

    ignored: list[str] = []
    # A context_fields entry matches a bare field name at ANY depth and never
    # expires by itself, so the day a generator starts reading that field the
    # declaration goes on silencing it with nothing to report. Record what each
    # entry actually silenced and check it below.
    silenced: dict[str, list[tuple]] = {}
    for path, value in _numeric_paths(template.example_input):
        field = _field_name(path)
        if field in declared:
            silenced.setdefault(field, []).append((path, value))
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

    # An exemption that no longer exempts anything is a claim nobody checked.
    stale = [
        field
        for field, leaves in silenced.items()
        if all(_model_moves(template, path, value, baseline) for path, value in leaves)
    ]
    assert not stale, (
        f"{template.id}: context_fields still lists {stale}, but the generator now reads "
        "every one of those numbers. Delete the entry — an exemption that silences "
        "nothing hides the next field that goes unread."
    )
    unused = sorted(declared - set(silenced))
    assert not unused, (
        f"{template.id}: context_fields lists {unused}, which match no number in "
        "example_input. A declaration that names nothing cannot be checked."
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
    coefficients = _objective_coefficients(problem.objective.expression)
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
    # Brute force over all 2^15 host assignments agrees. The home-and-away
    # balance is what costs money: letting every pair send its cheaper
    # traveller, with no cap on how often a club hosts, would come to 3969.75,
    # so holding each club to two or three home games is worth 169.50.
    "tournament_scheduling": 4139.25,
    # Cheapest detection per euro is cost_per_sample / defect_rate: C and E at
    # 20, A at 25, B at 46.67, D at 80. Filling in that order to 0.8 x 87 =
    # 69.6 defects gives 600 + 300 + 250 + 560, then 260 samples of D at 0.8.
    "quality_control_sampling": 1918.0,
    # Brute force over all 8^4 discount combinations agrees: jacket and dress
    # at full price, shirt at 60% off, hat at 30% off, which shifts 165.8 of
    # the 276 units against a 60% floor of 165.6.
    "markdown_pricing": 5214.0,
    # The lathe has 11 hours booked, so nothing finishes sooner, but no
    # schedule reaches it: C-Lathe cannot end before hour 8 and C-Mill needs 3
    # more, and the lathe still has to fit B-Lathe, which waits on 4 hours of
    # mill. Forcing makespan <= 12 comes back INFEASIBLE; 13 is optimal.
    "job_shop_scheduling": 13.0,
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


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=[t.id for t in ALL_TEMPLATES])
def test_the_card_states_the_size_of_the_model_it_builds(template) -> None:
    """estimated_variables and estimated_constraints are served and indexed.

    The API returns both on every template, and the RAG index stores them, so a
    stale pair misdescribes the card to a user and to the assistant. The
    example input is fixed, so the counts are exact, not an estimate.
    """
    problem = _build(template)
    assert (template.estimated_variables, template.estimated_constraints) == (
        len(problem.variables),
        len(problem.constraints),
    ), (
        f"{template.id}: the card says {template.estimated_variables} variables and "
        f"{template.estimated_constraints} constraints; the model has "
        f"{len(problem.variables)} and {len(problem.constraints)}."
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
