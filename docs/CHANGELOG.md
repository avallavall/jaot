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

### Changed

- **The home page opens with a real optimization instead of a screenshot.** The hero replays an actual solver run: a 24-stop route that improves 68.5% from its first answer to the proven optimum, with the gap closing to 0.00%. Every figure on it comes from the solver, and it still reads with JavaScript off or motion reduced.

### Fixed

- **The front page no longer advertises the retired visual builder.** Its hero image and caption still offered the builder as a way into the product, months after it was retired everywhere else.

## [3.3.0] - 2026-08-04

### Changed

- **The README covers what the platform actually does today.** It still described a visual builder that was retired months ago, and undercounted the problem generators. It now also states what you need before installing, how to point an AI agent at the instance over MCP, and how to run the tests and linters.

### Removed

- **The last door to the retired visual builder.** An API endpoint that converted an old builder document into a studio project had no caller left anywhere — the builder area itself was retired months ago. Audited on the reference install before removal: of the ten documents it could still have rescued, nine were empty shells and the one real model dates from June, before the studio replaced the builder.

## [3.2.0] - 2026-08-03

### Added

- **Two model classes the catalog was missing.** *Period selection* places items into periods under per-period capacity: it now powers the mine planning card (net present value with block precedence, plant capacity and a minimum ore grade per period), the forest harvest card (area caps, adjacency between neighboring stands, discounting) and the track maintenance card (every section into a possession window before its safety deadline). *Network design* buys candidate edges so the network survives any single link failure — the redundancy card returns a cheapest two-connected build instead of a zero.
- **What-if analysis by real re-solves** — the analysis panel can now answer "what would one more unit actually buy me?" by perturbing the solved model and solving it again: RHS ranging on the top binding constraints (read as a tornado chart) and decision regret (what it costs to overrule a binary decision). Every number is measured on the real MIP, not on an LP relaxation. Runs on the solver queue under a configurable budget; partial results are labelled, never padded.
- **"Explain this to me" on the what-if analysis** — the assistant reads the measured scenarios back in plain business language, and is constrained to the scenarios that actually ran. Opt-in and cached per execution.
- **Advanced-model toggle on every AI surface** — both chats, the three explainers, "Generate with AI", "Explain this model" and the version-diff explanation. Off by default and remembered per user, since the advanced model costs more per call.
- **The assistant answers in your language** — chat replies and every explanation now follow the locale you are browsing in, across all five languages. Identifiers (variable, constraint and set names, expressions, JModel source) are quoted exactly, so explanations still match the screen.
- **Solvers declare what they cannot do** — `GET /solvers/available` reports each solver's capabilities and the interface acts on them: the picker names what your choice will not give you before you solve, and the Sensitivity and Live Solve panels say the solver computes no shadow prices or streams no progress instead of appearing to fail.
- **Analysis tools over MCP (26 → 30)** — agents can now ask what is saturated, why a model is infeasible, and what one more unit of a limit is worth. The plain-language explainers stay out by design: an MCP client is already a language model.
- **Family-level KPIs in the post-solve analysis** — the exact analysis aggregates by constraint family (share of binding rows, slack, utilization) and by variable family, so a 10,000-row model reads like a ten-line summary.
- **A home for what you publish** — "What I Publish" collects an author's listings, how they are being found and adopted, and the reviews people left, in one place under the workspace. It is written for the first week as much as the thousandth: with little traffic it says what it knows in a sentence instead of drawing a chart of one colour, and it never presents a partial figure as a total.
- **Take a listing down, and put it back** — a published model can be withdrawn from the marketplace and restored later. Withdrawing keeps its adoptions, runs and rating, so restoring is one click; models other people already adopted are unaffected, because adopting copies the model rather than pointing at the listing.
- **Ask for the verified badge** — the request, the admin review queue and the badge all existed, but nothing let an author actually ask. The request button now sits on the organisation profile, where the badge status is shown.
- **Reviews you received, in one list** — reviews used to be readable only one model at a time, on each model's public page.
- **Public roadmap** — `docs/ROADMAP.md`, linked from the README. The frozen JModel grammar now ships as `docs/JMODEL_GRAMMAR.md`.
- **Connection-pool metrics on `/metrics`** — the database pool now reports how many connections are in use against its ceiling, with alerts before saturation. Previously the only sign of a full pool was requests starting to fail.
- **Automate a model you actually built** — a trigger can now fire a model from the studio, pinned to one of its committed versions. Until now a trigger could only point at a document from the old visual builder, which the studio does not create, so nothing built since the studio became the place you build models could be automated at all. Triggers made before this keep working and firing exactly what they always did.

