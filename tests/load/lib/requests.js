/**
 * Reusable request functions for load test scenarios.
 *
 * Each function tags its requests so k6 thresholds can distinguish
 * API latency from solve latency.
 */

import http from "k6/http";
import { check } from "k6";
import { BASE_URL, headers } from "./config.js";
import { PROBLEM_SMALL, PROBLEM_MEDIUM, PROBLEM_INVALID } from "./payloads.js";

// ---------------------------------------------------------------------------
// Public endpoints
// ---------------------------------------------------------------------------

export function healthCheck() {
  const res = http.get(`${BASE_URL}/api/v2/health`, {
    tags: { type: "api", name: "health" },
  });
  check(res, { "health 200": (r) => r.status === 200 });
  return res;
}

// ---------------------------------------------------------------------------
// Authenticated API endpoints
// ---------------------------------------------------------------------------

export function creditBalance() {
  const res = http.get(`${BASE_URL}/api/v2/credits/balance`, {
    headers: headers.authenticated,
    tags: { type: "api", name: "credits_balance" },
  });
  check(res, { "credits 200": (r) => r.status === 200 });
  return res;
}

export function modelCatalog() {
  const res = http.get(`${BASE_URL}/api/v2/models/catalog`, {
    headers: headers.authenticated,
    tags: { type: "api", name: "model_catalog" },
  });
  check(res, { "catalog 200": (r) => r.status === 200 });
  return res;
}

// ---------------------------------------------------------------------------
// Solve endpoints
// ---------------------------------------------------------------------------

export function solveSmall() {
  const res = http.post(
    `${BASE_URL}/api/v2/solve`,
    JSON.stringify(PROBLEM_SMALL),
    {
      headers: headers.authenticated,
      tags: { type: "solve", name: "solve_small" },
    }
  );
  check(res, {
    "solve ok": (r) => r.status === 200 || r.status === 402 || r.status === 429,
  });
  return res;
}

export function solveMedium() {
  const res = http.post(
    `${BASE_URL}/api/v2/solve`,
    JSON.stringify(PROBLEM_MEDIUM),
    {
      headers: headers.authenticated,
      tags: { type: "solve", name: "solve_medium" },
    }
  );
  check(res, {
    "solve ok": (r) => r.status === 200 || r.status === 402 || r.status === 429,
  });
  return res;
}

// ---------------------------------------------------------------------------
// Error-path traffic (expected failures)
// ---------------------------------------------------------------------------

/** Send an invalid payload — expects 422. */
export function solveInvalid() {
  const res = http.post(
    `${BASE_URL}/api/v2/solve`,
    JSON.stringify(PROBLEM_INVALID),
    {
      headers: headers.authenticated,
      tags: { type: "api", name: "solve_invalid" },
    }
  );
  check(res, { "invalid → 422": (r) => r.status === 422 });
  return res;
}

/** Hit an authenticated endpoint without credentials — expects 401. */
export function unauthorized() {
  const res = http.get(`${BASE_URL}/api/v2/credits/balance`, {
    headers: headers.public,
    tags: { type: "api", name: "unauthorized" },
  });
  check(res, { "no-auth → 401/403": (r) => r.status === 401 || r.status === 403 });
  return res;
}

/** Burst requests to trigger rate limiting — expects 429 eventually. */
export function rateLimitBurst() {
  const res = http.get(`${BASE_URL}/api/v2/credits/balance`, {
    headers: headers.authenticated,
    tags: { type: "api", name: "rate_limit" },
  });
  // 200 or 429 are both acceptable here
  check(res, { "rate-limit ok": (r) => r.status === 200 || r.status === 429 });
  return res;
}
