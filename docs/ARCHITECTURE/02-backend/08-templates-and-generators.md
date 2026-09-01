# Templates and generators

A template is a card in the marketplace and a recipe for a model. The card is
YAML in `app/data/templates/*.yaml`; the recipe is a `generator_type` naming a
class in `app/domains/solver/services/generators/`, plus a `generator_params`
dict that configures it.

There are 102 templates across 34 YAML files, and 32 problem generators plus a
generic passthrough. The registry holds 36 names, because three classes answer
to two names each: `scheduling`/`employee_scheduling`, `routing`/`vehicle_routing`
and `blending`/`fertilizer`. 31 generators are reached by a template today; the
rest are reachable by name through the API.

## A template describes its input twice, and the third is derived

| Field | Who reads it | What breaks when it is wrong |
|---|---|---|
| `example_input` | the generator, in every backend test | nothing — this is the one that is exercised |
| `input_fields` | the studio, which renders it as a form | the form drops or blocks the card's own example |
| `input_schema` | the API docs and clients | **derived, so it cannot drift** |

`input_schema` used to be a third hand-written copy, and it drifted: the seeder
always stored the schema derived from `input_fields` while the template route
served the copy written in the YAML. They disagreed on 10 of 102 cards about
which fields are required, so `GET /solve/templates/{id}` called `max_risk` and
`discount_rate` optional while `GET /models/catalog/{id}/schema` and the studio
form called them required. `yaml_template_to_dict` now overwrites it with
`build_input_schema(tmpl)` on every path. The YAML block is still required by
`TemplateDefinition`, but nothing serves it.

**A field's `default` is live.** `buildEmptyValues` in `DynamicFormRenderer.tsx`
reads `field.default` for top-level scalars, the way `makeEmptyRow` has always
read it for row columns. It did not, so all 35 declared defaults were inert: 25
sat on required fields and made the form refuse to submit over a number the card
had already supplied, and the rest were never sent, so the generator's own
hardcoded default ran in place of the advertised one.

`tests/test_template_form_contract.py` holds them together. Its headline test
rebuilds the model from exactly what the studio form would submit and requires
it to be byte-identical to the model built from `example_input`. Both
`handleLoadExample` and `collectCleanValues` in `DynamicFormRenderer.tsx` walk
`inputFields` and not the example, so a key with no field behind it is dropped
between "Load example" and "Solve", and the model then answers a different
question.

The same applies one level down, inside an array. `updateRow` spreads the
existing row, so editing a loaded example keeps a column the form cannot see,
but `makeEmptyRow` builds a new row from the declared `items.properties` alone.
A row the user **adds** is therefore missing every undeclared column, so the
declared columns must equal the union of the keys the example rows carry.

A list of plain numbers must declare `items: {type: number}`. The renderer
reads `field.items?.type ?? "string"`, so an undeclared list gets text inputs:
editing a value turns 120 into `"120"`, and adding one appends an empty string.

## `context_fields`

Every number in `example_input` has to reach the model. `tests/test_template_model_quality.py`
proves it by changing each number, up and down, and rebuilding: if the model is
identical, that number was never read.

Some cards legitimately carry a number the model does not optimise over. A
zone's population on a card that must cover every zone whatever its size; a
stand's age, which explains why its timber is worth what it is while the model
reads the volume and the price; a vessel's crane count. Name those fields in
`context_fields` and the gate skips them:

```yaml
    # every community must be covered whatever its size, so population sets the
    #   stakes rather than the answer
    context_fields: [population]
```

Write the reason above it. The point of the list is that the exception is
reviewable instead of silent — an undeclared unread number is indistinguishable
from a generator that forgot to read it, and that is the bug this whole gate
exists for.

`context_fields` is not an escape hatch for a number the model *should* read.
If the card promises something, the model has to do it, or the card has to stop
promising it.

## `generator_params`