### Changed

- **Lot sizing prices production against the demand still ahead.** The setup linking constant declines over the horizon instead of sitting at total demand for every period — same model size, same optimum, and measurably less for the solver to prove (root bound 3675 → 5968 on the reference instance).
- **The Sensitivity tab now holds the sensitivity analysis.** The what-if — the one that re-solves your model to measure what a unit of headroom is really worth — sat at the bottom of the Results tab, below five other sections, while the tab named Sensitivity showed only the LP-relaxation shadow prices. The what-if now opens that tab, with the shadow prices underneath as the approximation they are.
- **The same shadow prices no longer appear three times on one page.** They were listed in the Sensitivity tab, again inside the solution explorer, and again at the foot of the analysis — the middle copy untruncated, so a 685-constraint model printed all 685 rows there. One list remains, in the Sensitivity tab.
- **Comparing two runs no longer means typing their ids.** The side-by-side comparison of two executions was a finished screen with nothing linking to it: the only way in was pasting two ids into a text box on the analytics page. Pick two rows in the executions list instead. Multi-objective solving and custom solve were in the same position — complete pages nobody could reach — and now have their own entries in the sidebar.
- **JModel is part of the product, not an option.** The declarative editor, the Datasets tab and scenario runs shipped behind a switch that was off by default, from when the compiler was brand new. Every fresh install therefore started with no Datasets tab and no scenarios, and nothing on screen said why. The switch is gone: all three are simply there.
- **The template list is paged, and lighter.** It returned all 102 templates in one 90 KB response; the long descriptions alone were 59% of that, and the detail endpoint already serves them. Listings now carry the short description and come 25 at a time (`page` / `page_size`, up to 200), which takes a first listing from about 22,600 tokens to 2,900 for an assistant browsing what exists.
- **Validating a model reports every problem at once.** It stopped at the first one, so fixing a hand-written model cost a round trip per mistake — and while you were looking at the objective, nothing said the constraints and the bounds were wrong too.
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
- **A derived JModel says why it came out long.** Deriving a draft from a model with no indexed structure writes one line per variable, which is correct but reads like a wall — and nothing told you whether that was inherent to your model or something you could change. Usually it is the naming: an index needs a separator, so `x_1` reads as a family and `x1` is one whole name. The draft now says so, and which names to rename, but only when several variables share a prefix — a lone `co2` is a name, not a family missing an underscore. When the blocker is structural instead — say one variable of a family with a different bound than its siblings — the draft names that.
- **The API documents what it returns.** Forty-four endpoints answered with an undeclared object, so the reference described them as "any JSON" and generated clients had to guess — including the solve queue, the template catalogue and most of the admin surface. All of them now publish their response schema, which is what the generated TypeScript client and the OpenAPI reference are built from.
- **The author endpoints are named after authors.** ⚠️ **Breaking:** `/api/v2/seller/*` is now `/api/v2/author/*`, the admin route is `/admin/marketplace/author-analytics`, and its `sellers` response key is `authors`. There is no alias — the old paths return 404. Selling stopped existing when billing was removed; the surface kept the word for two releases. Anything generated from our OpenAPI schema picks this up by regenerating.
- **The model list says what is published.** Each row now carries whether it is on the marketplace, so you no longer have to open a model, or the marketplace itself, to find out.
- **One set of request limits for the instance.** The per-minute and per-day limits were the last thing decided per organisation: the numbers were copied onto each organisation when it signed up, so editing them in the admin panel changed what the *next* organisation would get and nothing about the ones already there. They are now read from settings on every request — an edit applies everywhere, immediately, including to organisations created years earlier.

### Removed

