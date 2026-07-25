# Changelog

All notable changes to JAOT are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) — Semantic Versioning.

> **Project history.** JAOT grew out of ~7.5 months of continuous development
> (first commit 2025-11-06, ~3,360 commits) before its public release —
> originally built as **Optera**, rebranded to JAOT on 2025-11-13. The
> entries below trace that history — from the early plugin-based prototype, to
> the universal SCIP rewrite, the marketplace, billing, the modular-monolith
> refactor, RAG, and the solver-agnostic, AI-assisted platform published here.
> Dates reflect when each change actually landed on the main line of
> development.

---

## [Unreleased]

### Added

- **The assistant answers in your language.** Every generated text — chat replies, the
  solution, infeasibility and what-if explanations, and the assumptions written alongside a
  generated JModel — came back in English no matter which of the five languages you were
  reading the app in. The locale you are browsing in now travels with each request and the
  model is told to answer in it. Identifiers are explicitly excluded: variable, constraint
  and set names, expressions, JModel source and JSON keys are quoted exactly as they are, so
  the explanation still matches what is on screen. An unknown locale falls back to English
  rather than to a language the product does not ship.

- **You can ask for the advanced model.** The platform had an advanced tier configured
  (`LLM_ADVANCED_MODEL`) that the interface never used: every chat message and every
  explanation went out on the default model, and the only way to reach the other one was
  the API. There is now an **Advanced model** toggle in both chats and in the solution,
  infeasibility and what-if explanations. Off by default and remembered per user — the
  advanced tier costs several times more per call, so it is always asked for, never
  inherited. The what-if explanation caches per tier: asking for the other one re-reads the
  scenarios, asking again for the same one stays free.

- **What-if analysis by real re-solves** (Sensitivity level 2). The analysis panel can
  now answer the question the exact analysis structurally cannot: *what would one more
  unit actually buy me?* On demand, the platform perturbs the solved model and solves it
  again — **RHS ranging** on the top binding constraints (loosen and tighten each by δ,
  measure the real objective change, read as a tornado chart normalised per unit) and
  **decision regret** (force a binary decision to its opposite value and re-solve, pricing
  what it costs to overrule the model; an impossible overrule comes back as infeasible,
  which is itself an answer). Unlike LP-relaxation shadow prices — duals of an easier
  problem, near-uniform under degeneracy — every number here is measured on the real MIP.
  Runs on the solver queue, never in the request, bounded by both a per-scenario time
  limit and a batch budget (defaults: 20 re-solves, 8 ranged constraints, 4 decisions,
  `min(2× the original solve, 30s)` per scenario, 5 minutes per batch — all configurable
  in the admin panel). Relaxations are solved before tightenings, so a batch cut short by
  the budget still spent it on the informative half; scenarios that never ran come back
  labelled and the result is flagged partial rather than padded, and a scenario stopped at
  its time limit is reported as a bound, not as an exact value. Requesting the batch twice
  joins the one in flight instead of starting a second, and the result is cached on the
  execution. The budget bounds the ANALYSIS only — solve time limits are untouched.

- **The grouped solution view is windowed, not truncated.** It used to render the first
  500 chips behind a "show all" that then mounted everything and froze the page — so a large
  solution was either incomplete or unusable. Now only the rows near the viewport are
  mounted: on a real 7,200-variable solution the view switches in ~180 ms and holds ~720
  chips in the DOM instead of 7,200, with the rest reachable by scrolling and each row
  reporting its true height so wrapped chips never drift the scrollbar. The family → index
  structure is unchanged, and a normal-sized solution still renders straight into the page
  with no nested scroller.

- **Agents can analyse, not just solve (MCP 26 → 30 tools).** The MCP surface exposed
  results but no analysis: an agent could solve a model and read the solution, yet could
  not ask what was saturated, why a model was infeasible, or what one more unit of a limit
  is worth. Four existing endpoints join the curated tool list —
  `get_execution_exact_analysis`, `analyze_infeasibility`, and the pair
  `start_execution_scenario_analysis` / `get_execution_scenario_analysis` (start, then poll,
  the same shape an async solve already uses; a retry joins the batch in flight rather than
  buying a second one). The plain-language `explain-*` endpoints stay OUT by design and a
  contract test keeps them out: an MCP client is already a language model, so spending the
  platform's AI budget to narrate figures it can read itself would bill the same sentence
  twice.

- **"Explain this to me" on the what-if analysis.** The assistant reads the measured
  scenarios back in plain business language — what actually limits you, what is not worth
  buying, what deciding otherwise would cost — for users who do not read tornado charts for
  a living. Grounded by construction: it is handed the solved scenarios and forbidden to
  invent one that was not run or to extrapolate a per-unit figure past the change actually
  tested, and each row's status (exact / bound / infeasible / never ran) is part of what it
  must respect. Opt-in like the batch itself, and cached on the execution so a reload never
  costs another call. Same guardrails as the rest of the assistant: bring-your-own-key
  first, monthly budget pause, per-org rate limit.

- **"Derive draft" recovers composite alphanumeric indices** (`xsc_s1_c1_k1` —
  MDPDP-style supplier/customer/vehicle labels). The flat-name parse now accepts
  letters-then-digits index segments alongside numeric ones, taking the maximal
  index suffix at segment granularity, so a flat/imported model named this way
  de-grounds into an indexed family over alphanumeric sets — and the same recovery
  feeds the grouped solution view and the family-level analysis KPIs. Purely
  alphabetic tails are still never guessed (`total_cost` stays a scalar), and the
  round-trip honesty gate keeps guarding every draft.

- **Family-level KPIs in the post-solve analysis** (Sensitivity level 1). The exact
  analysis now aggregates by constraint family — share of binding rows, slack
  min/mean/max, utilization mean/max, ranked so the saturated families lead and the
  headroom reads at the bottom — and by variable family (total objective contribution),
  so a 10,000-row model reads like a ten-line summary. Computed over *all* analysed
  rows, not the capped display lists. JModel-compiled problems carry the constraint
  family authoritatively (the declared constraint name); flat/imported problems recover
  it from conventional `name_1_2` naming, with the same never-second-guess contract the
  variable grouping already uses.
- **Public roadmap** — `docs/ROADMAP.md` (now / next / later / not-planned, directional,
  no dates), linked from the README. The frozen JModel grammar spec also now ships with
  the repo as `docs/JMODEL_GRAMMAR.md`.

### Changed

- **The AI assistant now runs on Claude Sonnet 5 / Opus 5** (from Sonnet 4.6 / Opus 4.6),
  at the same list price per token. Reasoning moved from manual extended thinking to
  **adaptive thinking** with an `effort` hint, because the fixed-token-budget form
  (`budget_tokens`) is rejected outright by every model of this generation. The advanced
  path thinks adaptively at the new `LLM_THINKING_EFFORT` setting (`low`…`max`, default
  `high`); an unrecognised value degrades to `high` instead of failing the request.
  The pricing map used by the monthly EUR guardrail gained explicit Sonnet 5, Opus 5 and
  Fable 5 entries — without them these models would have priced at the generic fallback,
  which under-counts Fable 5 by roughly half.
  A data-only migration moves existing installs, but only where the setting still holds
  the previous default, so a deliberately pinned model is left alone.
- **Non-reasoning requests now disable thinking explicitly** rather than by omission.
  From Sonnet 5 onwards an absent `thinking` parameter means *think anyway*, and since
  `max_tokens` caps reasoning and answer together, the quick paths (standard chat
  formulation, chunked fallback, JModel generation) would have spent their output budget
  on reasoning and truncated the JSON.

### Deprecated

- **`LLM_THINKING_BUDGET_TOKENS`** — no longer read by any code path; superseded by
  `LLM_THINKING_EFFORT`. The setting row stays for one release before removal.

### Fixed

- **Next.js patched to 16.2.11**, closing seven advisories present in 16.2.9 — SSRF via
  rewrites and via Server Actions on custom servers, a middleware/proxy bypass in App
  Router, unauthenticated disclosure of internal Server Function endpoints, plus DoS and
  cache-confusion issues.

- **A page reload no longer disarms the JModel stale lock** (the drift-on-reload
  footgun). Reloading — or restoring a version — rehydrates the JModel source with
  its sync state unknowable, but the editor used to come back editable: one
  keystroke could recompile an old source and silently replace a model last edited
  on the canvas. The rehydrated source now comes back **read-only with the stale
  notice** until the explicit recompile proves it matches (unlocking instantly in
  the common in-sync case) or deliberately replaces the model. Picking a dataset
  no longer auto-applies an unverified source either.
