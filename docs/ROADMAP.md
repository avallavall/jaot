# Roadmap

This is a **directional** roadmap — themes we are working on or considering, in rough
priority order. No dates, no commitments: items can move, change shape, or be dropped
as we learn. The best way to influence it is to
[open or upvote an issue](https://github.com/avallavall/jaot/issues).

## Now

**Analysis you can act on.** The post-solve analysis is exact, aggregates per-family KPIs
(binding share, slack distribution, utilization, headroom ranking, objective contributions
by variable family), and now answers what-if questions by really re-solving: RHS ranging on
the top binding constraints (what one more unit of a capacity is actually worth) and
decision regret (what it costs to overrule a decision), on demand, under a time budget,
cached per execution. The focus now moves to how that analysis is *presented* — the items
below.

## Next

- **Map visualization for routing problems** — plot routes/assignments for
  pickup-and-delivery-class models instead of reading them as tables.
- **Large-solution rendering** — virtualized views so a 20k-variable solution stays
  smooth in the browser.
- **JModel editing refinements** — a live read-only JModel view of canvas edits with
  an explicit "apply" step.
- **Solver-aware analysis panel** — the analysis UI adapts to what the active solver
  actually provides instead of showing empty sections.

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

---

*Shipped work is tracked in the [Changelog](CHANGELOG.md).*