- **Twenty-three settings that changed nothing.** Some had no reader at all — a gzip threshold the server hardcoded past, two metrics counters, four ID prefixes, both rate-limit windows. Others the panel let you edit while the value was really taken from the environment file: bind host, port, worker count, the Celery retry settings and the database URL. Each one looked like a working control.
- **`LLM_THINKING_BUDGET_TOKENS`**, deprecated last release in favour of `LLM_THINKING_EFFORT`.
- **The plan-tier editor.** Instance limits are ordinary settings now, so the tier table and the loose fields no longer render the same values twice on one tab.
- **The solver "Pool Size" setting.** It configured a thread pool that nothing builds — the pool existed for the in-request solves that moved to the queue a release ago, and no code has asked for it since. The panel offered the control anyway, down to a help text explaining when a change would take effect.
- **Ninety-eight settings rows left behind by billing, the paid tiers and last release's clean-up.** Code had stopped reading them long ago but nothing deleted them, so the table held twice what the panel could show. Anyone querying the database directly now sees exactly the settings that exist.
- **The plan label.** An organisation's "plan" stopped deciding anything when billing was removed and the four tiers became one instance-wide profile — it survived as a word printed on badges, in the sidebar and on the admin list, and as a field you could pick at signup that changed nothing. It is gone from the interface and from the API: what an organisation may do is decided in one place, and no longer looks like it depends on which tier it is on. Per-organisation request limits went with it — the admin pages no longer show two numbers that are not the ones being enforced.
- **The pre-fusion marketplace tables.** The two tables a model used to be split across, and the columns pointing at them, were replaced a while ago by a single model with a marketplace facet — but they stayed in the database, empty, alongside six columns left by billing. They are gone. Older runs keep the reference that identifies which model they came from, so nothing disappears from your history. **This one changes the database irreversibly:** rolling back to a previous release restores the code, not the tables.

### Fixed