A generator serves several cards, and `generator_params` is how one card tells
it which shape it is in. These are the parameters in use.

### `assignment`

The widest contract. Workers on one side, tasks on the other, and rules for
what may pair with what and at what price.

| Param | Default | Meaning |
|---|---|---|
| `cost` | `[]` | Rules that price a worker-task pair. A `penalty` rule adds an `amount` when a named worker field is `unequal` to a named task field. |
| `require` | `[]` | Rules that forbid a pair outright: `equal: [worker_field, task_field]`, or `at_least: [worker_field, task_field]` when the worker must meet or beat the task's number. |
| `worker_rule` | `at_most_one` | How many tasks one worker may take. |
| `task_rule` | `exactly_one` | How many workers a task must get. |
| `capacity_field` | none | A worker field capping how much it can absorb. |
| `needs_field` | `needs` | The task field listing what it requires. |
| `type_field` | `type` | The field both sides use to name a class of thing. |
| `idle_cost_field` | none | A worker field priced when the worker is left unused. |
| `demand_field` | `demand` | The task field naming how much it needs. |
| `supply_field` | `supply` | The worker field naming how much it brings. |

### The rest

| Generator | Param | Meaning |
|---|---|---|
| `blending` | `mode: absolute` | Targets are absolute amounts rather than fractions of the mix. |
| `covering` | `mode` | `cover` (default) or the packing variant. |
| `covering` | `coverage_format: index_pairs` | A set names the elements it covers by index, not by name. |
| `knapsack` | `min_totals` | `{field: floor}` — the chosen items must total at least `floor` of `field`. |
| `network_flow` | `mode: max_flow` | Maximise throughput instead of minimising cost. |
| `network_flow` | `arc_limit` | An input key holding a ceiling on what the arcs may carry. |
| `period_selection` | `mode: assign` | Every item must get a period, rather than periods being optional. |
| `portfolio` | `return_field` | Which item field is the return (default `expected_return`). |
| `portfolio` | `return_mode` | `absolute` (default) or a rate applied to the price. |
| `portfolio` | `return_discount_field` | An item field that discounts its return. |
| `portfolio` | `risk_field` | Which item field is the risk (default `risk`). |
| `portfolio` | `risk_limit_field` | The input key holding the ceiling on weighted risk. |
| `portfolio` | `weight_field` | What the risk and the budget are weighted by. |
| `windowed_tasking` | `mode: serve_all` | Every job must run and the cost is waiting, instead of jobs being optional and the objective being collected priority. |

A field name in a param refers to a key in the card's own data, so renaming a
key in `example_input` means changing the param too. The model-quality gate
catches that: the renamed number stops reaching the model.

## The lessons the generators keep re-learning

**Sanitize both sides of a lookup.** Variable names go through
`sanitize_name()`, which lowercases and replaces punctuation, while the lookup
table keeps the case the card wrote. The same bug appeared in four generators —
assignment, facility_location, routing, and covering — and each time the lookup
missed, a default was used, and the model solved a different problem without
complaint.

**Raise instead of defaulting.** A silent default is what makes these bugs
invisible: cost 1, distance 100, capacity 1000, size 1, duration 1, demand 1.
Each produced a model that built, solved, and reported optimal. When a required
number is absent, say so and name the row.

**Names must be distinct after sanitizing.** Two rows called "IC-201" and
"IC 201" both become `ic_201`, and their variables become one variable doing two
jobs. Call `self.reject_name_collisions(sanitized, originals, label)` from
`BaseGenerator` on every entity list a generator turns into variable names.
Eleven generators do. Without it, four cards merged the two rows and still
reported optimal (`pick_route_optimization` went from 49 variables to 36 and
answered 77 where the truth is 100) and 75 died on a pydantic message that named
neither the field nor the two names that clashed.

**A guard that reads "did ANY row carry it" is not a guard.** Knapsack checked
`not any(...)`, so it only rejected an input where NO row had a value. The one
row a user forgot a column on still fell through to a default of 1.0.

