# Roadmap

This is a **directional** roadmap — themes we are working on or considering, in rough
priority order. No dates, no commitments: items can move, change shape, or be dropped
as we learn. The best way to influence it is to
[open or upvote an issue](https://github.com/avallavall/jaot/issues).

## Now

**Deeper sensitivity analysis.** The post-solve analysis is exact and now aggregates
per-family KPIs (binding share, slack distribution, utilization, headroom ranking,
objective contributions by variable family). The next layer:

- **True MIP sensitivity, on demand** — real re-solve-based analysis: RHS ranging on
  the top binding constraints (how much does the objective actually move if a capacity
  changes?) and decision regret (what does it cost to flip a key decision?). Runs
  asynchronously with a time budget, cached per execution.

## Next

- **Map visualization for routing problems** — plot routes/assignments for
  pickup-and-delivery-class models instead of reading them as tables.
- **Large-solution rendering** — virtualized views so a 20k-variable solution stays
  smooth in the browser.
- **JModel editing refinements** — derive support for alphanumeric composite indices
  (e.g. `xsc_s1_c1_k1`), a live read-only JModel view of canvas edits with an explicit
  "apply" step, and safer edit flows after a reload.
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