- **Solve analytics reads honestly on a first day, not just after thousands of runs.** A success rate over a handful of executions shows as the plain ratio ("5/6") instead of a one-decimal percentage, a distribution where every run shares one status reads as a sentence instead of a donut of a single colour, and one or two days of activity say so instead of posing as a trend — the same quiet-when-sparse rule the author area already follows.
- **The maximum-flow card now proves its answer.** It shipped zero costs and a supply equal to the known result, so the model merely verified that value and reported an optimal cost of 0. The objective now is the flow itself, demonstrated by the solver against loose bounds.
- **Cutting stock enumerates every maximal pattern**, not single-item shapes plus one arbitrary pair — its "optimal" is the true optimum at catalog scale, and if an instance ever exceeds the enumeration cap the answer says the pattern set was truncated instead of staying silent.
- **A covering model with an uncoverable element refuses instead of approving.** It used to skip that element's requirement and answer "optimal" with the element uncovered — the one thing a covering model exists to prevent.
- **The food production-line and dye-batch cards read their own numbers.** Production lines were not a recognized resource list, their available hours defaulted to 40 and every job to 8 hours — so budgets and durations the cards shipped were silently replaced by defaults. The line card's description also no longer promises changeover sequencing the model does not do.
- **A mixed fleet no longer plans around its smallest vehicle.** In vehicle routing, the subtour bookkeeping used each vehicle's own capacity as a safety margin over customer pairs it never visits, so one small van in the fleet silently capped every truck's route at the van's capacity — a trivially feasible delivery plan came back infeasible. Nothing held a vehicle to its own capacity either, only to the fleet's largest. Both fixed; single-type fleets behave exactly as before.
- **Six scheduling cards now schedule.** Their single-list inputs (forest stands, mine blocks, trial phases, renovation tasks…) were fed to both sides of a worker-to-shift assignment, so the served model assigned the list to itself and answered nothing the card asked. They now plan start times — and honestly: crew limits are real constraints and declared task dependencies are honored. The renovation example answers a ten-day plan (nine of critical path, one more for the three-crew limit) instead of "everything starts at once, done in five".
- **Three blending cards priced their blend at zero.** Per-litre and per-tonne costs went unread — buying was free — and the batch or tonnage target only capped the mix, so producing nothing satisfied every quality spec. The ore card now answers a real cheapest blend meeting its iron, silica and moisture specifications.
- **The timber transport card moved nothing and called it optimal.** Once its routes were recognized, the depot and mill lists were thrown away and every supply read as zero. Networks with more supply than demand were also infeasible outright; sources may now keep their surplus.
- **Two inventory cards answered a total cost of zero.** Their SKU lists fell through to a single-item reader that found no demand at all. Multi-item lot sizing is real now — per-SKU ordering, whole batches where declared, and a shared-reactors limit — and the batch-planning example carries opening stock, without which its own first week was impossible on two reactors.
- **A variable with digits mid-name no longer breaks the solve.** A name like "aspirin_500mg" was rewritten as an implicit multiplication ("500*mg") and the model failed on a variable it never declared.
- **Supplier and material names that extend each other stay apart.** Procurement matched rows by name prefix and suffix, so material "steel" absorbed every "stainless_steel" purchase and a supplier's capacity was consumed by its namesakes.
- **Talking to the server over MCP survives a pause.** The protocol handshake issued a session that lived inside one worker process, so on a deployment with several workers a client's next request usually landed on a worker that had never heard of it and was refused — measured at three failures out of four, invisible in back-to-back calls because keep-alive pins a connection to one worker. Sessions are gone: every MCP request is complete in itself, and a client still sending its old session id is simply accepted.
- **Validating a model catches what the solver would reject.** An expression with no right-hand side, a doubled comparison operator or an unclosed parenthesis came back "valid, 0 errors" — and the solve then failed on the very expression validation had approved. Every expression is now parsed exactly the way the solvers parse it, so a green validation means the model will build.
- **A mistyped argument is an error, not a silent success.** Writing a project draft with a wrongly named field returned the project as if it had saved — and saved nothing, so the follow-up commit sealed an empty model. The write requests of the agent-facing tools now reject unknown fields with a validation error that names them.
- **No more −1e+99 served as a shadow price.** When the solver has no dual value to give for a row — two constraints sharing one name is one way to get there — it answers with an internal sentinel, and that number was published as a price, poisoning the derived reduced costs with it. Sensitivity now reports no value rather than an impossible one.
- **An account can actually be deleted.** Removing an organization tripped over its own API keys with a database error, and an audit found seventeen more references across the schema that would block the same deletion. Everything that is the account's data now dies with it; work created for the organization outlives its creator, unattributed.
- **Reduced costs and shadow prices no longer contradict each other.** They sit side by side on the Sensitivity tab and answer the same question from two sides, so they have to add up. When a capacity was written as a constraint rather than as a variable bound, SCIP charged that price twice — once as the constraint's shadow price and again as the variable's reduced cost — while HiGHS reported the same model correctly, so the answer depended on which solver you picked. The reduced cost is now the one your shadow prices imply, whichever solver ran. Runs recorded before this keep the numbers they were given.
- **Three marketplace cards that could not be used are no longer listed.** Demo Logistics, Demo Finance and Demo Manufacturing carried no model at all — no example, no input form, no version — so pressing "use this model" returned an error instead of a workspace. Every one of the 104 cards on the marketplace now opens into a working model.
- **Publishing an adopted model no longer tells you to do something you already did.** A model adopted from the marketplace may only be listed once you commit a change of your own. That refusal was reported as "commit your model, then come back" — to authors who had committed. The rule is now explained up front, before you fill in the listing form, and the two refusals no longer share one message.
- **The triggers page no longer breaks when a trigger fires a studio model.** Automating a model built in the studio became possible in this same release, and the trigger list crashed to an error screen as soon as one existed. The trigger's own page also left "Model" and "Pinned version" blank for those, so it never named what it fires.
- **The two analysis panels agree on which constraints are binding.** One counted a constraint as binding when it sat on its limit; the other when its shadow price was non-zero. Those are not the same question — an optimum can hold a constraint tight and still price it at zero — so the same run was reported as *0 of 21 binding* on one panel and *13 of 21* on the other. Binding now means zero slack everywhere, including for models with integer variables, where it is read from your actual solution rather than from the relaxed problem the shadow prices come from. Runs solved before this update keep the numbers they were saved with; re-solve to refresh them.
- **A tight strict inequality reads as binding.** A constraint written with `<` or `>` and resting exactly on its limit was reported as having slack, because the tolerance and the strictness margin were the same number.
- **The welcome tour shows Triggers.** It hands new accounts a map of the sidebar and left that one out, from back when triggers could not fire a studio model.
- **A trigger pinned to a version with no model says so.** It reported a validation failure listing missing fields instead, sending the operator to debug overrides for a version that has no content.
- **An infeasible run says why it has no sensitivity data.** The Sensitivity tab answered "no sensitivity data available for this execution", which reads like a fault. A model with no feasible solution has no optimum to price, so shadow prices cannot exist for it — the tab now says that, and points at the infeasibility analysis that does explain the run.
- **One review per person per model, enforced.** The rule was checked before writing, but nothing stopped two simultaneous posts from both getting through — the database constraint meant to catch that had quietly stopped applying when models were unified. Duplicates left behind are cleaned up on upgrade, keeping the most recent review of each pair.
- **A busy server now fails fast instead of stalling.** The API would accept four times more concurrent work than its database connections could serve; requests beyond that waited thirty seconds and then errored, and the container health check waited in the same queue — so a slow server was restarted for being unresponsive, moving its load onto the others. Concurrency is now matched to the connections available, the wait is five seconds, and the health check no longer queues behind ordinary traffic.

