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
