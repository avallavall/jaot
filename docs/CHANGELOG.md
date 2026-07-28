# Changelog

All notable changes to JAOT are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — Semantic Versioning.

<!--
  House style, so this file stays readable:

  - One entry per user-visible change, one to three lines. What changed and what it
    means for someone using JAOT — not how it was implemented.
  - Root causes, internal identifiers, file paths and function names belong in the
    commit message and in docs/ARCHITECTURE, which is where a reader who wants the
    mechanism should end up. `git log` is the detailed record; this is not.
  - No internal plan codes. If a reader cannot resolve a reference from this repo
    alone, it does not belong here.
  - One section per change type per version (Added, Changed, Deprecated, Removed,
    Fixed, Security), in that order. Never two "Fixed" blocks in one release.
  - Dates as YYYY-MM-DD, separated by a plain hyphen.
-->

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

- **What-if analysis by real re-solves** — the analysis panel can now answer "what would one more unit actually buy me?" by perturbing the solved model and solving it again: RHS ranging on the top binding constraints (read as a tornado chart) and decision regret (what it costs to overrule a binary decision). Every number is measured on the real MIP, not on an LP relaxation. Runs on the solver queue under a configurable budget; partial results are labelled, never padded.
- **"Explain this to me" on the what-if analysis** — the assistant reads the measured scenarios back in plain business language, and is constrained to the scenarios that actually ran. Opt-in and cached per execution.
- **Advanced-model toggle on every AI surface** — both chats, the three explainers, "Generate with AI", "Explain this model" and the version-diff explanation. Off by default and remembered per user, since the advanced model costs more per call.
- **The assistant answers in your language** — chat replies and every explanation now follow the locale you are browsing in, across all five languages. Identifiers (variable, constraint and set names, expressions, JModel source) are quoted exactly, so explanations still match the screen.
- **Solvers declare what they cannot do** — `GET /solvers/available` reports each solver's capabilities and the interface acts on them: the picker names what your choice will not give you before you solve, and the Sensitivity and Live Solve panels say the solver computes no shadow prices or streams no progress instead of appearing to fail.
- **Analysis tools over MCP (26 → 30)** — agents can now ask what is saturated, why a model is infeasible, and what one more unit of a limit is worth. The plain-language explainers stay out by design: an MCP client is already a language model.
- **Family-level KPIs in the post-solve analysis** — the exact analysis aggregates by constraint family (share of binding rows, slack, utilization) and by variable family, so a 10,000-row model reads like a ten-line summary.
- **Public roadmap** — `docs/ROADMAP.md`, linked from the README. The frozen JModel grammar now ships as `docs/JMODEL_GRAMMAR.md`.

### Changed

- **Capacity limits are the operator's to set.** JAOT no longer decides how large a model may be, how many solver threads you may use, or how long you may solve. Expression and source size caps are removed, request-body size moves to `MAX_REQUEST_BODY_MB` (unlimited by default), the JModel grounding budget becomes the `dsl_max_grounded_elements` setting, and no plan limit has a ceiling in the admin panel. **0 means unlimited** on all of them. A 1000×1000 model (905,400 variables) now solves where 500×500 used to be rejected. Limits that protect a real external cost — the AI request caps, billed per token — are unchanged.
- **Limit errors name the setting to change** — they used to return `upgrade_to` / `upgrade_url` pointing at a checkout page removed with billing. They now carry `setting_key`.
- **The AI assistant runs on Claude Sonnet 5 / Opus 5** at the same list price per token, using adaptive thinking with an `effort` hint (`LLM_THINKING_EFFORT`). A data-only migration moves existing installs, leaving deliberately pinned models alone.
- **The server no longer stalls itself while it answers** — 113 endpoints did synchronous database work on the thread that serves every other request; they now run on a worker thread. Uploads, file imports, PDF extraction and model exports moved off it too, so one large file no longer freezes the server. Recorded as ADR-009.
- **Foreign keys are indexed** — 18 columns on live paths had no index, including the one every user lookup uses to scope by organisation.
- **Security gates are back in the pipeline** — dependency auditing and static analysis stopped running when CI moved to GitHub Actions while the documentation still claimed they ran.
- **Routing variable names are readable** — arc variables in pickup-and-delivery models now group by family in the solution view and carry family-level KPIs, instead of rendering as an unstructured wall.
- **The Sensitivity tab collapses degenerate shadow prices** — in a MIP most constraints often share one shadow price, so a per-constraint bar chart carried no information. Identical values now collapse to one row with a note pointing at the exact analysis.
- **"Derive draft" respects JModel's model/data separation** — deriving a saved project produces the general formulation plus a generated dataset, instead of inlining 22,500 values into the source.
- **One set of limits for the instance, instead of four plan tiers.** The tiers outlived the paid plans they came from and had drifted into four identical copies. Organisations keep their plan label; what they may do is now decided in one place. Existing installs keep whatever numbers they had configured — the migration carries across the value that restricts nobody.
- **The admin settings panel is grouped by what you came to do** — Instance, Access, AI, Solver, Email, Advanced — instead of by which table a value lives in. Search covers every setting rather than half of them, each field shows the default it would return to, and tabs are built from what the server actually offers, so a setting can no longer exist without a place to edit it. Twenty-eight were in that state, the RAG configuration among them, reachable only through SQL.