- **Analytics name where a run came from.** The origin chart knew two of the nine channels a solve can arrive through, so it labelled everything that was not "manual" as "Automatic" — three identical grey entries in one legend, and a wrong word for runs launched by hand from the studio. Every origin now has its own name and colour, matching the badge on the executions list, and the origin filter offers all of them instead of seven.
- **The visual canvas no longer rewrites models it cannot read.** A constraint with variables on both sides or arithmetic among constants — how an AI-written cash-flow model is phrased — was silently reduced to an empty `0 <= 0` row when drawn as nodes, and the drawing then became the model everything else worked from. The canvas now reads general linear constraints exactly, withholds a model it cannot hold exactly (with a notice, like the too-large case), and discards a stored drawing that no longer matches its model instead of trusting it.
- **"Derive draft" tells the truth when it declines.** Every decline — including plain network errors — was reported as "this model has no indexed structure to recover", which was often false. The message now states the actual reason, and a failed request reads as a failure, not as a verdict about your model.
- **The reported-reviews queue opens again.** The moderation page read three fields the server has never sent — among them a per-review report counter that does not exist in the data — and threw while rendering the first flagged review, so the queue was unusable the moment it had anything in it. It now shows the reason the review was reported and whether it is currently visible, which is what the hide/show control acts on; before, that control only ever went one way.
- **Polling a running execution no longer reports a false finish.** While a model solves, its last progress tick says "completed" a moment before the run actually returns, and that word was leaking into the answer — so a client polling in that window read a finished run with no result and reported a failure. The same fault was fixed on the solve endpoint after a live incident; its twin on the model-execution endpoint had kept the bug.
- **Opening a saved model shows the whole model.** The canvas framed itself once, before the model had loaded, so it sized the view to the single empty node that was there and magnified it to the maximum. A model arriving a moment later inherited that zoom and nothing corrected it: a twenty-variable model opened showing two boxes and a lot of empty space. It now frames what actually loaded, and no longer magnifies a nearly empty canvas.
- **The bell now rings when a solve finishes.** The notification a completed or failed model run should leave was written and then discarded with the worker's session, on every run since the feature existed. Failed runs had a second silencer: naming the model read a field the model does not have. And the panel itself never asked — it looked for an API key in browser storage, which a normal sign-in does not leave, so the bell stayed empty and silent no matter what had arrived. All three fixed: the notifications are stored, both kinds are sent, and the bell shows them.
- **The "Recent" tab fills up again.** Opening a model left no trace — nothing ever wrote that list — so it greeted every account with an empty state next to a Favourites tab that worked. Opening a model's page now records it, and opening it again moves it to the top instead of adding a second entry.
- **Author analytics count the visits they receive.** Views and impressions were recorded on every marketplace page and then thrown away when the request ended, so a listing with real traffic reported zeros to its author. Both are stored now, and a visit from a signed-in reader is again attributed to their organisation.
- **Author analytics count readers, not our own servers.** Once those events were stored, almost all of them turned out to be ours: the sitemap generator walks the whole catalogue every hour, and each walk banked one impression per listing — 97.8% of every impression on the reference install. The detail page also fetches its own data server-side to build its metadata, so each visit was counted twice, once without a country or an organisation. Neither is a reader, and neither is counted now.
- **Solve analytics answer in a fifth of a second instead of sixteen.** The screen aggregates six columns, but the query loaded whole execution rows — and an execution carries its problem and solution, so counting statuses pulled 96 MB across the wire on the reference install. Same figures, 70× faster, and no more staring at a skeleton wondering whether the page is broken.
- **A solve you start from the studio tells you when it finishes.** Only runs of a marketplace model left a notification; every other path — including the studio, where most solves start, and multi-objective runs — showed its toast and left the bell empty. They all report through the same writer now.
- **Shadow prices are the ones your model actually has.** On the default solver, a constraint's shadow price could come back as zero — "relaxing this limit is worth nothing" — when it was worth a great deal, and the figure was presented as exact. The cause was a presolving setting that let the solver answer the question without ever solving the underlying linear program, leaving nothing to read the prices from. On the reference example every price was zero where the true answer prices the optimum exactly; now they do. The same applied to the approximate prices shown for models with whole-number decisions.
- **Watching a solve no longer ties up a database connection for as long as it runs.** The live-progress panel held one connection, and an open transaction, from the moment it opened until the run ended — so a handful of people watching the same long solve could use up the server's connections and stall everyone else, with the database otherwise idle. It now reads the run's state once per update and hands the connection straight back.
- **The marketplace category filter covers the catalogue.** It listed only the categories of the models on screen, so page two offered a different set and most of the catalogue could not be filtered by category at all.
- **A review now reaches the author.** Adopting someone's model notified them; reviewing it did not, though the notification type had been there all along.
- **Confirmation dialogs speak your language.** Every dialog in the app rendered "Accept" and "Cancel" in English under a translated message, in all five locales — as did the enabled/disabled badge on a trigger, which built its past tense by adding a "d" to the verb ("Activard" in Spanish).
- **Workspace tables fit on a phone.** They pushed the whole page ~120px wider than the screen instead of scrolling inside their own frame.
- **The German homepage headline stays inside the page.** It also spelled the compound wrong.
- **Two leftovers from the removed billing layer.** The admin model list declared a "Cost" column with nothing behind it, which shifted every row one column left and left Actions empty; the admin executions page kept a credits tile with no content, rendering an icon in an empty card.
- **A public profile stops linking to models that are gone.** The reviews listed on someone's profile each link to the model reviewed, and a withdrawn one was rendered as "Unknown Model" with the dead link still attached. Those rows now drop out entirely.
- **Escape cancels a model rename instead of saving it.** Pressing Escape while editing the name in the studio header committed the typed text to the server — the opposite of what it promises. Leaving the field empty no longer blanks it on screen either; it restores the name the model actually has.
- **An execution page finishes on its own.** Opening a run that was still solving — exactly what the list's "View" button offers on a pending row — left the page frozen on "pending" until you thought to refresh by hand. It now follows the run to its end.
- **The execution list can filter by every status it displays.** Cancelled and timed-out runs appeared in the table with no way to filter for them; the status names in the filter, the detail page and the analytics donut all read in your language now, rather than as the raw English value.
- **Smaller wording leftovers.** The version diff printed an untranslated duplicate line for a changed objective ("objective objective"); the execution comparison and the admin platform breadcrumb were part English; and "Member since" gave the month in English on every profile.
- **The automatic analysis of a solve reads in your language.** Its findings were written server-side in English and shown as-is under a translated heading. Each one now carries an identifier the interface renders in your locale, numbers and percentages included; the English text stays on the API and MCP responses, which is where it belongs.
- **The printable report stays printable on a real model.** It listed every constraint with its full expression, so a routing model with tens of thousands of rows — expressions running to thousands of characters each — produced a document hundreds of thousands of pixels tall. Constraints are now capped and long expressions trimmed, as the variables table already was, and the report says what it left out.
- **An execution page names its model and its solver.** Both showed "—": the detail endpoint never resolved the model name the list resolves, and it did not serve the solver at all — the screen was showing a hardcoded default. The report generated from that page inherited both blanks.
- **Signing in takes you where you were going.** Opening a protected page while signed out sent you to the login screen and then, once in, to the dashboard — never to the page you had asked for. The destination now travels with you, and only ever as a path on this site.
- **Emails arrive in the language you signed up in.** The welcome sequence had been translated into seventeen languages for months and every message went out in English, because nothing recorded a language when the account was created. Signing up now remembers it, and the verification and password-reset emails follow it too.
- **The "add a logo" step goes to the listing that needs one.** It linked back to the page the checklist itself is on, leaving you to work out which of your listings it meant.
- **Two things that overflowed a phone screen.** The MCP badge on the homepage could not wrap, and the toast stack sized itself wider than the viewport; both dragged the whole page into horizontal scroll.
- **Notifications read in your language.** The bell and its pop-up toast showed the English sentence the server had stored — "Execution Completed", "Model adopted" — under a fully translated panel. They are now written from what happened, in your locale, with the objective value in your notation. Anything the interface has no wording for still shows exactly what the server said, rather than nothing.
- **Sign-in, verification, password reset and invitations explain themselves in your language.** All four printed the API's English error text. Each failure now travels with a name the interface translates — including how many minutes a locked account has left — and the English text is still sent, unchanged, for API clients.
- **Admin feature analytics is translated.** The filters, tiles, chart, adoption table, funnel, country chart and event log were all in English under a translated heading, and event types read as their raw wire names ("Solver Solve", "Marketplace Activate"). The funnel also counted "1 users".
- **The what-if analysis counts as it goes.** A batch of scenarios can run for minutes and showed one unchanging sentence for all of it — indistinguishable from a hang. It now reports "8 of 20 solved" while it works.
- **A deployment can no longer refuse a live-progress socket from its own interface.** The origin allow-list did not implicitly include the address the app is served from, so a misconfigured list silently killed live solve progress: the handshake is refused before the upgrade, so the browser sees a bare 403 and the panel falls back to polling while the text still promises live updates.
- **One public profile per author.** An organization had two: the marketplace author page and a second, separately written one that counted different things, so the same author read differently depending on which link you followed. The older route now leads to the canonical page, and "preview my public profile" stops opening a 404 — it was addressing the profile by slug where the page expects an id.
- **Favourite a model from its own page.** The control only existed on the cards in the lists, so marking a model you were reading meant going back to a list and finding it again.
- **Favourites and Recently opened stop offering pages that are gone.** Both listed a model by the existence of its listing row, which was the same thing as "it is on the marketplace" only while withdrawing deleted that row. A withdrawn or unlisted model now drops off both lists and comes back if it is published again — the favourite itself is never lost.
- **Author analytics count visitors as visitors.** The "where your visitors are" breakdown was built from every recorded event, and impressions outnumber visits by roughly thirty to one, so the countries added up to far more than the visit total shown beside them.
- **The audit log distinguishes publishing from withdrawing.** Both were recorded as a generic model edit, so "when did this leave the marketplace, and who took it off?" had no answer in the log.
- **The author checklist links somewhere.** All three steps pointed at pages that either never existed or did not hold what the step asks for, so following the checklist meant hitting a 404 twice. The steps were also never rendered anywhere; they are now, and each one links to the page that completes it.
- **The profile stops sending you to support for the badge.** It said to contact support to request verification, which had not been the way to get it — and is certainly not now that the request button sits directly below that sentence.
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

- **A request can no longer choose the address it is rate-limited by.** Every per-IP limit — the anonymous one, login attempts, sign-up, the contact form — plus the address written to the audit log, read the first entry of `X-Forwarded-For`. Proxies *append* to that header, so the first entry is whatever the caller wrote there: sending a different one per request handed out a fresh allowance each time, which mattered most on the limit that throttles password attempts. The server now takes the address from a header its own proxy overwrites, and treats `X-Forwarded-For` as a last resort for deployments that have neither.
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
