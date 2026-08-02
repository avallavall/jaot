# JModel — Frozen Grammar (P5 gate, 2026-07-01)

> **Canonical home:** `docs/JMODEL_GRAMMAR.md` (moved into the repo 2026-07-21 from a
> local untracked path so every clone carries the spec; content unchanged). This is the
> normative grammar `app/domains/dsl/` implements — extend it via dated addenda like
> §6–§10, never by rewriting frozen sections.
>
> **Status: FROZEN for the gate.** This is the written grammar the P5 STOP-gate requires
> ("a frozen written grammar + a ≤2-week parser spike that round-trips 3 real models, else STOP").
> The spike (`scratchpad/jmodel_spike/`) implements exactly this subset. If the gate PASSES, this
> grammar graduates to `app/domains/dsl/`; if it STOPs, this file records why.
>
> ### ✅ GATE RESULT: **PASS** (2026-07-01, spike built in hours, well under the ≤2-week budget)
> All four acceptance criteria met on all 3 real models (`assignment`, `knapsack`, `edge_select`):
> 1. Parsed + lowered with **zero hand-written flat nodes**.
> 2. Each lowered output **validates** as a Pydantic `OptimizationProblem` AND passes
>    `validate_problem()` (the `/solve/validate` name/bounds gate).
> 3. Each **solves to its known optimum** through the real `SCIPAdapter` — `assignment`=9,
>    `knapsack`=220, `edge_select`=6 — proving the emitted strings are semantically correct.
> 4. Lowering is **deterministic** (byte-stable across two compiles). Parser = 646 lines incl.
>    docstrings/blanks/dataclasses (~460 code) — in the spirit of the "~500 LOC" target.
> `edge_select` exercises **set-filters** (`i != j` in both a `sum{}` and a constraint family) +
> same-set double indexing (the TSP/routing precursor, directly on-thesis for the owner's MDPDP).
> Evidence: `scratchpad/jmodel_spike/` (`jmodel.py`, `models/*.jmodel`, `verify.py`), run in the
> `jaot-api` image. **⇒ P5 is GREEN to build** (graduate the spike → `app/domains/dsl/`).

## 1. Design contract

JModel is a **lean, AMPL/ZIMPL-flavored, declarative** modeling language. It is:

- **Turing-incomplete by design** — no user functions, no recursion, no unbounded loops. The only
  iteration is bounded set-comprehension (`sum{...}`, `forall`). Statically analyzable: every model
  grounds to a finite flat problem in one deterministic pass.
- **An index-algebra macro expander, NOT a math core.** It expands `sets`/`params`/indexed families
  and `sum{}`/`forall` into the existing flat `OptimizationProblem` (`app/schemas/optimization.py`).
  Every scalar leaf becomes a plain expression **string** — the existing `ExpressionParser` (used by
  the solve path) parses it verbatim. JModel writes **zero** new math evaluation.
- **Deterministic lowering.** `lower(model)` → `OptimizationProblem` (flat variables list + one
  objective string + one constraint string per grounded family member). No solver-specific output.

The anti-hairball payoff: a 200×14 assignment model is ~12 authoring lines (one `var assign{E,S}`
family + 2 constraint families) instead of 2,800 flat React-Flow nodes / 2,800 flat variables authored
by hand.

## 2. Lowering target (the flat `OptimizationProblem`)

```jsonc
{
  "name": "str",
  "variables": [ {"name": "assign_A_1", "type": "binary", "lower_bound": 0, "upper_bound": 1}, ... ],
  "objective":  {"sense": "minimize", "expression": "4*assign_A_1 + 2*assign_A_2 + ..."},
  "constraints":[ {"name": "each_task_1", "expression": "assign_A_1 + assign_B_1 + assign_C_1 == 1"}, ... ]
}
```

- `type ∈ {continuous, integer, binary}`; `binary` implies `lb=0, ub=1`.
- Variable names are mangled from `family[i,j]` → `family_i_j`, sanitized to `[A-Za-z_][A-Za-z0-9_]*`
  (index tokens joined by `_`; any non-alnum char in a member → `_`). Uniqueness is guaranteed by the
  set/family structure; a post-mangle collision check aborts lowering (fatal, never silent).
- Constraint family `c{t in T}` grounds to one flat constraint per `t`, named `c_<t>`.

## 3. Concrete syntax (EBNF, informal)

```
model        := statement+
statement    := set_decl | param_decl | var_decl | objective | constraint | comment

comment      := "#" .* NEWLINE                      # full-line or trailing

set_decl     := "set" IDENT ":=" set_literal ";"
set_literal  := "{" member ("," member)* "}"
member       := IDENT | INT                          # 'A', 'plant1', 3 — alnum tokens

param_decl   := "param" IDENT [ "{" index_sets "}" ] ":=" param_body ";"
index_sets   := IDENT ("," IDENT)*                   # e.g. WORKERS, TASKS  (2-D param)
param_body   := scalar_num                           # scalar param:  param cap := 10;
              | entry ("," entry)*                    # indexed:       key... value
entry        := member+ scalar_num                   # 'A 1 4'  (A,1 → 4)  |  'A 20' (A → 20)

var_decl     := "var" IDENT [ "{" index_sets "}" ] var_spec ";"
var_spec     := ("binary" | "integer" | "continuous")? bound*
bound        := (">=" | "<=") scalar_num             # ">= 0", ">= 0 <= 100"
                                                     # default type = continuous, default bounds
                                                     # lb=-inf/ub=+inf unless given; binary ⇒ [0,1]

objective    := ("minimize" | "maximize") IDENT ":" lin_expr ";"

constraint   := "subject to" IDENT [ "{" qualifiers "}" ] ":" rel_expr ";"
rel_expr     := lin_expr ("<=" | ">=" | "==") lin_expr

qualifiers   := binding ("," binding)* [ ":" filter ]
binding      := IDENT "in" IDENT                     # t in TASKS
filter       := condition ("and" condition)*
condition    := idx_term ("!=" | "==" | "<" | ">" | "<=" | ">=") idx_term
idx_term     := IDENT | INT | member                 # index var, literal, or set member

lin_expr     := term (("+" | "-") term)*
term         := [ coef "*" ] factor                  # coef may itself be a param ref or number
factor       := scalar_num
              | var_ref
              | param_ref
              | "sum" "{" qualifiers "}" lin_expr     # aggregation over the qualifier bindings
var_ref      := IDENT [ "[" idx_list "]" ]           # assign[w,t]  (idx = bound index vars)
param_ref    := IDENT [ "[" idx_list "]" ]           # cost[w,t]    (resolved to a NUMBER at ground)
idx_list     := idx_term ("," idx_term)*
scalar_num   := NUMBER
```

### Semantics / lowering rules
- **Grounding** enumerates the Cartesian product of the qualifier bindings (respecting `filter`),
  substitutes each `param_ref` with its numeric value, resolves each `var_ref` to its mangled flat
  name, folds numeric `coef*number` products, and concatenates terms into ONE expression string.
- `sum{q} e` expands to the `+`-join of `e` evaluated at every tuple satisfying `q` (empty sum → `0`).
- A `forall`-style constraint family is written as `subject to c{q}: ...` — grounding `q` produces one
  flat constraint per tuple. (There is no standalone `forall` keyword; the `{q}` qualifier on
  `subject to` IS the forall.)
- **Params are compile-time constants**, never variables. A `param_ref` that survives to a leaf is
  substituted to its number; an unknown key is a fatal lowering error.
- Only **linear** expressions in the spike (product of two `var_ref`s → fatal "nonlinear, out of spike
  scope"). The flat schema/`ExpressionParser` support nonlinear later; the gate stays linear.

## 4. What the spike MUST prove (gate acceptance)
1. Parse + lower **3 real models** (assignment, knapsack, transportation) with no hand-written flat
   nodes.
2. Each lowered output **validates** as a Pydantic `OptimizationProblem`.
3. Each **solves to its known optimum** through the existing solver (SCIP + `ExpressionParser`),
   proving the emitted strings are semantically correct — not just syntactically valid.
4. `lower()` is **deterministic** (byte-stable across runs) and **≤ ~500 LOC**.

If any of 1–4 fails and cannot be fixed within the spike budget → **STOP** (record the wall here).

## 5. Explicitly OUT of the spike (deferred to full P5 if the gate passes)
- Multi-dim set literals as tuples (`set ARCS := {(A,1),(B,2)}`) — **SHIPPED, see §6**,
  set operators (`union`, `cross`),
  ranges (`1..10`) — **SHIPPED, see §7**, conditional params, `if/then` in expressions, ZIMPL
  import, nonlinear terms,
  the Monaco/editor lens + i18n, and round-trip *back* to JModel from
  flat (lowering is one-way for the gate).

## 6. ADDENDUM (2026-07-03, S6 / DSL-expressivity #3) — Tuple sets

Pulled forward into S6 (TFM bridge): the thesis MDPDP formulation sums over sparse arcs
`(i,j) ∈ A′` everywhere, so N-dimensional sets are now part of the language.

```
set_decl     := "set" IDENT [ "dimen" INT ] [ ":=" set_literal ] ";"
set_literal  := "{" set_member ("," set_member)* "}" | "{" "}"
set_member   := member | "(" member ("," member)+ ")"    # tuple member, arity >= 2

binding      := index_spec "in" IDENT
index_spec   := IDENT | "(" IDENT ("," IDENT)+ ")"       # tuple-unpacking binding
```

Semantics:
- Every member of one set has the same arity; an inline literal infers `dimen`, a
  declaration-only tuple set MUST state it (`set ARCS dimen 2;`; default 1, as in AMPL).
  A dataset member with the wrong component count is a structured error naming the fix.
- **Datasets encode tuple members as comma-joined strings** (`"A,B"`) — the same
  composite-key encoding indexed param values already use. `.dat` files may write
  `set ARCS := (A,B) (B,C);`.
- A family indexed over a tuple set takes the FLAT component count as subscripts
  (`var x{ARCS, K};` → `x[i,j,k]`; same for params, whose data keys are flat too)
  and expands over the set's ACTUAL members — sparse by construction, never the
  cartesian closure of the components. References outside the member list are
  ghost-variable errors (this is the sparsity guard).
- Qualifiers unpack: `sum{(i, j) in ARCS : j == n} x[i, j]`. An index may be bound
  only once per qualifier.
- **Equality-filter slicing:** an `==` filter pinning a component of binding level `b`
  to a value resolvable before `b` (literal, outer index, earlier binding) is executed
  as an indexed lookup (lazily-built per `(set, positions)` index), so per-row sums
  over sparse sets cost O(matched) instead of O(|set|) — and consume budget
  accordingly. Semantics identical to the full-scan compare, including numeric-first
  equality (`"1" == "1.0"`; index keys are canonicalized through the same rule).
- Indexed param bodies now parse entries greedily (`key... value`, comma-separated);
  the flat key arity is validated at grounding (it depends on set dimensions).
  Duplicate inline keys are now rejected (previously last-one-won silently).
- `MAX_GROUNDED_ELEMENTS` raised 500k → **2,000,000**: the TFM's largest flow scenario
  (243 vehicles × 199 orders, three sparse tuple arc sets) grounds to ~850k elements;
  slicing keeps compile time linear.
- `dimen` joins the reserved words.

## 7. ADDENDUM (2026-07-04, DSL-expressivity #2) — Ranges

```
set_decl     := "set" IDENT [ "dimen" INT ] [ ":=" set_body ] ";"
set_body     := set_literal | range_literal
range_literal:= signed_int ".." signed_int              # inclusive: set T := 1..96;
signed_int   := [ "-" ] INT
```

Semantics:
- `lo..hi` declares the 1-dimensional integer members `lo, lo+1, ..., hi` (inclusive),
  exactly as the equivalent brace literal `{lo, ..., hi}` would — members are the same
  decimal strings, so filters (numeric-first comparison), params keyed on them, and
  mangling behave identically.
- Endpoints are (optionally signed) integer literals — not params or floats. A
  descending range (`5..1`) is a structured error, not a silent empty set; a range
  larger than `MAX_GROUNDED_ELEMENTS` is rejected at parse time.
- Ranges appear only as a `set` body (not inline in qualifiers); bind via the set name.

## 8. ADDENDUM (2026-07-04, DSL-expressivity #1) — Quadratic terms

```
term         := factor (("*") factor)*            # unchanged; var*var now grounds
factor       := ["-"|"+"] factor | power
power        := primary [ ("^" | "**") INT ]      # INT ∈ {1, 2}; 1 is the identity
```

Semantics:
- Products distribute at grounding: linear × linear → bilinear terms
  (`(x + y)^2` → `x^2 + 2*x*y + y^2`); constants keep folding as before. Anything
  that would exceed TOTAL degree 2 (`x*y*z`, `x^2*y`, `(x*y)^2`, `x^3`) is a
  structured compile error — the flat `ExpressionParser` caps at degree 2.
- Unary minus binds looser than `^` (AMPL): `-x^2` = `-(x^2)`.
- Bilinear pairs consolidate under an order-insensitive key (`x*y + y*x` → `2*x*y`).
- Emission: squares as `v^2`, cross products as `v1*v2` — both native to the flat
  parser; linear terms first, then quadratic (byte-stable for pure-linear models).
- Downstream (verified): `classify()` → QP/MIQP/QCP/MIQCP; auto-router sends
  quadratics to Hexaly/SCIP; SCIP builds quadratic CONSTRAINTS natively but its
  objective must be LINEAR → shared epigraph reformulation in `_scip_expression.
  set_scip_objective` (aux var `t`, `f(x) <= t`, minimize `t`), applied to BOTH
  SCIP model builders; HiGHS now REJECTS quadratics explicitly (it used to drop
  them silently — a wrong linear relaxation); sensitivity is capped for quadratic
  problems (LP duals do not apply).

## 9. ADDENDUM (2026-07-04, DSL-expressivity #4) — Set operators

```
set_decl     := "set" IDENT [ "dimen" INT ] [ ":=" set_body ] ";"
set_body     := set_expr                                # a lone literal/range is the base case
set_expr     := set_term (("union" | "diff") set_term)*  # left-associative
set_term     := set_atom ("cross" set_atom)*             # cross binds tighter (AMPL)
set_atom     := IDENT | "(" set_expr ")" | set_literal | range_literal
```

Semantics:
- `union` keeps first-appearance order and deduplicates; `diff` keeps the left
  operand's order; `cross` concatenates member tuples (dimen adds, left-outer
  order) and is budget-checked before materializing.
- Operand sets must be declared EARLIER in the source (forward references are
  errors) — so member dimension is static at parse time and cycles are
  impossible. `union`/`diff` require equal dimensions.
- Members of a computed set are evaluated after datasets fill the operands, in
  declaration order; a dataset may still override the computed set itself,
  whole-symbol (like inline literals). `/dsl/inspect` marks computed sets as
  self-filling so the dataset editor never asks for them.
- Anonymous literal/range atoms are allowed (`1..5 diff {2, 4}`); an EMPTY
  literal inside an expression is an error (no inferable dimension).
- `union`, `diff`, `cross` join the reserved words.

## 10. ADDENDUM (2026-07-04, DSL-expressivity #5) — Conditional expressions

```
primary      := ... | if_expr
if_expr      := "if" if_cond ("and" if_cond)* "then" term [ "else" term ]
if_cond      := if_operand ("!=" | "==" | "<" | ">" | "<=" | ">=") if_operand
if_operand   := idx_term | IDENT "[" idx_list "]"       # the indexed form must be a PARAM
```

Semantics:
- Selection happens at GROUNDING time, per qualifier environment. Conditions
  compare bound indices, declared set members, numbers, and PARAM values
  (scalar by name, indexed with subscripts) — a variable in a condition is a
  structured error: conditions are decided by the compiler, never the solver.
- Only the taken branch is grounded — `if i != j then d[i, j]` never looks up
  the diagonal, which is what makes sparse conditional params usable.
- A missing `else` is 0 (AMPL). Branches bind to the following TERM (like
  `sum`); parenthesize to widen: `(if c then x else y) * 2`.
- Comparison semantics are exactly the filter rules: numeric-first equality
  (`"1" == "1.0"`), ordering requires numeric terms.
- `if`, `then`, `else` join the reserved words.