### Removed

- **Twenty-three settings that changed nothing.** Some had no reader at all — a gzip threshold the server hardcoded past, two metrics counters, four ID prefixes, both rate-limit windows. Others the panel let you edit while the value was really taken from the environment file: bind host, port, worker count, the Celery retry settings and the database URL. Each one looked like a working control.
- **`LLM_THINKING_BUDGET_TOKENS`**, deprecated last release in favour of `LLM_THINKING_EFFORT`.
- **The plan-tier editor.** Instance limits are ordinary settings now, so the tier table and the loose fields no longer render the same values twice on one tab.
- **Ninety-eight settings rows left behind by billing, the paid tiers and last release's clean-up.** Code had stopped reading them long ago but nothing deleted them, so the table held twice what the panel could show. Anyone querying the database directly now sees exactly the settings that exist.

### Fixed

- **The "Recent" tab fills up again.** Opening a model left no trace — nothing ever wrote that list — so it greeted every account with an empty state next to a Favourites tab that worked. Opening a model's page now records it, and opening it again moves it to the top instead of adding a second entry.
- **Author analytics count the visits they receive.** Views and impressions were recorded on every marketplace page and then thrown away when the request ended, so a listing with real traffic reported zeros to its author. Both are stored now, and a visit from a signed-in reader is again attributed to their organisation.
- **The contact form works while you are signed in.** On the public pages the server identifies you for the sole purpose of attaching your account to what you send — and that identification came back unusable, so the submission failed outright. Signing out and sending was the only way through.
- **Changing an API rate limit in the admin panel now reaches the organisations already signed up.** The two rate limits are kept on the organisation, copied when it is created, so editing the setting changed what new organisations would get and nothing about the existing ones. A limit set deliberately for one organisation still overrides the instance-wide value.
- **Creating a scheduled run always failed with "Schedule limit reached (0)".** Zero means unlimited everywhere else since capacity limits became the operator's to set, but this check read it as "allow none", so cron scheduling was unusable out of the box.
- **The hour between scheduled runs is now yours to set.** A schedule could not fire more often than hourly, whatever the hardware underneath — the last inherited capacity ceiling left in the code. It is a setting now, and 0 removes the floor.
- **Hexaly's configurable time limit now applies.** The setting has always been in the panel, and the solver ignored it in favour of a fixed 300 seconds — so on a solver that searches until told to stop, the one control over when it stops did nothing.

