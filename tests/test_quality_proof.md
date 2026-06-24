# Backend Test-Quality Proof Policy

The user's pain, stated verbatim: *"que los test sean demasiado simples, que se basen solo en respuestas http"*. Phase 11 already codified the equivalent rule for frontend E2E tests in [`tests/integration_proof.md`](integration_proof.md) — "no mocking of the JAOT-owned HTTP boundary." This document is the unit/integration-level analog for the Python backend. The 5-tier smell checklist below is the grading rubric for the Phase 12.2 audit; §6 defines the `# CONTRACT-TEST:` annotation that 12.3's deletion gate will consult.

## 1 — Definition of the Antipattern

The smell: a test mocks the boundary it claims to validate. The assertion is then about the mock's response shape, not about the system. Phase 9's `contact-form.spec.ts` incident is the frontend version of the same bug; on the backend it shows up as `MagicMock(spec=Session)` plus a `status_code == 200` check, with no row ever touching Postgres.

Forbidden snippet (do NOT do this):

```python
def test_create_user_creates_a_user():
    fake = MagicMock(spec=Session)
    response = client.post("/api/v2/users", json={...})
    assert response.status_code == 200          # the mock returned 200 — of course it did
    fake.add.assert_called_once()               # asserting on our own mock, not the system
```

That test is a component render check, not a database-backed integration test. It passes in CI for months while production accumulates schema drift, missing indexes, and silently dropped rows. CLAUDE.md's rule is explicit: **"Don't mock the database — use real PostgreSQL."** Tier 1 enforcement makes that rule mechanizable.

## 2 — Mechanizable Rule

The Tier-1 anti-patterns blocked by [`scripts/check_test_quality_tier1.py`](../scripts/check_test_quality_tier1.py):

| Pattern | Regex | Why forbidden |
|---------|-------|---------------|
| `MagicMock(spec=Session)` | `MagicMock\s*\(\s*spec\s*=\s*Session\s*\)` | Fakes the SQLAlchemy session. "DB-backed" test asserts its own mock, not the DB. Violates CLAUDE.md "NEVER mock the database — use real PostgreSQL." |
| `patch(...get_session)` | `patch\s*\([^)]*get_session\b` | Substitutes the DI'd DB session at the FastAPI dependency layer. Same problem: the test owns what "the database" means. |
| `patch(...get_current_user)` | `patch\s*\([^)]*get_current_user\b` | Substitutes the auth dependency in-test. The test then asserts that "authenticated" requests work — but it's the test that decided what "authenticated" means. Phase 9 incident class (auth bypass surfaces only when real keys hit the wire). |

Hook registration in `.pre-commit-config.yaml`:

- `id: check-test-quality-tier-1`
- `language: system` (pure-stdlib script; no managed venv)
- `entry: python3 scripts/check_test_quality_tier1.py`
- `files: ^tests/.*\.py$`
- `exclude: '(^|/)conftest\.py$'` (per D-02 — fixtures are the legitimate seam)
- `pass_filenames: true`

The same script runs in CI under the `lint-backend` step (Plan 12.1-03). Pre-commit catches it locally; CI is the hard gate.

**Day-1 violation count is 0** — grep across all 171 test files returns zero matches for the three regexes. The hook turns on green; no grandfather list is needed.

## 3 — Legitimate Seams (NOT blocked — explicit carve-out)

`MagicMock(spec=...)` is allowed for non-DB unit isolation. The hook matches `MagicMock(spec=Session)` literally — `Session` only, not `spec=`-anything:

| Legitimate pattern | Example | Why allowed |
|--------------------|---------|-------------|
| `MagicMock(spec=User)` | `tests/api/test_deps.py:20,29` | Mocks a data-class-like instance to isolate pure business logic. The DB is not in the loop. |
| `MagicMock(spec=Organization)` | `tests/test_pricing_restructure.py:450,490,531,571`; `tests/test_tier_caps.py:103` | Same shape — domain model standing in for the org under test. |
| `MagicMock(spec=Request)` | `tests/api/test_deps.py` | FastAPI request object; not a boundary. |
| `MockEmailService`, `FakeHexalyAdapter`, `MockSolverAdapter` | `tests/services/*`, `tests/unit/test_solve_orchestrator.py` (6 occurrences) | Substitutes external/expensive components — the unit's own dependencies, not the boundary under test. |
| `conftest.py::mock_auth` (and any `**/conftest.py` patch of `get_current_user` / `get_session`) | `tests/conftest.py` | Fixtures are the legitimate auth/DB seam. In-test patching is the smell; in-fixture patching is the seam. Globally excluded via `exclude: '(^|/)conftest\.py$'` per D-02. |