- **"Derive draft" recovers two constraint shapes it used to decline** (the 2026-07-21
  torture-test findings): (H1) two same-shape scalar constraints over one family —
  a multi-knapsack's `Σw1·x ≤ 50` / `Σw2·x ≤ 40` — no longer fuse into one
  undeclarable group; each emits as its own constraint with its own coefficient
  table. (H2) a per-constraint constant coefficient — a CFLP's `cap_i · y_i` —
  no longer fragments the constraint family into singleton groups; the template
  key now classes coefficients as unit/non-unit only, the constant-vs-param choice
  is resolved at emission, and a merged group that cannot emit falls back to the
  per-value partition. The round-trip honesty gate is unchanged and still guards
  every draft.

### Changed

- **Derived drafts read like a person wrote them** (the torture test's cosmetic
  findings): two index positions whose members happen to coincide are no longer
  fused into one set — set identity now needs structural evidence (a shared free
  index linking the slots in some constraint), so jobs vs periods with the same
  labels derive as `x{S1, S2}`, not a claimed square over one set. And each set
  keeps one canonical index letter across the whole source (`S1→i`, `S2→j`, …) —
  a family ranging only over the second set reads `sum{j in S2} …` in the
  objective and under its `∀` alike, instead of a fresh `i` per line.

- **The Sensitivity tab no longer renders a wall of identical bars** (owner report,
  the 100×100 assignment): in a MIP the LP relaxation is often (near-)degenerate —
  most constraints share the same shadow price — so a per-constraint bar chart
  carries zero information. When duplication dominates, the tab now collapses to
  one row per DISTINCT shadow-price value ("150 constraints (150 binding) · 1.0000")
  plus a degeneracy note pointing to the exact analysis; a genuinely diverse chart
  stays, capped to the top 30 bars, and the detail tables cap at 50 rows with an
  honest truncation note.

- **"Derive draft" now respects JModel's model/data separation** (owner report, the
  100×100 TFM model): deriving a persisted project's flat model produces the PURE
  general formulation — declaration-only sets and params (`set S1;` /
  `param c_a{S1, S1};`), the objective, and the ∀-quantified constraint families —
  while every set member and param value lands in an automatically created
  **"Derived data" project dataset**, selected so the draft compiles immediately.
  Previously the draft inlined all values (`param c_a{S1, S1} := …` with 22,500
  entries for a 100×100 model — an unusable wall of numbers). The honesty gate now
  verifies `compile(source, dataset)` equivalence. Unsaved projects (nowhere to
  store a dataset yet) keep the self-contained inline form, as does the scalar
  fallback.

## [3.1.0] — 2026-07-20

### Fixed