- **"Explain this model" and the version-diff explanation answer in your language.** Both were sent without the header that tells the server what you are reading in, so they came back in English however the app was set — while every other explanation honoured the locale.
- **A model written in JModel arrives in the list with a name.** The assistant already titled the models it wrote, but a source typed into the JModel lens stayed "Untitled Model" until you renamed it by hand — so a studio full of DSL models read as a column of identical rows. The project now takes the compiled model's name, and only while it is still untitled: a name you chose is never overwritten.
- **The multi-objective importer opens on your models**, not on the pre-fusion builder documents — which are empty for almost everyone, so the panel greeted you with "no builder documents found" while your models sat one tab over.
- **A marketplace model's success rate is a number again.** Nothing had written it since the marketplace and the studio became one entity: each solve bumped the run counter and stopped there, so every listing showed a dash where its reliability should be — beside a model with fourteen recorded runs. Failed runs now count too, which is what the rate needs to mean anything, and models published before the fix read 100% because a success was the only outcome the old counter recorded.
- **A model with no write-up shows its description instead of five empty tabs.** Overview, Features, How it Works, Example I/O and Changelog were rendered whether or not the publisher had filled them in, so a reader clicked through five panels of "no content added" to reach the description underneath. Only sections with content appear now.
- **The AI solution explanation no longer contradicts the analysis printed above it.** It was given only the LP-relaxation sensitivity, which prices a binding integer constraint at zero, so it reported a resource the solution had used right up to its limit as having spare capacity — while the exact analysis on the same page marked that row binding. The explanation now reads the exact, solution-based analysis for what binds, and treats shadow prices as approximate pricing rather than evidence.
- **Browsing quickly no longer signs you out.** The reverse proxy counted the session check the app makes on every page against the same ten-per-minute budget as login attempts, so after about ten pages you were thrown back to the sign-in screen — which was itself rate-limited, leaving you locked out of your own account until the minute elapsed. Session upkeep now runs on the general API budget; login, signup and password reset keep their own. The app also stops treating a throttled or failed session check as proof that you are signed out.
- **The platform admin console no longer shows up in every account's sidebar** — the menu was gated on owning an organisation, which everyone who signs up does, rather than on being a platform administrator. The pages themselves were never reachable: the server refused them and the app returned you to the studio.
- **A rate limit of 0 blocked every request** instead of allowing them all, so an administrator setting 0 to mean "no limit" would have locked their instance out.
- **The JModel grounding budget applied inconsistently** — two of its three checks read the built-in constant instead of the configured value.
- **The health check no longer freezes the server for 100 ms per call** — it sampled CPU usage in a way that sleeps mid-request, on the most-polled endpoint there is.
- **Viewing the canvas no longer counts as changing the model** — opening the canvas sub-lens locked the JModel editor read-only behind a "changed elsewhere" warning that was untrue.
- **A page reload no longer disarms the JModel stale lock** — a rehydrated source came back editable, so one keystroke could recompile an old source over a model last edited elsewhere.
- **The MCP discovery document advertised 26 tools** after the analysis tools landed. It is now generated from the server's own list and pinned by a test.
- **"Derive draft" recovers two constraint shapes it used to decline** — same-shape scalar constraints over one family, and per-constraint constant coefficients.
- **The grouped solution view is windowed rather than truncated** — a 7,200-variable solution renders in ~180 ms with everything reachable by scrolling, instead of capping at 500 values behind a "show all" that froze the page.

### Security

- **Refusing a solver no longer says which ones the server has.** Asking for a solver that does not exist and asking for one the server carries but cannot license produced different messages, so trying names revealed the commercial solvers a deployment holds — the solver list itself already hides them. Both now refuse identically; the real reason stays in the server log.
- **Next.js patched to 16.2.11**, closing seven advisories present in 16.2.9: SSRF via rewrites and via Server Actions, a middleware bypass in App Router, unauthenticated disclosure of internal Server Function endpoints, plus denial-of-service and cache-confusion issues.

---

## [3.1.0] - 2026-07-20

The analysis workbench: the post-solve page answers what the model decided and what
constrains it, and the JModel lens gains mathematical notation, AI generation and
recovery from flat models.

### Added