Aliasing — `from sqlalchemy.orm import Session as DbSession` then `MagicMock(spec=DbSession)` — would not match the literal `Session` regex. The alias name is fine but is discouraged on readability grounds.

## 4 — Naming Conventions

| Path | Realism | Tier-1 enforcement |
|------|---------|--------------------|
| `tests/test_*.py` (root) | Integration + unit; real PostgreSQL via fixtures. | **Forbidden.** Use `db_session` fixture instead of `MagicMock(spec=Session)`. |
| `tests/api/` | API + HTTP round-trip; real PostgreSQL. | **Forbidden.** |
| `tests/integration/` | Multi-service integration; real PostgreSQL + real Celery if applicable. | **Forbidden.** |
| `tests/unit/` | Pure unit; no DB. `MagicMock(spec=<non-Session>)` allowed. | **Forbidden** for `spec=Session` (use a callable that takes a session, or move the test to `tests/test_*.py`). |
| `tests/contracts/` | Schema/OpenAPI stability. | No DB; not in scope for Tier 1. |
| `tests/**/conftest.py` | Fixtures. `patch(...get_current_user)` / `patch(...get_session)` IS the legitimate auth/DB seam. | **Excluded** globally via D-02. |

## 5 — Exception Process (per-line escape hatch, per D-01)

If a test MUST contain one of the three Tier-1 patterns (rare — discuss before landing), bypass the hook with:

```python
# test-quality-skip: legitimate fixture-style seam in unit test, see test_quality_proof.md §3
fake = MagicMock(spec=Session)
```

Rules for the justification (enforced by the hook):

- **≥ 25 chars** total after `# test-quality-skip:`.
- **Forbidden tokens:** `TODO`, `FIXME`, `HACK`, `XXX` — you cannot defer the smell with a sticky "will fix later."
- **Citation:** SHOULD cite `test_quality_proof.md §3` (soft check — reviewer enforces citation; the hook enforces length + forbidden-token absence).
- **Marker placement:** same line as the violation OR within the 3 lines immediately above it (allows multi-line `MagicMock(spec=Session)(\n  ...)` calls).

Why `# test-quality-skip:` and not `# noqa: test-quality-tier-1`? Per D-01: `ruff 0.14.5` (pinned in `.pre-commit-config.yaml`) treats unknown `# noqa:` codes as `RUF100` "unused noqa" errors. A distinct marker is owned entirely by our hook and ignored by ruff. The marker exists exclusively to suppress this hook.

**Emergency bypass for the whole commit:** `git commit --no-verify` (matches the existing project-wide pattern documented at `.pre-commit-config.yaml:2`). `--no-verify` only bypasses local pre-commit; CI's `lint-backend` step is the hard gate and re-runs the same script on the same regex set.

## 6 — `# CONTRACT-TEST:` Annotation (the do-not-delete marker, per D-03)

Some tests look small but encode load-bearing invariants — refund idempotency, cross-tenant isolation, credit-balance non-negativity under concurrency. Deleting them in 12.3 consolidation passes would silently remove the only guard against an entire regression class.

**Annotation syntax:**

```python
# CONTRACT-TEST: <kebab-case-slug> [(<REQ-ID>)]
#   <invariant description, ≥20 chars, one or two lines>
```

**Placement rules:**

- **Class-scoped invariant** → on the `class` definition (or above the `@pytest.mark.*` decorator stack).
- **Function-scoped invariant** → on the `def test_...` line (or above its decorators).
- **File-scoped invariant** (multiple tests in the file share the invariant) → at the top of the file, after the module docstring, before imports.

**Discovery:**

```bash
grep -rEn "^\s*#\s*CONTRACT-TEST:" tests/
```

returns the full registry as `file:line: # CONTRACT-TEST: <slug> ...`. No separate registry file in Phase 12.1 (D-03): the comment IS the registration. If Phase 12.2's audit surfaces >30 annotated tests, the audit may add a `tests/CONTRACT-TESTS.md` registry — decide then.

