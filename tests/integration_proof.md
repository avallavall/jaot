# Integration Proof Policy

Tests under `frontend/e2e/*.spec.ts` are integration tests: they assert that the full stack
(frontend, API, worker, database) behaves correctly together. Mocking the JAOT-owned HTTP
boundary in these tests defeats their purpose entirely.

## 1 — Definition of the Antipattern

**Phase 9 incident (2026-05-18):** `contact-form.spec.ts` was green in CI for 2 days while
production had 3 hidden bugs: `EMAIL_BACKEND='console'` in PSS (emails dropped), the Celery
worker never called `EmailService.configure()` (every worker-side email silently discarded),
and a stale Resend `SMTP_PASSWORD` causing SMTP auth failures. The first real contact with
the system was discovered by a human operator, not by CI.

The root cause was this mock in the spec (lines 18–31):

```typescript
// frontend/e2e/contact-form.spec.ts
await page.route("**/api/v2/contact", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ id: "ctc_e2e", status: "pending", created_at: "..." }),
  });
});
```

**Antipattern definition:** mocking the JAOT-owned HTTP boundary that a test claims to
validate makes the test a component render check, not an integration test. The test then
asserts the behavior of its own mock, not of the system.

## 2 — Mechanizable Rule

**JAOT-owned surface** (D-05): any path matching `/api/v2/*` or `/api/v1/*`, or any hostname
matching `localhost:8001`, `api:8001` (Docker network), `jaot.io`, `*.jaot.io`.

**Enforcement:** ESLint rule `jaot/no-e2e-mock-jaot-boundary` registered in
`frontend/eslint.config.mjs`, applied to `e2e/**/*.ts(x)`. The rule detects
`page.route(<path>).fulfill(...)` calls where `<path>` matches the JAOT-owned regex and
the fulfill argument is synthetic (not a `route.fetch()` passthrough). The machine-readable
domain allowlist is at `frontend/eslint/allowlist.json`.

## 3 — External Allowlist

External SaaS calls may be mocked in `e2e/` specs when running them live would incur real
costs or require credentials unavailable in CI. The single source of truth is
`frontend/eslint/allowlist.json`. Current allowed domains:

| Domain | Reason |
|--------|--------|
| `api.stripe.com` | Stripe payment API — charges per request; credentials not in CI |
| `*.resend.com` | Resend email API — charges per email; credentials not in CI |
| `api.anthropic.com` | Claude LLM API — charges per token; not in CI budget |
| `api.openai.com` | OpenAI API — charges per token; not in CI budget |

**Plausible** (`plausible.jaot.io`) is **not** in the allowlist. Run real Plausible in CI via
`docker-compose` — the stack already supports it (D-08).

## 4 — Naming Conventions

- `frontend/e2e/*.spec.ts` — Playwright E2E against real Docker backend (`target: runner`).
  No `page.route().fulfill()` for JAOT-owned paths. Mocking external allowlist domains is
  permitted. Docker stack must be up (`docker-compose up -d --build`) before running.

- `frontend/src/**/__tests__/*.test.tsx` and co-located `*.test.ts(x)` — vitest unit tests.
  Mocking is permitted and expected. This is the correct home for tests that need to fake
  `/api/v2/*` responses.

**Legitimate seams (not antipatterns):** unit-test fakes such as `MockEmailService`,
`FakeHexalyAdapter`, and `conftest.py::mock_auth` (lines 619–654) substitute a component to
isolate the subject under test — they do not mock the integration boundary. Celery task
capture (`send_contact_email.delay` patched in `test_contact.py`) is also a legitimate seam:
it stubs external infra, not the HTTP endpoint.

## 5 — Exception Process

If a `frontend/e2e` spec must mock an external (allowlist) domain, use:

```typescript
// eslint-disable-next-line jaot/no-e2e-mock-jaot-boundary -- justification: external
//   Stripe billing webhook; credentials not in CI. See tests/integration_proof.md §3.
await page.route("**/api.stripe.com/**", async (route) => { ... });
```

Rules for the justification text: ≥ 25 chars after `--`, no `TODO`/`FIXME`/`HACK`/`XXX`
tokens, should cite `integration_proof.md §3` (soft-check per D-13 — the lint rule enforces
token presence and length ≥ 25 chars, not citation content).

**Reviewer checklist:** before approving an `eslint-disable` comment, confirm the path in the
`page.route()` call actually matches an entry in `frontend/eslint/allowlist.json`, and that
the real service cannot be run cheaply in CI instead.