- **Structured solution view** — an assignment or routing solution used to render as a wall of `assign_v3_o107 = 1` rows because the flat solver output had thrown away the index structure. Variables now keep their family and indices end to end, and the execution page leads with a family → index grouping answering "what did the model decide?".
- **Exact, solution-based analysis** — a new Analysis section leads with facts that are exact for the integer solution and solver-agnostic: which constraints are binding, each constraint's slack and utilization, and which objective terms drive the value. LP-relaxation shadow prices are demoted to a collapsed "approximate" section.
- **The model as mathematical notation** — the JModel editor renders the source as symbolic math in a live pane, keeping sums and ∀-quantified families symbolic instead of flattening them into thousands of rows. No AI involved: it is a pure function of the parsed model.
- **Generate a JModel with AI, from a description or a screenshot** — a source is returned only when it verifiably compiles, because the compiler is the oracle. Screenshots and PDFs are read directly as vision input, so a photo of a formulation becomes editable JModel.
- **Derive a JModel draft from a flat model** — a canvas-built or imported model has no source, so the lens reconstructs a compact indexed one. Honest by construction: the draft is offered only when it recompiles to an equivalent problem, and declines clearly otherwise.
- **Per-model run history on the Solve tab**, listing the open project's executions.
- **Public documentation for the analysis workbench** — a new "Analyzing Results" page, plus updates to the JModel DSL and solution pages.

### Changed

- **Honest post-solve summary replaces the convergence chart** — the live gap chart was a flat line for essentially every real model, since solvers find a near-optimal incumbent immediately and then spend the run proving optimality. The page now states the outcome plainly ("proven optimal at the root node", "time limit — gap X%") with the final metrics.
- **The variable-values chart collapses identical bars** — dozens of bars all at 1.0 carry no information; the chart aggregates them and keeps the real chart when magnitudes vary.
- **The studio results drawer links out instead of cramming** the whole variable table and sensitivity analysis into a side sheet.
- **"Solve all" shows why it is busy** — compiling a large model server-side takes tens of seconds, during which the button was disabled with no explanation.
- **"Derive draft" recovers multi-family constraints and small models** — a 150×150 model (22,600 variables) de-grounds to a compact JModel in about 3 seconds.

### Fixed

- **The AI solution explainer no longer fails on large solves** — it embedded the full model and solution, so a 10,000-variable solve produced a prompt the API rejected. Each block is now bounded, keeping the objective exact.
- **A cancelled solve no longer leaves the "Solving…" pill spinning** when the cancel came from another tab or device.
- **The JSON model editor no longer crashes the studio page** — and no longer silently drops a variable added just before the crash, since the crash aborted the pending autosave.
- **Viewing the canvas no longer locks the JModel source read-only.**
- **The JModel lens explains why solve is blocked** after deselecting a dataset, instead of greying out the controls with no reason.
- **Marketplace and template executions carry the grouped-solution structure** — they were the one entry point that never annotated it, so their result page fell back to the flat table.
- **The exact-analysis endpoint no longer runs on the event loop**, where it stalled every in-flight request while re-parsing thousands of constraints.
- **"Generate with AI" survives an unexpected code-fence label, a text-less model reply, and picking more files than the attachment limit** (which used to drop the extras silently).
- **Solution explanations keep the top decisions** — the bounded prompt now samples the largest values by magnitude, as documented, instead of the first 200 in insertion order.
- **One AI-cost ledger per user, guaranteed** — two concurrent first generations could race and create duplicates. Enforced by a unique index.
- **MCP usage analytics survive a library upgrade** — the tool-call counter wrapped a private dispatch method and now degrades to "no analytics" instead of breaking every tool call.
- **Startup settings self-heal is race-safe** — booting several API workers at once made three of four fail on a primary-key conflict.
- **Switching a dataset in the JModel lens compiles once**, not twice.

---

## [3.0.0] - 2026-07-17