**12.3 enforcement (out of 12.1 scope):** the plan-checker for 12.3 deletion commits MUST grep the annotated set and fail any deletion of an annotated test class/function without an explicit ADR commit. This document defines the marker; 12.3 wires the enforcement.

### Worked example 1 — CR-01 (refund idempotency)

```python
# tests/test_cancel_refund_idempotency.py

# CONTRACT-TEST: refund-idempotency (CR-01)
#   Exactly one refund row per (organization_id, reference_type='solve_task',
#   reference_id=task_id) under concurrent cancel + worker-except race.
#   Removing this test removes the only guard against double-refund regressions.
@pytest.mark.integration
class TestCancelRefundIdempotency:
    """CR-01 regression: concurrent cancel + worker-except produces exactly one refund."""
    ...
```

### Worked example 2 — CR-02 (cross-tenant isolation)

```python
# tests/test_tenant_isolation.py
"""OWASP A01: Cross-tenant isolation tests."""

# CONTRACT-TEST: cross-tenant-isolation (CR-02)
#   Organization B cannot access Organization A's data through any API endpoint.
#   Cross-tenant 404 detail string is identical to genuine 404 (anti-oracle, D-18).
#   Removing this file removes the cross-tenant IDOR regression guard.

import hashlib
...
```

### Worked example 3 — credit concurrency invariants

```python
# tests/test_credit_race_conditions.py

# CONTRACT-TEST: credit-concurrency-invariants
#   SELECT FOR UPDATE correctness under multi-thread concurrency:
#   balance never goes negative; concurrent solves do not double-debit;
#   async refunds settle exactly once.
class TestCreditRaceConditions:
    ...
```

## Appendix — Tiers 2–5 (rubric for 12.2 audit; NOT hook-enforced in 12.1)

Phase 12.1 only mechanizes Tier 1. Tiers 2–5 are the audit rubric the 12.2 plan will apply file-by-file. Each tier has at least one concrete `tests/<file>:<line>` example so the rubric is anchored to real code.

### Tier 2 — HTTP-status-only assertions

The test sends a request and asserts only `response.status_code == 200`. No body assertion, no schema check, no DB side-effect verification.

- Example: `tests/test_admin_auth.py:1` (1 occurrence of `assert response.status_code == 200` with no other assertions in the function).
- Why a smell: the endpoint returning `200` says nothing about whether the work was done correctly.
- 12.4 strengthens these to status + Pydantic schema roundtrip + DB side effect.

### Tier 3 — Shallow body assertions

The test asserts response body shape (`"items" in data`, `isinstance(data["count"], int)`) but not semantics (the right rows, the right values).

- Example: `tests/api/test_admin.py:32-39` (shape checks: keys exist, types are int — no value assertions).
- Why a smell: the endpoint can return an empty list, the wrong list, or the right list under the wrong filter — all three pass shape checks.
- 12.4 strengthens these to value-level assertions tied to fixture data.

### Tier 4 — Per-test semantic assertion (PASSING BAR)

The test asserts status + body semantics (`all(item["price_eur"] >= 10 for item in data)`) + happy path + at least one error/edge case. This is the bar.

- Example: `tests/test_catalog_filters.py:14-38` (status + body semantics + happy + error).
- This is the per-test target tier 12.4 is steering toward.

### Tier 5 — Suite-level invariants (GOLD STANDARD)

Properties that hold for the whole suite, not per-test:

- Coverage gate (Phase 12.0 baseline: 78% in CI, see `pyproject.toml::tool.pytest.ini_options::addopts`).
- Mutation score on the 5 critical financial/auth modules ≥ 75% (Phase 12.5 target).
- CONTRACT-TEST registry (this §6) — invariant tests cannot be silently deleted.
- Anti-oracle assertions: cross-tenant `404` detail strings must equal genuine `404` detail strings (D-18 from Phase 4).
- Concurrent-access test for every financial endpoint (CR-01, credit-race file already encode this).

12.1 does not enforce Tier 5; it defines the rubric so 12.5 has a target.

---

**Living document:** edits to this policy land via conventional commit `docs(12.x):` with rationale in the commit message. The hook script and this document MUST agree byte-for-byte on the three Tier-1 regex strings — divergence is the primary tampering risk (T-12.1-01).
