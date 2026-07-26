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
your hardware, not by a constant in our schema.

## Next

- **Finishing the architecture pass** — the remaining items are the dependency
  direction between layers (and a lint contract to keep it that way) and giving the
  endpoints that still return untyped payloads a real response schema, so the API
  describes itself and clients stop hand-writing those types.
- **Scaling the routing models** — a fleet-sized pickup-and-delivery problem is a
  realistic ask in transport, and we are working through what the platform needs to
  express and solve one honestly.

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