**The "Model, Analyze & Solve" release** — the repo's first tagged version. The model
becomes the platform's protagonist: one versioned **ModelProject** workspace (canvas, AI
assistant, JSON editor and JModel DSL as lenses over a single canonical model), git-style
commits, datasets and scenarios, live async solving, a fork-first collaborative
marketplace fused into the same entity, grounded AI explainers, and a 26-tool MCP surface
for agents. Money and credits are fully retired ([ADR-008](ARCHITECTURE/08-decisions/ADR-008-remove-monetization-and-credits.md)) —
fair use is rate limits plus solve caps.

### Added

- **"Model, Analyze & Solve" workspace and the first-class `ModelProject`** ([ADR-006](ARCHITECTURE/08-decisions/ADR-006-model-project-unification.md)) — one model built, analyzed and solved across Build · Analyze · Solve tabs, with git-style versioning, autosave and live model stats. MCP grows 19 → 26 tools.
- **JModel DSL editor** — a declarative modeling language (sets, params, indexed variable and constraint families, `sum{}`, filters) as a fourth lens. A 200×14 assignment model is about 12 lines instead of thousands of canvas nodes. Off by default behind a feature flag.
- **Scenarios: one model, many named datasets** — a JModel can declare its sets and params without values and fill them from a named dataset ("Q3 forecast", "+20% demand"), with a dataset editor, a table view, file import (AMPL `.dat`, CSV, JSON), live validation against the model's declarations, and side-by-side comparison of N scenarios in one click.
- **JModel language features** — tuple sets for sparse routing-style models, integer ranges (`1..96`), set operators (`union`, `diff`, `cross`), quadratic terms compiling to QP/MIQP, and compile-time conditional expressions.
- **AI Assistant lens** — build a model by chatting in the studio and refine it incrementally, with RAG grounding, file attachments, and generation that survives switching tabs.
- **Explain a model and a version diff with AI** — Python computes the facts, the model only narrates them.
- **Infeasibility explainer** — an infeasible solve computes a minimal conflicting set (IIS) solver-agnostically and explains it in plain language.
- **Solution explainer and sensitivity analysis** — per-variable reduced costs alongside shadow prices, with a grounded explanation of the result.
- **Bring your own Anthropic key** — an organization can run every AI feature on its own account. The key is encrypted at rest and never returned or logged.
- **Agents can author models end-to-end over MCP** — an external agent can write a versioned model, not just create, commit and solve it. Solve tools accept a compact response that omits near-zero variables.
- **Import and export across every model surface** — MPS, LP, CIP, SOL, CSV and JSON; every solve records its provenance.
- **Editor lens** — edit the model as JSON text; valid edits reflect on the canvas and autosave, invalid JSON blocks solve and commit.
- **Archive, restore and permanently delete models**, with an org-wide model list, creator attribution and bulk cleanup.
- **RAG grounding for the assistant** — Qdrant plus local sentence-transformers, including a worked-example formulation per template and an optional reranker. All local: no data leaves the box.
- **Modular monolith foundation and the solver domain** — `app/domains/` with import-linter enforcing the boundaries, the solver extracted as the first bounded context (ADR-004), and a `SolverAdapter` Protocol with capabilities and a registry keeping SCIP inside its adapter.
- **Templates and generators** — 102 templates across 34 unified YAML files and 27 problem generators, including a multi-depot pickup-and-delivery generator with time windows.
- **Read-only organization overview for admins**, and 24 monitoring alert rules with email delivery.

### Changed

- **One model entity: the marketplace fused into the studio** — the split between catalog models, activated models and studio projects is gone. A listing is a facet of a ModelProject, and using a marketplace model means forking it into your studio. Old marketplace and model ids keep resolving.
- **"Sellers" are now authors** — with money gone, the platform speaks of authors who publish and share models, measured by adoption. Author profiles moved to `/marketplace/authors/{org}`, with the old paths redirecting.
- **Every solve rides one async pipeline** ([ADR-007](ARCHITECTURE/08-decisions/ADR-007-async-only-executions.md)) — `/solve`, templates, imports, project solves and multi-objective all execute through it, each keeping its exact synchronous contract and degrading to `202 + task_id` when a solve outlives the wait budget. No more solves dying at proxy timeouts.
- **`?wait=true` on the async solve** returns the classic synchronous result directly, for ERP and MCP callers who just want the answer.
- **Execution and usage limits relaxed for self-hosting** — solve time cap 1 h → 24 h, request body 1 MB → 50 MB, quotas and AI budget loosened. Auth rate limits and the login lockout unchanged.
- **All platform timestamps are timezone-aware UTC** — every stored column is `timestamptz` and API responses carry an explicit offset.
- **Variable views hide zero values by default** — a large solution is mostly zeros, which buried the variables carrying the answer. Each view has a toggle and a shown/total count, so nothing is hidden silently.
- **Terms and Privacy rewritten for the open-source model** (five locales): hosted jaot.io is free, self-hosting is Apache 2.0.
- **Solver upgraded to SCIP 10.0.2**, and dependencies swept to latest stable.