- **Technical-audit hardening of the v3.1 surface** (a code audit of everything
  since v3.0.0):
  - **Marketplace/template executions now carry the grouped-solution structure
    (A1)** — `/solve` and `/solve/async` annotated `family`/`index_tuple` at
    enqueue, but executions launched via `/models/{id}/execute` never did, so
    their post-solve page silently fell back to the flat variable wall. The
    worker now annotates the problem it builds, covering every entry point.
  - **The exact-analysis endpoint (A3) no longer runs on the event loop** — it
    re-parses up to thousands of constraints (CPU-bound) and was `async def`,
    stalling every in-flight request for the duration; it is now a sync `def`
    (threadpool), contract-tested to stay that way.
  - **"Generate with AI" (B3) robustness** — an unexpected fence label
    (```` ```python ````) no longer leaks into the compiled source; a (rare)
    text-less model reply no longer aborts the retry loop with a transport
    error; and picking more files than the 4-attachment limit now says so
    instead of silently dropping the extras.
  - **"Derive draft" (B2) declines gracefully on exotic models** — a family with
    more index positions than the reconstruction's letter pool (14) used to leak
    an internal error; it now declines honestly like every other unrecoverable
    shape.
  - **Large-solve explanation sampling keeps the top decisions** — the bounded
    prompt now samples the largest non-zero values by magnitude (as documented)
    instead of the first 200 in insertion order, so a dominant decision can no
    longer be dropped from the explanation.
  - **A3 objective contributions merge like terms** — `2*x + 3*x` reads as one
    `x` row, not two colliding rows.
  - **The grouped solution view stays responsive on huge solutions** — it now
    renders a bounded prefix (500 values) with a "show all" opt-in instead of
    mounting tens of thousands of chips (a 20k-variable solution with the
    non-zero filter off froze the page).
  - **One AI-cost ledger per (org, user), guaranteed** — the hidden `sys:`
    bookkeeping conversation's get-or-create could race under two concurrent
    first generations and produce duplicate ledgers (benign for the budget sum,
    but unbounded). A partial unique index now enforces the invariant (additive
    migration, with a dedupe of any existing duplicates) and the loser of the
    race adopts the winner's row.
  - **MCP analytics survive a fastapi-mcp upgrade** — the tool-call emitter
    wraps a private dispatch method; a library switching that call to
    positional arguments now degrades to "no analytics" instead of breaking
    every MCP tool call with a TypeError.

- **The "Solving…" pill no longer lingers after a solve is cancelled from another
  tab/device** — the ambient solving indicator shows only while the session is
  `running`, and the completion poll moved the session off `running` for `completed`
  and `failed` — but not for a Celery-revoked task (`GET /solve/async/{id}` returns
  `"revoked"`). A cancel/revoke from another tab, a worker restart, or any unexpected
  terminal status left the poll spinning and the pill stuck (the idle reconcile that
  would clear it only runs while the session is idle). The poll now resolves EVERY
  non-in-flight status: revoke/cancel → cancelled, anything else terminal → failed.

- **The JSON model editor no longer crashes the studio page (and silently drops a
  just-added variable)** — the server `/solve/validate` response never included a
  `warnings` array, yet the editor lens read `validation.warnings.length` on every
  validated edit, so ~500ms after any change the whole workspace fell to the error
  boundary. Because the crash unmounted the workspace, its debounced autosave was
  aborted — a variable added right before (e.g. after deriving a JModel) was never
  persisted. This was the "derived a JModel, added another variable, it wasn't saved"
  report. The endpoint now honours its declared `ValidationResult` contract (always
  returns `errors` and `warnings` arrays), and the editor coalesces a missing array
  to empty so a malformed response can never crash the page. Regression-guarded by a
  new E2E that waits for the validation to render (existing editor specs navigated
  away first) plus a backend contract test.

- **Viewing the canvas no longer locks the JModel source read-only** — after the
  structured-solution work tagged each variable with its index structure
  (`family`/`index_tuple`), the canvas ↔ model bridge stopped recognising an
  untouched canvas as unchanged (those fields can't be drawn on the canvas), so
  merely opening the Build/canvas view of a DSL-authored model flagged the source as
  "changed elsewhere" and locked it read-only. The bridge now preserves that
  structure across a canvas reprojection, so viewing the canvas is a no-op.

- **The JModel lens explains why solve is blocked after deselecting a dataset** — a
  declaration-only source with its dataset removed correctly blocks solve, but the
  inline compile-error box had stopped appearing (it keyed off the lens' own compile,
  which no longer runs on a dataset change), leaving the controls greyed out with no
  reason. The box now reflects the canonical block state and names the cause.

- **The AI solution explainer no longer 400s on large solves** — explaining a
  SOLUTION embedded the full formulation, the full variable→value map, the full
  variable list and full sensitivity as JSON, so a 10k-variable solve (150×150)
  produced an 11.6M-token prompt and the LLM API rejected it (`prompt is too long:
  … > 1000000 maximum`). Each block is now bounded like the model explainer already
  was: the formulation is sampled to a representative head and the solution is
  reduced to its decisions — the top non-zero variable values — with the objective
  kept exact. A small solve is still embedded in full.

### Changed

- **"Solve all" (Scenarios) now shows why it is busy** — running a JModel against a
  dataset compiles the model server-side first, which for a large model (e.g. a
  200×239 MDPDP scenario) genuinely takes tens of seconds; during that the button was
  disabled with no explanation and read as stuck. It now shows a spinner + "Compiling
  (n/N)" progress while the batch launches, and carries a disabled-reason tooltip in
  every state (compiling / no dataset selected / no JModel source).

- **"Derive draft" (B2) now recovers multi-family constraints and small models** —
  a constraint that mixes variable families with a shared free index (the real TFM
  scenarios: `sum_i a[i,j] + z[j] == 1  ∀ j`) is now recovered as one ∀-quantified
  family, aligning the fixed indices that co-vary across the flat constraints; a real
  150×150 model (22.6k variables, 3 constraint families) de-grounds to a compact
  JModel in ~3s. Constraint families are also split by coefficient character (a unit
  `sum_j a[i,j] == 1` vs a weighted `sum_j d[i,j]*a[i,j] <= M`). Separately, a small
  model with no indexed families (a two-variable canvas model, a 15-item assortment)
  de-grounds to a plain scalar JModel instead of declining, and binary variables
  round-trip whether or not the flat model stated their `[0,1]` bounds.

### Added

- **Public documentation for the v3.1 analysis workbench** — a new
  [Analyzing Results](https://jaot.io/docs/studio/analyzing-results) docs page
  (the structured solution, the honest solve summary, the exact analysis, and
  their API); the JModel DSL page now documents the mathematical notation view,
  "Derive draft", "Generate with AI", and the `/dsl/*` endpoints;
  "Understanding Your Solution" reflects the new three-layer analysis order;
  the executions API reference documents `GET …/exact-analysis`; `llms.txt`
  links the new surfaces; and the home page's "Understand your solution"
  section now shows the real thing — fresh light/dark screenshots of the
  analysis page and copy describing the exact, solution-based analysis (the
  orphaned convergence-chart component was removed).

- **Generate a JModel with AI, from a description or a screenshot (v3.1 B3)** — the
  JModel lens has a "Generate with AI" button that turns a plain-language description
  and/or attached screenshots/PDFs of a formulation into a working JModel source. It
  is built on JModel's determinism: the model proposes a source and the compiler is
  the oracle, so the new `POST /dsl/generate` runs a generate→compile→feed-the-error→
  retry loop and returns a source only when it VERIFIABLY compiles — a rare
  non-compiling best-effort draft is still loaded (the editor highlights its error),
  never passed off as valid. Attachments ride to Claude as native vision blocks
  (images and PDFs read directly — no OCR), so a photo of a thesis formulation becomes
  editable JModel. The draft lands in the editor exactly like a paste, and can be
  refined further. Same guardrails as the chat assistant: bring-your-own-key first,
  the monthly AI-budget pause, LLM rate limiting, and a moderation pre-check; the
  spend of platform-key runs is booked so it counts toward the monthly budget. Gated
  behind `JAOT_DSL`.

- **Derive a JModel draft from a flat model (v3.1 B2, phase 1)** — a model built on
  the canvas or imported (MPS/LP/CIP) has no JModel source, so the JModel lens now
  offers "Derive draft": it reconstructs a compact indexed JModel from the flat
  problem — variable families over sets, `sum` objectives with coefficient params,
  and ∀-quantified constraint families — so the model can be read, edited and shown
  as math (B1) in its compact form instead of as a wall of scalar rows. The
  reconstruction is heuristic, so it is **honest by construction**: the new
  parse-only `POST /dsl/deground` returns a draft only when it VERIFIABLY round-trips
  (recompiles to a problem equivalent to the input) and declines with a clear message
  otherwise, never showing a draft that misrepresents the model. Recovers coefficient
  and rhs params, per-element (`x[i] ≤ 1 ∀ i`) and summed constraint families, and
  handles negative/fractional coefficients; a model with no indexed structure (a
  purely scalar model) is declined rather than dumped verbatim.

- **JModel split-pane: the model as mathematical notation (v3.1 B1)** — the JModel
  editor now renders the source as symbolic math (KaTeX) in a live right-hand pane.
  A deterministic LaTeX pretty-printer walks the compiler AST *before* grounding, so
  the indexed objective, the ∀-quantified constraint families and the variable
  domains stay symbolic (`min Σ_{i∈I} wᵢ·xᵢ`, `Σ_{w∈W} assign_{w,t} = 1  ∀ t∈T`)
  instead of flattening into thousands of scalar rows. It is served by a new
  parse-only `POST /dsl/latex` (gated behind `JAOT_DSL`), so it also renders
  declaration-only sources where a full compile would error, and the pane keeps the
  last valid render on screen while an in-progress edit does not yet parse. No AI:
  the rendering is a pure function of the parsed model. Greek-named symbols render as
  their letters (`alpha → α`) and the pane can be collapsed back to a plain editor.

- **Structured solution view — variables regain their index structure (v3.1 A1)** —
  a binary assignment/routing solution used to render as a wall of identical
  `assign_v3_o107 = 1` rows because the flat solver output had thrown away the
  family + index structure the model knew. The backend now recovers it once,
  server-side: the JModel compiler stamps each grounded variable with its
  `family` + `index_tuple` authoritatively, flat/imported models get a
  conservative best-effort parse, and every solver adapter carries it onto the
  result — so the persisted `result_data`, the MCP tools and the grounded
  `explain_solution` prompt all see `assign[v3, o107]` instead of a mangled
  string. The execution-detail page now leads with a family → first-index
  grouping ("assign · v3 → o107, o12, o44") answering "what did the model
  decide?", with a toggle back to the full flat table (and constraint
  sensitivity) and a graceful fallback to the flat table when a solution has no
  recoverable structure.

### Added

- **Exact, solution-based analysis leads the post-solve view (v3.1 A3)** — a new
  Analysis section on the execution-detail page leads with facts that are EXACT
  for the integer solution and solver-agnostic: which constraints are binding
  (slack = 0), each constraint's slack/utilization (b_i − a_i·x*), and which
  objective terms drive the value (c_j·x*_j). All are computed on demand from x*
  + the stored problem via a new `GET /models/executions/{id}/exact-analysis`
  endpoint (off the solve path — it re-parses constraints, so it is bounded and
  never slows a solve). The LP-relaxation shadow prices — which for a MILP are
  duals of a different, easier problem and near-uniform under degeneracy — are
  demoted into a collapsed "approximate (LP relaxation)" section with identical
  values deduped ("47 constraints · shadow price 1.0"), so they no longer read
  as the primary artifact a decision is made from.

### Changed

- **The studio results drawer links out instead of cramming (v3.1 A5)** — the
  post-solve drawer in the studio was a 24rem sheet stuffed with the whole
  variable table and the sensitivity analysis. It now shows a lightweight
  summary — status, objective, solve time/gap, a variable count — and a "View
  full results" button into the full execution-detail page (which already has
  the grouped solution, the honest summary and sensitivity). The execution id
  needed for the deep link was already in the async enqueue response; it is now
  carried on the solve session. The builder and template drawers, which have no
  execution page, keep their full inline view unchanged.

- **The variable-values chart collapses identical bars to an aggregate (v3.1 A4)** —
  a binary assignment/routing solution rendered as dozens of bars all at 1.0:
  identical length, zero information. When every non-zero variable shares the
  same magnitude the chart now shows an aggregate ("N variables = 1 · M at zero")
  with a "show chart anyway" escape hatch, and keeps the real bar chart whenever
  the magnitudes vary (continuous / LP models, where bar length carries meaning).

- **Honest post-solve summary replaces the convergence chart (v3.1 A2)** — the
  live gap-convergence chart was noise for essentially every real model: SCIP
  finds a near-optimal incumbent almost immediately and then spends the run
  *proving* optimality, so the per-incumbent stream is ~2 points — a flat line
  even when the model branched 1,936 nodes. The execution-detail page now shows
  a truthful fact-card — "proven optimal at the root node", "optimal after N
  nodes", or "time limit — gap X%" — plus the final metrics (objective, gap,
  nodes, iterations, time), and the studio live panel keeps its streaming
  numbers without the flat chart. Branch-and-bound node/iteration counts are now
  persisted with the result so the summary can be specific. (A real
  dual-bound-vs-time chart is deferred until the solver streams the dual bound,
  not just incumbents.)

### Fixed

- **MCP usage analytics restored (v3.1 C1)** — the `MCP_TOOL_CALL` event lost its
  only emitter in the async-only solve rewrite, pinning the MCP dashboard at zero.
  Every tool call is now counted at fastapi-mcp's single dispatch choke point and
  attributed to the caller resolved from the forwarded Bearer, so all 26 tools are
  covered in one place (best-effort, off the tool's critical path).
- **Startup settings self-heal is now race-safe (v3.1 C3)** — booting several API
  workers at once made the seed's check-then-insert fail 3-of-4 workers on the
  `platform_settings` primary key. It now inserts with `ON CONFLICT DO NOTHING`, so
  a concurrent (or repeated) seed is a harmless no-op instead of a logged crash.
- **The ambient "solving…" pill no longer shows a future time (v3.1 A6)** — a server
  clock slightly ahead of the client's snapshot rendered "solving · in 2 seconds".
  The start is clamped to now (a running solve is always in the past) and the pill
  ticks every 15s so sub-minute solves stay fresh.

### Changed

- **Switching a dataset in the JModel lens compiles once (v3.1 C2)** — the panel and
  the provider-level recompile both fired on a dataset change, double-compiling the
  source. The panel now compiles directly only in the drifted-source window the
  provider hook deliberately skips; the normal case is handled once by the hook.

## [3.0.0] — 2026-07-17

**The "Model, Analyze & Solve" release** — the repo's first tagged version. The model
becomes the platform's protagonist: one versioned **ModelProject** workspace (canvas,
AI assistant, JSON editor and JModel DSL as lenses over a single canonical model),
git-style commits with health/stats, datasets & scenarios, live async solving, a
fork-first collaborative marketplace fused into the same entity (publish = list a
version; adopt = fork into your studio), grounded AI explainers, and a 26-tool MCP
surface for agents. Money/credits are fully retired (ADR-008) — fair use is rate
limits + solve caps. ~160 commits over the previous main.


### Added

- **Docs + tooltips sweep for the fused platform (2026-07-17)** — the in-app documentation was rebuilt around the post-fusion reality (fork-first marketplace, project-native API, async-only solving, 26 MCP tools) and grew eight new pages: Visual Canvas, JSON Editor, JModel DSL, Versioning, Datasets & Scenarios, Importing & Exporting Files, Favorites & Reviews, and Authors. In-app "?" help tooltips now cover the studio flow — problem class, health score, matrix density/nonzeros, commits, datasets, scenarios, solver auto-routing and the live convergence chart — plus a "reduced cost" glossary term in the sensitivity table, in all five languages. README, the architecture docs, the ERDs and the use-case diagrams now describe the fused entity model (the ModelProjectListing facet, "Use in studio" adoption).

- **Agents can author models end-to-end over MCP (P1.5 G7d, 2026-07-16)** — the `update_model_project_draft` tool joins the MCP surface (25 → 26 tools), closing the loop an external agent needs to *write* a versioned model, not just create/commit/solve it (previously it had to fall back to the REST API). The solve tools (`solve_problem`, `solve_model_project`) accept `solution_filter=nonzero` for a compact response that omits near-zero variables and reports the omitted count — a few hundred zero binaries no longer blow an MCP client's context; the stored execution keeps the full solution.

### Changed

- **Variable views hide zero values by default (2026-07-16)** — a large solution is mostly zeros, which buried the variables that actually carry the answer. The execution-detail solution explorer, the visual builder's result drawer and the A/B comparison now default to showing only non-zero (or only changed) variables, each with a toggle to bring the rest back and a shown/total count so nothing is hidden silently. The variable magnitude chart always omits zero bars (they were invisible anyway). The sensitivity table filters by non-zero *reduced cost* — the informative rows there are exactly the variables sitting at zero — and says so.

### Fixed

- **Pre-merge deep review: 15 real defects fixed across the branch (2026-07-17)** — a three-pass review of the full release branch before merging surfaced and fixed: two solve routes (`/solve/multi-objective`, `/projects/{id}/solve`) missing the maintenance gate every other entry point enforces; the draft's If-Match check and both cancel endpoints doing unlocked read-then-write (a user cancel landing as the worker finished could permanently discard the computed solution; two clients with the same lock could silently lose edits); a dataset-name race returning a 500 instead of the intended 409; the JModel compiler rejecting mathematically-valid models over float residues and silently merging distinct all-digit set members beyond float precision; the studio autosave/commit 409-retry re-sending a stale snapshot over a newer save; the solve poller retrying a lost task forever ("Solving…" pinned); solves missing from the org audit log since the async rewrite; the sync solve facade blocking threads without the old 429 backpressure; and the disaster-recovery runbook still promising WAL archiving that the 2026-07-07 incident turned off. Publishing also gained an authorship rule (owner decision): a model adopted from the marketplace can only be republished after committing a change of your own — derivative works welcome, 1:1 clones not.

- **A finishing async solve could briefly report a false "Solve failed" (2026-07-17)** — the async status endpoint spread the task's progress metadata *over* its own fields, so during the final progress tick (Celery still in PROGRESS but the tick's meta saying "completed") a poll read `status: "completed"` with **no result payload**. Every consumer — the studio's solve panel, MCP clients, ERP integrations polling the REST API — could hit that window and surface a failure for a solve that succeeded milliseconds later. The endpoint now always reports in-flight state as `running` (a contract test pins it), and the studio poller additionally treats a result-less "completed" as transient instead of terminal. Found by driving the full 44-spec E2E suite for the v3.0.0 close-out — the whole suite now runs green against the production-target stack, after re-anchoring stale specs to the post-fusion reality (auto-router default in import, generator-backed template cards, the retired `/workspace/usage` route, real-PDF upload fixtures matching the backend's pypdf extraction).

- **Owner live-test round: polish across the fused flow (2026-07-17)** — the sensitivity tab now speaks your language (the raw English "Approximate — based on LP relaxation" note is localized; "Shadow Price"/"Binding" become real terminology in es/ca/fr/de) and no longer renders a wall of invisible zero bars: zero shadow prices are dropped and an all-zero MIP gets an explanation instead of an empty chart. Publishing validates the 10-character description in the form and maps the raw pydantic error to a friendly message. Marketplace listings that carry nothing to materialize (legacy demo rows) disable "Use in studio" up front with an explanation instead of failing the click. The legacy Visual Builder / Templates / AI Assistant nav entries retired — the studio's lenses, launcher and template gallery are the one door. And a deep diacritics sweep fixed **655 broken translations**: missing Spanish ñ/tildes, a broken Catalan verification block ("Insiglia"), an accent-less French templates batch (~424 strings), and German templates whose umlaut words had been amputated ("erfüllen" → "erf.") — reconstructed sentence by sentence.

- **The announcement banner meets WCAG AA contrast (2026-07-17)** — the site-wide announcement banner rendered black text on red-600 (4.4:1, below the 4.5:1 AA minimum for its 14px copy) and failed the public axe sweep on every page while enabled. It now uses white on red-700; the banner documentation screenshots were regenerated. The nine E2E specs that still visited the `/pricing` page removed with ADR-008 (SEO canonical/metadata, i18n switcher, axe/a11y sweeps, plausible tracker, visual/feature audits) were re-anchored to living pages (`/contact`, `/terms`) — all rerun green against the production-target stack.

- **The landing page caught up with the fused platform (2026-07-17)** — the home's MCP showcase still advertised the retired `activate_catalog_model` tool and claimed "12 tools"/"19 Curated Tools": it now lists the real 26-tool surface including the model-project authoring group. The page metadata dropped the money-era "Buy" ("Build, Use, or Automate") and credits both solvers; the solver disclaimer no longer speaks as if SCIP were the only engine; the "how it works" steps mention the studio's four authoring lenses. Dead pre-redesign i18n subtrees (`public.features`, `public.problemTypes`, the credit-era account tool group) were pruned across all five languages, and the stale translations E2E spec (old hero copy, dead pricing page) was rewritten to the current product.

- **Dead "purchases" analytics removed (2026-07-17)** — the `marketplace.purchase` event type survived ADR-008 but nothing ever emitted it again: the admin conversion funnel's last step and the "Purchases" KPI card were permanently zero. The funnel now converts on `marketplace.activate` (a "Use in studio" fork — the real adoption event) and the KPI card counts Adoptions. Residual stale rhetoric in the UI copy ("activate", "premium models from verified sellers", credit-era transaction labels) was reworded or removed across all five languages.

- **The execution "PDF" export is now an honest, useful printable report (2026-07-16)** — the old export produced a visually broken page (a duplicated element nested the metadata grid), was labelled "PDF" while producing an HTML page, and printed every variable unfiltered (hundreds of zeros; huge models froze the tab). The rebuilt report carries the model name, solver, gap and a constraints section, shows non-zero variables only (with an explicit omitted count) capped at 500 rows, follows your language for text/number/date formatting, and is labelled "Printable report" (its Print button is still the way to save a PDF). The CSV export now fills the variable bound columns it always left empty.
- **Favorites/recents attribution and action (P1.5, 2026-07-16)** — favorites showed "by Unknown" for every seeded/backfilled listing (the legacy catalog never carried an author organization): the official seed now stamps its org on the listing and the favorites/recents endpoints fall back to the owning project's organization. Their primary action now forks the model into the studio ("Use in studio") instead of driving the retired activate-era execution page.

### Changed

- **"Sellers" are now authors (2026-07-16)** — with money gone (no sales, no earnings) and the marketplace fused into the studio, the platform speaks of *authors* who publish and share models, measured by adoption. Public author profiles moved to `/marketplace/authors/{org}` (old `/marketplace/sellers/{org}` links redirect), the footer and admin analytics adopt the author wording across all five languages, and the dead money-era dashboard components (revenue chart, conversion funnel, geo distribution, onboarding checklist, top-models table) were removed. The `/api/v2/seller/*` wire paths and a few response keys keep their legacy names until the next contract release.

- **One model entity: the marketplace fused into the studio's ModelProject (P1.5 / ADR-006 D4, 2026-07-13)** — the historic split between "catalog models", "activated models" and studio projects is gone. A marketplace listing is now a *facet* of a ModelProject (publish pins a committed version; officials keep their parametric generator on the listing), and **using a marketplace model means forking it into your studio** — one "Use in studio" button seeds a ModelProject (optionally with your own inputs for parametric officials), which you then edit, version, solve and re-publish like any other model. `POST /models/{id}/execute` executes one of your ModelProjects (generator-backed forks render inputs; plain models solve their content directly); executions, reviews, favorites, history, analytics and admin views are all keyed on the project. Legacy `/solve` model pages redirect to the studio and old marketplace/model ids keep resolving (they were preserved as project ids).

### Removed

- **The legacy "activate" flow and the separate organization-model entity (P1.5, 2026-07-13)** — `POST /models/catalog/{id}/activate`, the my-models CRUD (`/api/v2/models` list/detail/schema/create/update/deactivate), the legacy `/models/{id}/publish`, and the private generator-definition model type are gone; their MCP tool `activate_catalog_model` is replaced by `create_model_project_from_marketplace` (25 tools). Adoption signals (author notification + activation counter) now fire when someone forks a listing.

- **The paid marketplace and the entire credit system (ADR-008, 2026-07-10)** — Stripe/billing/invoices, seller earnings/withdrawals/featured placements, and credits (grants, per-solve/per-message charges, balances, 402s) are gone: every solve and assistant message is free. Fair use is enforced by rate limits, a daily solve quota, per-solve time/size caps and a monthly EUR budget for the AI assistant (BYOK remains unlimited). Marketplace activation is always free; catalog price filters were removed, and the `get_credit_balance` MCP tool is gone (26 → 25 tools).

### Changed

- **All platform timestamps are timezone-aware UTC (ADR-007 S6c, 2026-07-10)** — every stored date/time column is now `timestamptz` and API responses carry an explicit UTC offset, so clients no longer have to guess (the root fix behind the earlier "hace 2 horas" display bug).
- **Marketplace model execution rides the async pipeline in both modes (ADR-007 S6d, 2026-07-10)** — the last in-request solver call is gone; the sync mode waits on the queued run and keeps its exact response, degrading to `202 + task_id` on a long solve. A solver-internal error is now refunded consistently in async mode too.
- **Scenario runs compile on the server (ADR-007 S7, 2026-07-10)** — "Solve all" sends one small request per dataset and the server compiles the JModel source against it, instead of uploading multi-MB compiled models from the browser (which a reload could abort mid-flight).
- **Scheduled triggers are now priced (2026-07-05)** — a trigger solve now costs the standard per-solve credits like any other solve; previously a pricing bug made triggered solves effectively free.

### Fixed

- **Closed a solve/reaper credit race (ADR-007 S6b, 2026-07-06)** — the background sweep that fails and refunds abandoned solves now locks each row before acting, so a solve that finishes at the same moment can no longer be double-written or wrongly refunded (a completed solve stays completed and charged).
- **The web app no longer breaks on a long solve (ADR-007 S5, 2026-07-06)** — now that a solve which outlives the server-side wait returns `202 + task_id`, the app's solve, multi-objective, template and file-import flows transparently wait for the queued result to finish (polling in the background) instead of rendering a broken/empty result; the studio was already resilient via its live-progress sessions.
- **Credit correctness across the solve paths (2026-07-05)** — several credit bugs found by an end-to-end audit: concurrent retries with the same `Idempotency-Key` can no longer refund more than they charged; a solve that errors (e.g. a bad expression) is never charged, on the marketplace and in triggers as well as `/solve`; every solve in a workspace without a credit pool is charged (not just the first); an invalid problem is rejected before any charge; and a refunded solver error now reports 0 credits used.
- **Large scenarios failed to launch through the web app (2026-07-04)** — solve payloads over 10 MB (the biggest TFM scenarios) were silently truncated by the frontend proxy's default body cap and surfaced as opaque "NetworkError"/500 rows in Solve-all; the proxy now allows up to the API's own 50 MB limit.

### Added

- **Template, import, project & multi-objective solves now ride the async pipeline (ADR-007 S4, 2026-07-06)** — `POST /solve/templates/{id}/solve`, `POST /import`, `POST /projects/{id}/solve`, and `POST /solve/multi-objective` join `POST /solve` on the one async pipeline (pre-paid credits, a durable execution record, progress/cancel/history for free); each keeps its exact synchronous result contract and degrades to `202 + task_id` for a solve that outlives the wait budget. Solving a specific committed version now records which version the run came from.
- **One credit model + one execution writer for every solve (ADR-007 S3, 2026-07-05)** — the marketplace model execution and scheduled triggers now pre-pay and refund exactly like the main solve, so a failed solve never leaves a charge, and a single writer keeps every execution's history consistent.
- **`POST /solve` now rides the async pipeline (ADR-007 S2, 2026-07-05)** — the classic synchronous endpoint keeps its exact contract (result shape, `Idempotency-Key`, error codes) but executes through the one async pipeline: pre-paid credits, a durable execution record from the start, progress/cancel/history for free, and no more solves dying at proxy timeouts — a solve that outlives the wait budget returns `202 + task_id` to poll instead. An idempotent retry that races the original now attaches to the same run instead of erroring.
- **`?wait=true` on the async solve (ADR-007, 2026-07-04)** — `POST /solve/async?wait=true` waits server-side (up to 100s) and returns the classic synchronous result directly — the "just give me the answer" contract for ERP/MCP callers — degrading to the normal task envelope if the solve needs longer; async responses now also carry the `execution_id` alongside the `task_id`.
- **Conditional expressions in JModel (DSL #5, 2026-07-04)** — `if <condition> then <term> [else <term>]` selects coefficients and terms at compile time from indices and param values (`if setup[i] == 1 then fixed[i] * y[i]`); only the taken branch is evaluated, so sparse conditional data just works, and a missing `else` is 0.
- **Set operators in JModel (DSL #4, 2026-07-04)** — `set S := A union B;`, `A diff B` and `A cross B` build sets from other sets (parentheses, literals and ranges allowed, `cross` concatenates tuple dimensions): define arc sets, exclusions and product index spaces from data instead of enumerating them by hand.
- **Quadratic models in JModel (DSL #1, 2026-07-04)** — JModel now compiles quadratic terms (`x*y`, `x^2`, `(x + y)^2`) into solvable QP/MIQP/QCP/MIQCP problems: products distribute at grounding, anything beyond degree 2 is a clear compile error, and the solve path handles the rest (SCIP objectives via an epigraph reformulation; HiGHS now honestly rejects quadratics instead of silently dropping them; sensitivity is marked unavailable for quadratic models).
- **Integer ranges in JModel (DSL #2, 2026-07-04)** — `set T := 1..96;` declares an inclusive integer range as a set, exactly like the equivalent brace literal — the natural way to write time periods and other numbered index sets.
- **TFM bridge: one MDPDP model, 17 scenario datasets (S6, 2026-07-04)** — `scripts/tfm_bridge.py` seeds a studio project with the thesis MDPDP formulation (Vall-llaura 2017, eqs. 4.1–4.10) written once as a JModel over sparse tuple arc sets, plus its 17 scenarios as named datasets (scenario_00 = the fabricated Table 3 data, solving to the thesis optimum 90 through the dataset path; 01–16 synthetic at the Table 4 sizes) and as importable `.dataset.json` files; the dataset size cap rises 5 → 16 MB to fit the largest scenario.
- **Tuple sets in JModel (S6a, 2026-07-03)** — Sets can now hold N-dimensional members (`set ARCS := {(a, b), (b, c)};` inline, `set ARCS dimen 2;` from a dataset, members encoded `"a,b"` like composite param keys, also in `.dat` files): variables and params index over the actual sparse members instead of a cartesian closure, qualifiers unpack them (`sum{(i, j) in ARCS : j == n}`), and equality filters run as indexed slices so sparse routing-style models ground in linear time — the grounding budget rises to 2M elements to fit the largest TFM scenario.
- **Table view for datasets (S2b, 2026-07-03)** — The dataset editor gains a structured Table view over the same JSON: sets as member lists, scalar params as a number field, indexed params as index/value rows with add/remove — switch views freely, the data never forks.
- **Live dataset↔model validation (S5, 2026-07-03)** — While editing a dataset, the editor checks it against the model's declarations as you type: "fills the model", missing/unknown sets or params, scalar-vs-indexed shape and composite-key arity — guidance only, the compiler stays the source of truth.
- **Compare N scenarios side by side (S3, 2026-07-03)** — The Solve tab gains a Scenarios section: select several datasets, solve them all in one click, and watch a live comparison table (dataset · status · objective · time · solver, server-derived so it survives reloads); a dataset that doesn't fill the model shows the compiler message as a failed row, and any two completed runs diff their solutions variable by variable.
- **Import a dataset from a file (S2c, 2026-07-03)** — The dataset editor accepts AMPL `.dat` (sets, scalar and N-D params), `.csv` (one param per file, header auto-detected, name from the filename) and our JSON shape; the file is parsed server-side into a preview with compiler-grade errors and saved through the normal create.
- **Dataset skeleton from the model (S2a, 2026-07-03)** — One click pre-fills a new dataset with the model's real declared symbols (sets → `[]`, scalar params → `0`, indexed → `{}`) via a new parse-only `/dsl/inspect` endpoint — no more writing the JSON shape by hand.
- **"Data" tab in the studio (S4, 2026-07-03)** — Input data gets its own top-level tab (Build · Data · Analyze · Solve, shown while JModel is enabled): dataset management moves out of Analyze, the Build "Editor" lens is renamed "JSON", and data-shaped JModel errors plus the Solve dataset chip now link straight to the Data tab.
- **Dataset provenance in the executions history (S1, 2026-07-03)** — Every solve launched with a dataset now records which one it ran with; the history table and the execution detail show a dataset badge, and the name survives even if the dataset is later deleted.
- **Scenarios: one model, many named datasets (§8, 2026-07-03)** — A JModel can declare its sets/params without values (`set I;` / `param w{I};`) and fill them from a named dataset ("Q3 forecast", "+20% demand") managed in the Analyze tab: create/edit/delete data bundles, pick which one the JModel compiles against, and the Solve tab shows which data the result used. One model, N scenarios — the model/data separation. Gated behind `JAOT_DSL` like the JModel lens.
- **JModel DSL editor — experimental (P5, 2026-07-02)** — A new declarative modeling language (sets, params, indexed variable & constraint families, `sum{}`, set-filters) as a 4th "JModel" lens in the studio Build tab. Write a compact model that compiles to the flat problem — a 200×14 assignment is ~12 lines instead of thousands of nodes. Off by default behind the `JAOT_DSL` flag (ships dark).
- **Sharper AI grounding: worked examples + reranking (2026-07-01)** — The formulation assistant's RAG now indexes a real worked-example formulation (concrete variables/objective/constraints) for every template alongside the summaries, so suggestions imitate proven models; an optional local cross-encoder reranker (off by default) can re-order retrieved context for higher precision. All local — no data leaves the box.
- **AI Assistant lens (P4b, 2026-06-30)** — Build a model by chatting in the studio and refine it incrementally ("add y", "make x integer"); the conversation is scoped to the model and each result flows into it live, with RAG grounding and file attachments.
- **Durable AI conversation (2026-06-30)** — An in-flight AI generation now survives switching studio tab/sub-lens; the produced model still lands even from another tab.
- **Explain a model & a version diff with AI (P4, 2026-06-30)** — Grounded plain-language explanations of what a model optimizes (Analyze) and what changed between two versions (history). Python computes the facts; the LLM only narrates them.
- **Editor lens (P3, 2026-06-30)** — Edit the model as JSON text in the studio; valid edits reflect on the canvas and autosave, invalid JSON blocks solve/commit.
- **Centralization: templates & marketplace → studio (P2, 2026-06-30)** — Using a template or marketplace model now seeds a versioned model in the workspace (born with a v1 commit) instead of a one-off solve.
- **"Model, Analyze & Solve" workspace + first-class `ModelProject` (2026-06-29, [ADR-006](ARCHITECTURE/08-decisions/ADR-006-model-project-unification.md))** — A unified studio where one model is built, analyzed and solved across Build · Analyze · Solve tabs, with git-style versioning (commit with a "what/why"), autosave, live model stats, and a real-time Live Solve convergence chart. MCP grows 19 → 26 tools.
- **My Models: org scope, attribution & bulk cleanup (2026-06-29)** — Org-wide model list with creator attribution, a Mine/Whole-org filter, and bulk restore/delete in the Archived tab.
- **Archive, restore & permanently delete models (2026-06-29)** — Active/Archived tabs with a soft-delete (+Undo) and a gated, irreversible permanent delete.
- **Execution history truth for async/studio solves (2026-06-30)** — Async solves now persist their result (no more "pending" zombies) and show the model name, author, and a "Studio model" origin instead of an opaque id.
- **Import/Export across every model surface (2026-06-28)** — Export (MPS/LP/CIP/JSON, no solve) and import (MPS/LP/CIP) wherever you work with a model; every solve records its provenance; MCP gains export tools (17 → 19).
- **Read-only organization overview for admins (2026-06-27)** — A View action opens a read-only org detail page (config, limits, credits, executions, users, API keys, models) without editing it.
- **BYOK — per-organization Anthropic API key (2026-06-26)** — An org can run all AI features on its own Anthropic account (BYOK-first: no JAOT credits charged). The key is Fernet-encrypted at rest, never returned in plaintext, never logged.
- **Infeasibility explainer — IIS + AI (P2, 2026-06-26)** — An INFEASIBLE solve now computes a minimal conflicting set (Irreducible Infeasible Set) solver-agnostically and explains it in plain language on the result page.
- **Solution explainer + sensitivity analysis (P1, 2026-06-26)** — After a solve, get per-variable reduced costs alongside shadow prices and a grounded plain-language explanation of the result.
- **SolverAdapter Protocol (Phase 4, 2026-04-14)** — Solver-agnostic abstraction: `SolverAdapter` Protocol + capabilities + registry; `SCIPAdapter` owns the SCIP pipeline; 6 import-linter contracts keep pyscipopt inside the adapter.
- **Solver domain extraction (Phase 3, 2026-04-13)** — First bounded context extracted to `app/domains/solver/` (ADR-004); old paths preserved via shims, zero behavior change.
- **Modular monolith foundation (Phase 2, 2026-04-10)** — `app/domains/` + `app/shared/` structure with `import-linter` enforcing the boundaries.
- **RAG system (2026-04-03)** — Qdrant + sentence-transformers (BAAI/bge-small-en-v1.5, local CPU); hybrid dense+sparse retrieval; enabled in production.
- **File Import/Export (P5, 2026-04-04)** — 6 formats (MPS, LP, CIP, SOL, CSV, JSON); drag-and-drop import; solve analytics dashboard.
- **Template system overhaul (2026-04)** — 102 templates in 34 unified YAML files, 27 problem generators.
- **MDPDP generator** — Multi-Depot Pickup-and-Delivery with time windows and tachograph constraints.
- **Monitoring alerts** — 24 alert rules across 7 groups; SMTP email alerts.
- **CI pipeline** — lint, test, deploy stages replacing manual deployment.
- **LLM stable error codes** — raw error strings replaced with i18n-mapped codes.
- **Idempotency hardening** — `Idempotency-Key` bound to the request body hash.

### Changed

- **Execution/usage limits relaxed for open-source self-hosting (2026-06-29)** — Solve time cap 1 h → 24 h (default 60 s → 300 s), request body 1 MB → 50 MB, per-solver credit multipliers flattened to 1.0, and quotas/LLM budget loosened. Auth rate limits and the login lockout are unchanged. All values stay tunable from the admin panel.
- **RAG context capped by `RAG_MAX_TOKENS` (2026-06-30)** — Retrieved RAG documents are now budget-bounded (most-relevant-first) so the system prompt can't bloat without limit.
- **Dependencies upgraded to latest stable (2026-06-27)** — Backend + frontend swept to latest stable, validated against the full test suites. A few packages held at a documented cap where a new major breaks behavior or a peer (fastapi, radix-ui, lucide-react, typescript).
- **Terms & Privacy rewritten for the open-source / self-host model (2026-06-27)** — Both documents (5 locales) drop the paid-SaaS framing: hosted jaot.io is free, self-host is Apache 2.0; adds an AI Assistant section, Usage Quotas, HiGHS, and cookieless Plausible.
- **Configurable auth rate limits (2026-06-26)** — Login/signup/verification/reset limits became tunable platform settings; the strict defaults were loosened.
- **Solver upgraded to SCIP 10.0.2 (2026-06-26)** — license attribution and citation metadata synced.
- **Marketplace de-monetized → free & collaborative (2026-06-25)** — `MONETIZATION_ENABLED` (default off) gates every paid feature; activation/publishing are free and credits become a pure usage quota. The paid code is dormant and reversible.
- **Solver orchestrator slimmed (Phase 4)** — `solver_service.py` rewritten as a solver-agnostic orchestrator (-66%); all SCIP code lives in the adapter.
- **Test suite audit** — dead/low-value tests removed, weak assertions strengthened, missing tenant/concurrency/idempotency coverage added.

### Added

- **Per-model run history on the Solve tab (2026-07-04)** — A "Runs of this model" card lists the open project's executions only (status, dataset, objective, time, solver), each row linking to the execution detail; the global history stays under Solve → Executions.

### Fixed

- **Launching many scenarios at once is survivable (2026-07-04)** — "Run all" launches at most 3 datasets at a time (big scenarios upload tens of MB each; 16 at once sat for minutes behind the browser's connection limit), and leaving/reloading the page while a batch is still launching now asks for confirmation instead of silently losing the not-yet-queued runs.
- **Times shown one timezone off (2026-07-04)** — API timestamps (naive UTC) were parsed as local time, so every displayed date sat hours in the past ("hace 2 horas" on a run that just finished); all date displays now parse them as UTC.
- **A burst of big solves froze the whole API (2026-07-04)** — the async-solve and validate handlers did CPU-bound work on the event loop; they now run in the threadpool, so health checks and the rest of the UI stay responsive while large problems are ingested.
- **A failed autosave no longer sticks at "Error al guardar" (2026-07-04)** — it retries with the latest in-memory model every 10 seconds instead of waiting for the next edit.
- **Large solves no longer die with an opaque 500 (2026-07-04)** — The expression parser rebuilt its known-variables set on every parsed expression, so auto-routing or building a 100k-constraint model cost O(constraints × variables) — minutes of CPU that Next's 30-second proxy timeout turned into a bare 500. Name sets are now built once per problem and adopted without copying (routing a 200×200 TFM scenario: >2 min → 2.8 s; queueing it: 5 s), and the proxy timeout rises to 120 s.
- **Scenario runs show what they're doing (2026-07-04)** — "Run all" now marks each selected dataset as Compiling…/Queueing… and updates the table as each run is queued (big scenarios spend many seconds uploading before a server row exists); the solution-diff button is always visible with a hint on how to enable it.
- **Template gallery: page scroll restored + search (2026-07-04)** — `/studio/templates` rendered inside the workspace's full-screen shell, clipping the 102 cards to one screen with no scroll or sidebar; it is a normal list page again and gains a search box that filters on the localized name/description/category ("mochila" finds Knapsack).
- **"Run all scenarios" explains itself when the project has no JModel source (2026-07-04)** — Scenarios recompile the JModel formulation with each dataset's values; on a flat/imported model (already grounded) the button used to sit disabled with no hint. The section now says why and links to the JModel lens.
- **A broken JModel/JSON editor no longer lets a tab switch solve the previous model silently (2026-07-03)** — A source that doesn't compile keeps solve/commit blocked even after leaving the lens (the block used to clear on unmount), and the broken text survives the round trip with its error. A broken or out-of-date JModel source is now explicitly marked "not applied"; a drifted source locks read-only until you explicitly recompile it, so replacing the newer model is always a deliberate act.
- **Solves overcharged credits with default options (2026-07-02)** — When the default solve time limit rose to 300 s (relaxed limits), the credit formula still granted the free window only up to 60 s, so every solve using default options billed ~4 phantom "time-bonus" credits. The free threshold now tracks the actual default limit.
- **Execution history could show another org's model name (2026-07-02)** — The run history resolves a model's name/author from a client-supplied source id; that lookup is now organization-scoped, so a run pointing at another org's project id can never surface that project's name or author.
- **Complex/parametric models crashed the solver (2026-07-01)** — A constraint that reduces to a constant (no variable terms — e.g. a parametric/indexed expression the flat parser can't bind) no longer aborts the SCIP build with a cryptic "given constraint is not ExprCons but bool". It's now anchored and handled as redundant when satisfied or infeasible when violated, so the solve returns a clean result instead of an error.
- **Model shown empty after a non-canvas edit + reload (2026-07-01)** — Replacing the model from a non-canvas source (AI Assistant / Editor) now re-evaluates the canvas hairball guard, so a large→small swap re-enables the canvas and autosave persists a canvas that matches the model. Load also ignores a stale canvas (fewer nodes than the model has variables) and rebuilds it from `model_json`, so a model can no longer render as "0 variables / empty" next to a real saved model.
- **"Explain this model" reset when leaving the Analyze tab (2026-07-01)** — The explanation stream and its conversation were lifted to the workspace provider (above the tabs), so an in-flight explanation now survives switching Build/Analyze/Solve and is still there (streaming or finished) on return — matching the durable AI Assistant and solve sessions.
- **"Explain this model" failed on very large models (2026-06-30)** — The grounded model explanation now samples a huge formulation to a representative head (long expressions clipped) instead of dumping every variable, so a 48,556-variable model no longer overflows the LLM context window (was a 400 "prompt is too long"). The authoritative counts still come from the computed statistics block.
- **Live Solve chart never streamed for email/password sessions (2026-06-29)** — The progress WebSocket now authenticates from the same-origin JWT access cookie, so the convergence chart streams live on the deployed site (not just with an API key).
- **More at-a-glance model & solver info (2026-06-29)** — Analyze gained the objective sense, a constraint operator breakdown, and avg terms/constraint; Solve shows which solver actually ran for an `auto` selection.
- **Multi-objective form restricted to two objectives (2026-06-29)** — The form is now strictly bi-objective, matching the backend (which solves exactly two); a third objective no longer returns a cryptic 422.
- **Importing a large model no longer freezes the browser (2026-06-29)** — A model exceeding the canvas scale cap skips the visual canvas and hydrates directly from the model JSON (verified with a 48,556-variable model).
- **Large models could not be solved (2026-06-29)** — Raised the expression-length cap (500K → 5M chars) and the free-plan `max_variables`, so big imported models reach the solver instead of 4xx-ing.
- **An imported large model was silently emptied on open (2026-06-29)** — Fixed a canvas-bridge race that could overwrite a too-large model with an empty canvas on load.
- **Durable solve sessions (2026-06-29)** — A running solve is now derived from the server, so it survives reload, a duplicated tab, another device, or power loss, and is picked up across tabs while idle.
- **"Explain this solution" missing after an async solve (2026-06-28)** — The async-completion handler now fetches the canonical execution record, so both explainers render identically in sync and async mode.
- **Admin lists could render empty from a stale cache (2026-06-27)** — Authenticated API responses are now `no-store`, and admin lists show a load error with retry instead of a misleading empty state.
- **GDPR data controls reachable for every user (2026-06-27)** — "Export your data" / "Delete account" moved to My Profile (always in the sidebar).
- **Landing copy + docs navigation (2026-06-26)** — toned down the landing copy and corrected the docs page count.
- File import JSON depth check (pre-parse instead of `RecursionError`).
- 15 missing i18n keys added to es, ca, fr, de.
- PDF export blank tab; post-import redirect to execution detail.
- Export 401 auth error.
- Race condition in the P5 import/export flow.
- Generic `pytest.raises(Exception)` replaced with typed exceptions.

---

## [2.8.0] - 2026-02-19

### Invoices, SLA, Health Monitoring

### Added

- **Invoice system** — automatic invoice generation for subscriptions and credit top-ups; `Invoice` model with line items (JSON), totals, tax, Stripe refs; HTML rendering for print-to-PDF; `GET /billing/invoices`, `GET /billing/invoices/{id}`, `GET /billing/invoices/{id}/html`; 35 tests.
- **SLA document** — `docs/operations/SLA.md` with uptime targets (99.0%–99.95%), service credits, incident response times, rate limits, data retention, support tiers.
- **Health status endpoint** — `GET /api/v2/health/status` with component checks (database connectivity + latency, SCIP solver, memory, disk); returns healthy/degraded/down status for SLA monitoring.
- **Alembic migration** — `invoices` table with indexes on `invoice_number` and `organization_id`.

---

## [2.7.0] - 2026-02-19

### Billing, Templates, Deployment & Testing

### Added

- **Stripe billing integration** — subscription checkout, credit top-up purchases, webhook processing, billing portal; `app/services/stripe_service.py`, `app/api/v2/billing.py`; Organization model extended with `stripe_customer_id` and `stripe_subscription_id`.
- **4 new model templates** — Employee Scheduling (shift coverage, unavailability, min/max hours), Vehicle Routing / CVRP (MTZ subtour elimination, capacity constraints), Portfolio Optimization (linear Markowitz with cardinality and sector constraints), Bin Packing (symmetry breaking, capacity constraints).
- **Public credit calculator** — `POST /api/v2/credits/calculator` (no auth required); estimates credits based on problem complexity with cost-by-plan breakdown.
- **Production deployment config** — `docker-compose.prod.yml` with production server tuning, Caddy TLS, json-file logging, `.env.production` template.
- **91 new backend tests** — `test_template_engine.py` (46 tests: all generators, edge cases, sanitization), `test_billing.py` (24 tests: Stripe service, endpoints, webhooks), `test_credit_calculator.py` (21 tests: formula, validation, edge cases).
- **Onboarding email sequence** — 5-email drip campaign (Day 0, 1, 3, 7, 14); pluggable email service with console/SMTP backends; Celery tasks with retry; triggered on signup.
- **Email service abstraction** — `app/services/email_service.py` with `ConsoleBackend` (dev) and `SMTPBackend` (prod).
- **PostgreSQL test infrastructure** — tests run against real PostgreSQL (`jaot_test` database); 23 PG-specific tests (schema, constraints, JSON, Alembic, Stripe).
- **Alembic migrations** — full infrastructure, initial migration for all tables, upgrade/downgrade tested.
- **Python SDK** — initial `JAOT` client package (internal, not published); `sdk/` package with solve (template + raw), model catalog, credits, error handling with retries; 33 tests.

### Changed

- Dockerfile healthcheck URL fixed from `/api/v1/health` to `/api/v2/health`.
- Landing-page pricing corrected to match platform settings (Free: 50 credits, Starter: €19/600 credits, Pro: €49/2,500 credits, Business: €149/20,000 credits).
- `stripe>=8.0.0` and `alembic>=1.18.0` added to `requirements.txt`.
- Stripe and email env vars added to `app/config.py` and `.env.example`.
- Billing webhook and credit calculator added to public endpoints in auth middleware.
- `seed_models.py` updated to feature the new templates in the marketplace.
- `app/db/base.py` refactored: lazy import of `SessionLocal` in `get_db()`.

### Fixed

- Landing-page plan data inconsistency (was showing €99/10K for Pro instead of €79/5K).

---

## [2.6.0] - 2025-12-15

### Notifications + Documentation

### Added

- **Notification system** — in-app notifications for execution events (job queued, completed, failed); `Notification` model with read/unread state; REST endpoints at `/api/v2/notifications`.
- **Full developer documentation** — QUICKSTART, CONTRIBUTING, SOLVER internals, API reference (all endpoints with JSON examples), AUTHENTICATION, WEBSOCKETS, ADRs for SCIP, RabbitMQ/Celery, and multi-tenancy.

### Changed

- Documentation restructured from flat files into `docs/getting-started/`, `docs/api/`, `docs/development/`, `docs/ARCHITECTURE/decisions/`, `docs/product/`.
- Roadmap switched from version-based to milestone-based format.
- README rewritten as a concise landing page with a 3-line quickstart.

---

## [2.5.0] - 2025-12-11

### Refactoring — Modular Architecture

A multi-phase internal refactor to improve maintainability without changing external behaviour.

### Changed

- **Solutions → Models rename** — all internal and external references updated (backend, frontend, DB schema, Celery tasks, tests).
- **Modular routers** — `models.py` (2,000+ lines) split into focused sub-modules under `app/api/v2/routes/models/`.
- **Modular admin** — `admin.py` split into a modular structure under `app/api/v2/routes/admin/`.
- **Modular profiles** — `profiles.py` extracted into `app/api/v2/routes/profiles/`.
- **Shared schemas** — common Pydantic schemas extracted into `app/schemas/` to eliminate duplication across `auth.py`, `keys.py`, and other routes.
- **Shared utilities** — `app/utils/` now contains `id_generator`, `pagination`, `datetime_helpers`, `validators`, `slug`.
- Base currency changed from USD to EUR.
- All pytest deprecation warnings resolved.

### Fixed

- `init_db.py` updated to include all models (`ModelReview`, `UserFavorite`, `RecentModel`).
- Admin endpoints no longer matched by public path patterns (auth bypass bug).
- Sidebar UX and public profile endpoints.

---

## [2.1.0] - 2025-12-09

### Async Execution + Marketplace

### Added

- **Async execution** — jobs submitted to a RabbitMQ queue, processed by Celery workers.
- **WebSockets** — real-time execution monitoring; convergence-graph events streamed to the frontend.
- **Publish to marketplace** — model authors can publish solutions from the UI.
- **Marketplace profiles and reviews** — author public profiles, star ratings, review text.
- **Verification system** — badge management and organization verification.
- **Favorites** — users can bookmark models; `UserFavorite` and `RecentModel` tracking.
- **Execution validation** — input-payload validation before job submission.
- **Cancel / rerun** — cancel queued executions; rerun with the same payload.
- **Solutions management page** in the admin dashboard.

### Changed

- Frontend icons migrated from emoji to Lucide React.
- `/settings` renamed to `/workspace`.

### Fixed

- Hydration error in Next.js SSR.
- Default `Code` icon for custom solutions without a category.
- SolverService used in Celery tasks (was incorrectly using `UniversalSolver`).
- Re-activation of already-activated solutions prevented.

---

## [2.0.0] - 2025-12-09

### Major Release — Complete V2 Architecture

Full rewrite of the platform. The plugin-based system was replaced by a universal solver architecture.

### Added

- **Universal SCIP solver** — single `/api/v2/solve` endpoint for all LP/MIP problems.
- **Model Catalog** — browse and activate pre-built optimization solutions.
- **My Models** — per-organization model activation and management.
- **Execution history** — full audit trail with timing, status, and credit usage.
- **Credits system v2** — multi-currency (EUR, USD, GBP, CHF), earned credits, scheduled withdrawals.
- **Withdrawal system** — request and schedule credit withdrawals.
- **Modern React frontend** — Next.js 15, TypeScript, Tailwind CSS, shadcn/ui components.
- **Admin dashboard** — comprehensive organization, user, model, and credit management.
- **API v2** — complete REST API at `/api/v2/` with OpenAPI docs.
- **Health & metrics** — `/api/v2/health` endpoint with system metrics.
- **Docker Compose** — multi-service orchestration (API, Celery, PostgreSQL, RabbitMQ, Ollama, frontend).
- **Pagination** — all list endpoints return `PaginatedResponse[T]`.
- **Rate limiting** — per-plan rate limits on the solve endpoint.
- **Multi-tenant auth** — SHA-256 hashed API keys; auth always enabled on all endpoints.

### Removed

- Plugin system.
- AI Builder (returned later as the AI Model Builder).
- Wizard (replaced by model templates).
- API v1.
- Legacy HTML/JS/CSS dashboard.
- Static frontend.

### Changed

- PostgreSQL as the exclusive database (SQLite removed from the production path).
- Authentication simplified to API key only (no session cookies).
- Docker setup consolidated into a single `docker-compose.yml`.

---

## [1.5.0] - 2025-11-27

### GenAI Factory + Sandbox

### Added

- **GenAI Factory** — AI-powered model generation, migrated to a local Ollama backend.
- **Secure sandbox execution** — process isolation and resource limits for user-submitted code.
- **Wizard v2** — variable-based JSON generation for model configuration.
- **Admin metrics dashboard** — builder stats and enhanced user management.
- **Admin filtering** — filter users and organizations in the admin panel.
- **Organization deletion** — admin can delete organizations and their data.
- **Credit tracking** — admin user tracked in credit-addition events.

---

## [1.4.0] - 2025-11-25

### Pagination + Admin Improvements

### Added

- Pagination on API keys, usage history, and admin activity endpoints.
- Loading indicators for dashboard actions.
- Shared utilities for API, UI, and pagination across frontend components.

### Changed

- Admin and dashboard scripts refactored to use shared utilities.
- Common UI component styles extracted into `vintage-theme.css`.

---

## [1.3.0] - 2025-11-23

### Admin Dashboard Redesign

### Added

- Comprehensive admin dashboard with vintage-theme styling.
- User management: view, suspend, delete users.
- Organization management: view credits, usage, API keys.

### Changed

- GenAI Builder migrated from Claude/GPT to a local Ollama backend (no external API costs).

---

## [1.2.0] - 2025-11-19

### GenAI Factory MVP

### Added

- GenAI Factory MVP: generate optimization models from natural language using Claude Sonnet + GPT fallback.
- Database models for GenAI Factory (`GeneratedModel`, `GenerationRequest`).
- Type-safety improvements in the credits service.

---

## [1.1.0] - 2025-11-18

### Analytics + Vintage Theme

### Added

- Time-series analytics: credit usage over time, execution trends.
- Granular analytics: problem-type breakdowns, constraint-complexity distribution.
- Usage analytics dashboard in the frontend.
- End-to-end auth journey tests for the solve endpoint.
- Comprehensive test suite for the logistics module.

### Changed

- UI redesigned with a vintage/retro theme.
- Real auth middleware used in admin tests (replaced mocks).

---

## [1.0.0] - 2025-11-13

### Initial Release

- Plugin-based optimization system with a PySCIPOpt backend.
- Multi-tenant architecture with organization scoping.
- Credit system with Free/Pro/Enterprise plans.
- AI Builder for plugin generation.
- Admin dashboard (HTML/JS).
- API key authentication.
- PostgreSQL database.
- Docker Compose setup.
- Comprehensive test suite and load-testing infrastructure.

---

## Notes

- v1.x used a plugin architecture that has been fully replaced in v2.
- A fresh database is recommended when upgrading from v1 to v2 (the schema is not compatible).
- Dates reflect when each change landed on the main line of development; semantic-version
  tags in the predecessor repository were in some cases applied retroactively and are not
  used as the date of record here.
