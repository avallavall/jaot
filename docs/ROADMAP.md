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

## Next

- **A home for people who publish** — the marketplace can be published to, but an
  author has nowhere to see what happens next: how their listings are being found and
  adopted, and how to ask for the verified badge rather than wait to be granted one.
  The measurements are already taken; what is missing is the place to read them.

## Later / Exploring

- **Data → model drafting** — upload a dataset (CSV/XLSX) and get a draft optimization
  model to edit, instead of starting from a blank canvas.
- **A native solver** — we are researching what a solver built into the platform itself
  could look like. Early exploration; no design commitments yet.

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
