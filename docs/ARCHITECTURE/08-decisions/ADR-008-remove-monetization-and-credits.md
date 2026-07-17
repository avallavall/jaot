# ADR-008 — Remove monetization and the credit system entirely

**Status:** Accepted (owner decision, 2026-07-10)
**Context:** post-OSS pivot (public repo, free collaborative marketplace), pre-P1.5 fusion.

## Context

JAOT pivoted to open source in June 2026: the public pitch is "free and collaborative",
the SaaS pricing page is gone, and the paid marketplace sits dormant behind
`MONETIZATION_ENABLED=false` (every billing/seller-payout endpoint returns 404).

A full surface audit (2026-07-10) found **two distinct layers**:

1. **The money layer** — Stripe (checkout/subscriptions/webhooks/Connect), invoices,
   seller earnings & withdrawals, featured placements, exchange rates, seller TOS,
   admin billing pages: ~3,700 LOC of backend, 9 dedicated tables, ~6,000 LOC of
   dedicated tests. Dormant, unused, but fully maintained.
2. **The credit system** — NOT gated by `MONETIZATION_ENABLED`. Every solve and every
   LLM message pre-pays credits; each org gets a one-time grant (20,000) and there is
   **no automatic refill**. In practice credits are a depletable counter that ends in
   HTTP 402 — a kill-switch that has already locked out the platform's own operator.
   Keeping it correct is expensive (the ADR-007 S3 audit alone fixed six real credit
   bugs, including a concurrent-refund mint).

Abuse protection does NOT depend on either layer. Independent controls that remain:
per-org rate limits (per-minute + per-day), a daily solve quota (`max_daily_solves`),
per-solve time caps (plan `max_solve_time_seconds` + Celery soft/hard limits + the
execution reaper), `max_variables`, request body caps, always-on auth with lockout —
and the one real out-of-pocket cost, LLM spend, is capped by the monthly EUR budget
(`LLM_MONTHLY_BUDGET_EUR`) with BYOK-first (org keys are free to the platform).

## Decision

Remove both layers **entirely** — delete the code, do not flag it off.

1. **Money layer: delete.** Stripe services + webhook, invoices, seller
   earnings/sales, withdrawals (+ schedules + admin approval), featured placements,
   exchange rates/currency, seller TOS, `MONETIZATION_ENABLED` and every
   billing/commission/placement/withdrawal setting, the Stripe CSP entries, and the
   `STRIPE_*` infra config.
2. **Credit system: delete.** `CreditsService`, workspace credit pools, solve
   pricing (`compute_credits`/`calculate_credits`), the prepaid/refund carrier, the
   credits API (balance/transactions/calculator), admin credit adjust, every
   deduct/refund call site (solve enqueue, workers, triggers, reaper, LLM), the 402
   insufficient-credits paths, the `x-credits-balance` response header, signup
   grants, credit Prometheus metrics, and the credit fields in API responses
   (breaking change — bundled into v3.0.0 like the rest of ADR-007).
3. **What stays:** rate limits, daily solve quota, time/variable caps, the LLM EUR
   budget + BYOK, plan tiers as **limit profiles only** (their `credits` /
   `monthly_quota` fields go).
4. **Data:** additive-only rule holds — no DROP/RENAME. Dead tables and columns stay
   in the schema, unmapped and unwritten; a cleanup migration may drop them in a
   LATER release. Historic `credits_consumed` values remain in old rows.
5. **Docs/positioning:** README/docs/CLAUDE.md stop describing credits and Stripe;
   quotas are documented as plain usage limits. Final marketing polish still lands
   in release-finalization (last).

## Consequences

- P1.5 (marketplace fusion) shrinks: seller analytics/earnings/placements and their
  FK tables leave its blast radius; no credit columns to migrate.
- The ADR-007 S3 audit's remaining credit debt (F4 refund asymmetry, F6 metric
  double-count, F7 `credits_used_month`) dies at the root.
- Dedicated money/credit test suites (~10,000 LOC incl. their CONTRACT-TESTs) are
  deleted **with their feature** — allowed by `tests/test_quality_proof.md §6`
  (feature removal, not consolidation); remaining suites drop their balance/402
  assertions.
- Self-hosters get a simpler platform; a future operator who wants payments builds
  them as an extension, not by flipping a flag.

## Rejected alternative

`CREDITS_ENABLED=false` (soft kill-switch): keeps all the machinery and its
maintenance cost — exactly the overhead this decision removes — and adds a second
confusing flag next to the dead `MONETIZATION_ENABLED`.
