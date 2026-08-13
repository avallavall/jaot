# Roadmap

This is a **directional** roadmap — themes we are working on or considering, in rough
priority order. No dates, no commitments: items can move, change shape, or be dropped
as we learn. The best way to influence it is to
[open or upvote an issue](https://github.com/avallavall/jaot/issues).

## Now

**Foundations before features.** The analysis layer is where we wanted it: exact
post-solve facts, per-family KPIs, what-if answers by real re-solves, and an interface
that adapts to what your chosen solver can actually deliver. Before building the next
large thing on top, we are going through the backend itself so that what comes next
lands on solid ground rather than on top of it.

Landed so far: request handling no longer blocks the server on database work or on file
parsing, foreign keys are indexed, the security gates are back in CI, and the capacity
limits inherited from the hosted-product era are gone — model size is now bounded by
your hardware, not by a constant in our schema. The dependency direction between layers
is settled and a lint contract keeps it that way, and every endpoint that used to answer
with an undeclared object now publishes its response schema, so the API describes itself
and clients stop hand-writing those types.

A fleet-sized pickup-and-delivery model also went from "does not compile" to solving
exactly in seconds — and the lesson was not about the solver. The formulation had tied
three arcs of one journey together with equalities, so what looked like a routing problem
with millions of variables was an assignment problem with a few hundred thousand. Same
optimum, verified across instances. Worth saying out loud because it generalises: on this
kind of model, how you write it decides more than which solver runs it.

Publishing to the marketplace now has a home to come back to: authors can see what
they published, take a listing down and put it back without losing its history, read
the reviews people left, and ask for the verified badge instead of waiting to be
granted one. The numbers it shows are deliberately quiet when there is little to
report — a first-week author gets a sentence saying so, not a chart of one colour.

The solve analytics screen now follows the same rule. A success rate over a handful of
runs shows as the plain ratio instead of a one-decimal percentage, a distribution with a
single status reads as a sentence instead of a donut of one colour, and one or two days
of activity say so instead of posing as a trend.

The front page was rebuilt on the same principle: show the product working instead of
describing it. It opens on a real solver run rather than a screenshot, and the sections
below it follow one industrial instance the whole way down — where the money in a
quarterly plan actually goes, why an over-committed version of it has no answer at all,
and the model source that compiles to both. The figures are generated from the solver
and from the template catalogue itself, so the page cannot drift away from what JAOT
reports after a solve.

## Next

Nothing queued right now — the last item here (the solve analytics screen reading
well before the data arrives) shipped; see Now.

## Later / Exploring

- **A solver of our own** — we are researching what an in-house solver could look like. It
  lives in its own open-source repository, [jaos](https://github.com/avallavall/jaos),
  published alongside JAOT rather than inside it: a solver has no business depending on the
  platform that happens to use it, and keeping it standalone means anyone can use it without
  JAOT at all. The platform will then adopt it the way it adopts any other solver — through
  the adapter contract, same as SCIP and HiGHS. Early exploration; no design commitments yet.

- **Optimization for Odoo** — a module that brings real optimization to Odoo, where the
  decisions worth optimizing already live (purchasing, inventory, production, delivery
  routes, workforce planning are the obvious candidates). Like the solver, it has its own
  open-source repository, [jaom](https://github.com/avallavall/jaom), rather than being part
  of this one. Nothing is designed yet — including the first question, which is whether it
  talks to a JAOT instance over the public API or stands on its own.

## Not planned (for now)

Things we have considered and deliberately set aside — so you don't have to guess:

- **Multi-provider LLM support** (OpenAI-compatible endpoints, local models, etc.).
  The AI assistant currently targets the Anthropic API, including bring-your-own-key
  per organization. A full provider abstraction is designed but on hold.
- **Live data connectors in triggers** (databases, spreadsheets, HTTP feeds re-feeding
  models automatically). The complexity outweighs the value for now; importing data as
  datasets stays the supported path.
- **A live JModel view of canvas edits.** Previously listed under Next. "Derive draft"
  already turns a canvas or imported model into a JModel source on demand, and it only
  offers a draft that provably round-trips — recomputing that on every keystroke buys
  little for a view you read once.

---

*Shipped work is tracked in the [Changelog](CHANGELOG.md).*
