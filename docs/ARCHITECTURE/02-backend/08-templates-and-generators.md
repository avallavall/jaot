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

## A template describes its input three times

Only one of the three is executed, which is why they drift.

| Field | Who reads it | What breaks when it is wrong |
|---|---|---|
| `example_input` | the generator, in every backend test | nothing — this is the one that is exercised |
| `input_fields` | the studio, which renders it as a form | the form drops or blocks the card's own example |
| `input_schema` | the API docs and clients | a client sends what the docs say and the model rejects it |

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

## Two lessons the generators keep re-learning

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
jobs. `rail_timetabling` and `round_robin` reject that; a new generator should
too.

## The gates

- `tests/test_template_model_quality.py` — every number reaches the model, the
  objective can tell two answers apart, 24 optima are pinned to a hand
  derivation, and the stated model size is exact.
- `tests/test_template_form_contract.py` — the studio form submits the card's
  whole example.
- `tests/test_template_translations.py` — every card has text in all five
  locales, and `en.json` matches the YAML word for word.

See [TESTING.md](../../TESTING.md) for what each one caught.
