# ADR-006 — `ModelProject`: a single first-class model entity (full fusion)

- **Status:** Accepted (2026-06-28)
- **Spans:** the "Model, Analyze & Solve" hub work (multi-phase; see the implementation plan).
- **Supersedes (partially):** the "leave marketplace model IDs as raw UUIDs" decision — reconciled
  below in *Consequences → Identity strategy*.
- **Related:** ADR-001 (modular monolith, feature-led), the execution-provenance migration
  (`source_kind`/`source_id`), and the solve-contract-drift invariant (all solves go through one
  orchestrator).

## Context

The platform's model-building capabilities grew as **independent screens** — an AI assistant, a visual
(ReactFlow) builder, a file importer, a templates gallery, a marketplace, an executions history — each
with its own state and no shared identity for "the model". Two parallel persistence concepts emerged:

- **`ModelBuilderDocument`** — the *authoring* object (`canvas_json` + `model_json`), with a
  canvas-centric version-snapshot service (diff/restore, auto-pruned checkpoints).
- **`OrganizationModel`** / **`ModelCatalog`** — the *distribution + runtime* objects (marketplace
  activation, runtime config, reviews; raw-UUID identifiers).

A user's "model" therefore had **two bodies** with two IDs and two detail surfaces. That split is the
root cause of a fragmented experience ("which screen do I run this from?") and of duplicated logic. It
also blocks the product's north star: **make the model itself the protagonist — one object you build,
analyze and improve step by step, with a history of how it changed and why.**

A codebase review confirmed that ~80% of the needed substrate already exists (builder documents with
both representations, a version-snapshot service, execution provenance threaded through every solve
path, model import/export to MPS/LP/CIP/JSON, BYOK LLM explainers). The work is primarily
**unification + a single identity**, not a green-field rebuild — provided we avoid two well-known traps:
a *parallel* entity that fragments versions/provenance, and a *bespoke modeling language* that becomes
an open-ended research project.

## Decision

1. **Introduce `ModelProject` as the single, first-class "Model" entity** (user-facing noun: **Model**;
   code name: `ModelProject`, prefixed IDs `mp_` / versions `mpv_`). It owns:
   - a **mutable HEAD draft** (the working tree: `draft_model_json` + `draft_canvas_json` +
     `draft_dsl_source` + a content hash + an optimistic-concurrency lock), and
   - an append-only list of **immutable, commit-grade versions** (`ModelProjectVersion`): full
     snapshots of all three representations + a **required commit message** ("what changed") + an
     optional body ("why") + author + `parent_version_id` + a frozen stats/`problem_class` snapshot.
   - Autosave writes the draft; **only an explicit, message-bearing commit creates a version row.**
     `content_hash` de-duplication makes a no-op commit a no-op.

2. **Full fusion of the marketplace entities into `Model` (D4).** `OrganizationModel` and
   `ModelCatalog` are **collapsed into the single `Model` entity**. "Publishing to the marketplace"
   becomes a **facet** of a Model — a public-visibility flag plus a pinned public version — not a copy
   into a separate table. Activating a marketplace listing **seeds a new `ModelProject`** (a fork) in
   the activating organization and drops the user into the workspace. Existing `OrganizationModel` /
   `ModelCatalog` rows are **backfilled into `ModelProject`s** by an additive migration; the legacy
   tables remain during transition (additive-only rule) and are read through a compatibility layer.

3. **One workspace, three tabs.** The hub "Model, Analyze & Solve" opens a single workspace with
   **Build** (sub-lenses *Canvas · Assistant · Editor*), **Analyze**, and **Solve**. Every lens edits
   the *same* canonical in-memory model (the solver-agnostic `OptimizationProblem`); other
   representations are projections of it. **Model I/O (import-replace, export, view-as-format) is
   consolidated in the Analyze tab**, distinct from *result/solution* export which stays in Solve.

4. **Centralization.** Templates, marketplace, and file import are **sources that seed a
   `ModelProject`**, not terminal destinations — a single funnel for creating and running models. A
   per-project execution history lives inside the project; the **account-level "all runs" birds-eye is
   kept**.

5. **No new solve path; no class-logic duplication.** Solving a `ModelProject` routes through the
   existing single orchestrator with `source_kind="model_project"` (an additive value — the column is
   already wide). A single `classify(problem)` feeds both the stats service and the auto-router.

6. **The bespoke modeling language is deferred.** "Model from scratch" ships first as a Monaco editor
   over the existing `OptimizationProblem` JSON (zero new parser); a bespoke indexed-family DSL is the
   **last** item, behind its own flag.

## Consequences

**Positive**
- One identity for the model across building, analyzing, running, versioning and publishing — the
  product's protagonist finally has a single home. Eliminates the "two bodies" class of bugs and the
  "which screen do I run from?" ambiguity.
- Git-style, message-required version history gives organizations an auditable record of *what changed
  and why* over a model's multi-year life.
- The marketplace stops being a separate object graph; "publish" / "fork" are operations on Models.

**Costs / risks**
- **Migration is the highest-risk work in the effort (tracked as R13).** Collapsing
  `OrganizationModel`/`ModelCatalog` touches activations, executions, reviews and publishing. It MUST
  be additive (create + backfill, no DROP/RENAME in-release), idempotent, count-verified pre/post, and
  fronted by parity tests on every marketplace flow. It is recommended as its own phase.
- **Identity strategy** (reconciles the prior raw-UUID decision): new Models use `mp_`-prefixed IDs;
  **back-filled Models keep their existing raw-UUID** as the `Model` ID to avoid rewriting foreign
  references. So both forms coexist by construction — the prefix rule holds for new entities, and
  legacy UUIDs are preserved, not "fixed".
- **Scripts and seed/fixture data must be adapted** to create/read `Model` instead of the old entities
  (demo/dev seeds, the template validator, demo generators, OpenAPI export, E2E factories).

**Invariants to enforce (contract tests)**
- Every solve entry point (including the project solve) persists `origin + source_kind + source_id`.
- A committed `ModelProjectVersion` is immutable; commit rejects an empty message.
- All `Model` queries filter `organization_id`; cross-org access 404s.
- `ModelStatsService.problem_class` equals the auto-router's classification.
- Model round-trips `export → import` with semantic equivalence.

## Alternatives considered

- **Evolve `ModelBuilderDocument` in place; only brand it "ModelProject" in the UI** (the delivery
  red-team's recommendation, lowest migration cost). *Rejected:* commit-grade versioning needs richer
  columns (author/body/parent/content-hash) the current snapshot model lacks, and the owner explicitly
  chose a clean first-class entity. The over-build risk it warns about is mitigated by phasing (ship the
  workspace shell first over the existing builder-doc with no migration), by having `ModelProject`
  *absorb* the builder-doc rather than run parallel to it, and by reusing the existing
  serializer/diff/restore/solve plumbing.
- **Keep `OrganizationModel` separate and merely link it** to `ModelProject`. *Rejected by the owner:*
  "two separate things has always caused me problems." Full fusion is the explicit goal.
- **Build the bespoke indexed-family DSL now.** *Deferred:* highest open-ended-effort risk; the
  Monaco-over-JSON interim delivers authoring-as-text immediately with no parser.

> Implementation detail, phasing, schema, risk register and test strategy live in the implementation
> plan (`.claude/plans/model-analyze-solve-hub-2026-06-28.md`), which is the working document; this ADR
> records the decision.