### Removed

- **The paid marketplace and the entire credit system** ([ADR-008](ARCHITECTURE/08-decisions/ADR-008-remove-monetization-and-credits.md)) — billing, invoices, seller earnings, withdrawals, featured placements and credits are gone. Every solve and assistant message is free; fair use is enforced by rate limits, a daily solve quota, per-solve caps and a monthly budget for the AI assistant.
- **The legacy "activate" flow and the separate organization-model entity** — replaced by forking a listing into your studio.

### Fixed

- **A finishing async solve could briefly report a false "Solve failed"** — the status endpoint could return `completed` with no result payload during the final progress tick, which every consumer could hit.
- **Large models could not be solved** — the expression-length cap and the free-plan variable limit both rejected big imported models before they reached the solver.
- **A burst of large solves froze the whole API** — the async-solve and validate handlers did CPU-bound work on the event loop.
- **Large solves died with an opaque 500** — the expression parser rebuilt its variable-name set for every expression, making a 100,000-constraint model cost minutes of CPU. Routing a 200×200 scenario went from over two minutes to 2.8 seconds.
- **Times were shown one timezone off** — API timestamps were parsed as local time, so every displayed date sat hours in the past.
- **Execution history could show another organization's model name** — the name lookup is now organization-scoped.
- **655 broken translations repaired** — missing Spanish tildes, a corrupted Catalan block, an accent-less French batch, and German words whose umlauts had been truncated.
- **A pre-merge review fixed 15 further defects**, including two solve routes missing the maintenance gate, unlocked read-then-write on cancel (a user cancel racing the worker could discard a computed solution), and a compiler rejecting valid models over floating-point residues.
- **The announcement banner meets WCAG AA contrast**, and the printable execution report is honest about being HTML rather than a PDF.
- **Importing a large model no longer freezes the browser** — a model past the canvas scale cap hydrates directly from JSON.
- **Durable solve sessions** — a running solve survives reload, a duplicated tab, another device or power loss.

---

## [2.8.0] - 2026-02-19

Invoices, SLA and health monitoring.

### Added

- **Invoice system** — automatic invoice generation for subscriptions and credit top-ups; `Invoice` model with line items (JSON), totals, tax, Stripe refs; HTML rendering for print-to-PDF; `GET /billing/invoices`, `GET /billing/invoices/{id}`, `GET /billing/invoices/{id}/html`; 35 tests.
- **SLA document** — `docs/operations/SLA.md` with uptime targets (99.0%–99.95%), service credits, incident response times, rate limits, data retention, support tiers.
- **Health status endpoint** — `GET /api/v2/health/status` with component checks (database connectivity + latency, SCIP solver, memory, disk); returns healthy/degraded/down status for SLA monitoring.
- **Alembic migration** — `invoices` table with indexes on `invoice_number` and `organization_id`.

---

## [2.7.0] - 2026-02-19

Billing, templates, deployment and testing.

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
- Only 3.0.0 onwards is tagged in this repository — it is the first release published
  here — so the comparison links below start there.

[Unreleased]: https://github.com/avallavall/jaot/compare/v3.1.0...HEAD
[3.1.0]: https://github.com/avallavall/jaot/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/avallavall/jaot/releases/tag/v3.0.0
