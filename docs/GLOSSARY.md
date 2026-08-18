# Glossary — the words, and where each one lives in the code

The product has several nouns that sound interchangeable. What each one **means**
is explained for users at [`/docs/getting-started/concepts`](../frontend/content/docs/getting-started/concepts.mdx)
— read that first if you are new to the domain.

This page is the other half: which class, which table, which module. It exists so
a contributor can go from a word in a conversation to the code that implements it
without grepping.

> **One canonical copy.** The user-facing explanation lives in
> `frontend/content/docs/` and is not duplicated here. This file only maps the
> vocabulary onto the codebase, which that page deliberately does not do.

| Word | Class | Table | Where |
|------|-------|-------|-------|
| Model project | `ModelProject` | `model_projects` | `app/models/model_project.py` |
| Version | `ModelProjectVersion` | `model_project_versions` | same file |
| Dataset (a.k.a. scenario) | `ModelProjectDataset` | `model_project_datasets` | same file |
| Marketplace listing | `ModelProjectListing` | `model_project_listings` | same file |
| Problem | `OptimizationProblem` | — (JSON column) | `app/schemas/optimization.py` |
| Result | `OptimizationResult` | — (JSON column) | same file |
| Execution | `ModelExecution` | `model_executions` | `app/models/optimization_model.py` |
| Comparison | `SolverComparison` | `solver_comparisons` | `app/models/solver_comparison.py` |
| Matrix | *(none — derived)* | *(rows share `batch_id`)* | `app/api/v2/solver_comparison_batch.py` |
| JModel source | *(a string on the project)* | `draft_dsl_source` | compiler in `app/domains/dsl/` |
| Template | *(YAML, not a table)* | — | `app/data/templates/*.yaml` (102 in 34 files) |
| Generator | `BaseGenerator` subclasses | — | `app/domains/solver/services/generators/` (33 registered) |
| Solver adapter | `SolverAdapter` (Protocol) | — | `app/domains/solver/adapters/` |

## The distinctions that cost time

- **A problem is not a model project.** `OptimizationProblem` is the flat,
  solver-agnostic maths; a `ModelProject` is the versioned workspace that
  produces one. A project stores its problem as JSON on the draft, and a
  comparison stores a *snapshot* of it per row (that is D-32).

- **A template is not a generator.** A template is a YAML entry with an input
  schema, and it declares a `generator_type`. The generator is the class that
  turns input into an `OptimizationProblem`. 102 templates, 33 generators —
  several templates share one, because the same maths appears under different
  words.

- **A dataset only means something with a JModel source.** It supplies the
  members and values the source declares. A flat or imported model already has
  its numbers inline, which is why the solver matrix refuses one.

- **A matrix has no table.** Its rows are ordinary `SolverComparison` records
  tied by `batch_id`, and its status is *derived* from them. A stored parent
  would have to be kept up to date from Celery tasks in another process.

- **"Compare" means two different things.** `/solve/executions/compare` diffs two
  **solutions**. `/solvers/compare` compares **solvers** on one problem. Neither
  is a rename of the other.

- **An execution is per solver.** Four datasets solved is four executions; four
  solvers compared is also four. `ModelExecution.comparison_id` is what ties the
  second kind to its parent.