**Read the shared helpers instead of writing a fourth copy.**
`BaseGenerator.first_number(row, keys)` returns the first key present or `None` —
returning `None` rather than a default is the point, because `or 0.0` at the call
site is what turned an unrecognised demand key into "buy nothing, optimal".
`safe_float` rejects NaN and infinity, and `TemplateEngine.render` now refuses
either anywhere in the input, naming the field: both are valid JSON literals and
survived all 65 bare `float()` casts.

**Size the model before building it.** `rail_timetabling`, `windowed_tasking`
and `scheduling` cap at 40,000 start variables, counted from the arithmetic
before any `Variable` is constructed. Checking after the loop meant an oversized
card paid the whole build first — 15.9 s for 39,604 variables, inside the
request handler, only to accept them.

**An objective all of whose coefficients are equal is only wrong when the
constraints pin the total.** "Minimize how many bins are opened" is a real
objective and nothing fixes that count. Three cards optimised a total their own
rows already fixed, so every plan tied and one was picked arbitrarily; each now
carries the per-row weight that separates one plan from another (an evaporation
loss and a tariff per irrigation slot, a curtailment cost per generator, a value
of water per period). `FLAT_OBJECTIVE_IS_CORRECT` holds the ones that are
legitimately flat, each with a written reason.

## The gates

- `tests/test_template_model_quality.py` — every number reaches the model, the
  objective can tell two answers apart, 24 optima are pinned to a hand
  derivation, and the stated model size is exact.
- `tests/test_template_form_contract.py` — the studio form submits the card's
  whole example.
- `tests/test_template_translations.py` — every card has text in all five
  locales, and `en.json` matches the YAML word for word.
- `tests/test_generator_params_are_read.py` — every key a card sets in
  `generator_params` is one its generator actually reads. The check parses the
  generator's source for the literal keys it takes off `params`, so it costs
  nothing at runtime. A free-form dict swallows a misspelling in silence:
  misspelling one key changed the model for 23 of 43 keys, including `mode`,
  where losing it reverts `serve_all` to `select` and the plan stops having to
  serve anything.
- `tests/contracts/test_fork_answers_once.py` — a fork gives one model whichever
  path asks for it. See [the fork rule](#a-fork-is-a-cache-until-somebody-edits-it).

See [TESTING.md](../../TESTING.md) for what each one caught.

## A fork is a cache until somebody edits it

A project seeded from a marketplace card stores the model rendered once, at fork
time, while `/preview` and `/execute` re-render from the source card. Those two
answers stop agreeing the moment the card is corrected — and 17 cards carry
`generator_params`, so every project forked from one of them before 3.8.0 was in
that state. The studio reads the stored draft and posts it to `/solve/async`, so
the same project id showed one model and solved another, with no warning on
either side.

`PUT /projects/{id}/draft` has never refused an edit to a generator-backed
project, and the solve path re-rendered regardless, so a model somebody wrote by
hand in the studio was discarded the moment they solved it.

`ModelProject.seed_content_hash` records what the draft looked like when the
project was seeded. Three states, one answer each:

| State | Meaning | What happens |
|---|---|---|
| `seed_content_hash == draft_content_hash` | nobody edited it | the draft is a cache of the card; rendering refreshes it |
| they differ | the user wrote that model | their model wins on every path and is never overwritten |
| `seed_content_hash IS NULL` | seeded before the column existed | reads as edited, so the draft is left exactly as it is |

The NULL case is deliberate. We cannot tell whether somebody authored that
model, and keeping a model the user may have written beats overwriting it to
match a card. Migration `20260901_project_seed_hash` therefore ships **no
backfill**.

Use `model_project_service.draft_is_untouched(project)` to ask, and
`refresh_seeded_draft(db, project, model_json)` to refresh — it is a no-op on an
edited draft.
