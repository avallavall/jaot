/**
 * Shared configuration for k6 load tests.
 *
 * Environment variables:
 *   BASE_URL      — API base URL (default: http://localhost:8001)
 *   API_KEY       — Bearer token for authenticated endpoints
 */

export const BASE_URL = __ENV.BASE_URL || "http://localhost:8001";

export const headers = {
  public: { "Content-Type": "application/json" },
  authenticated: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${__ENV.API_KEY || "ok_test_placeholder"}`,
  },
};

// ---------------------------------------------------------------------------
// Thresholds aligned with docs/operations/SLA.md
// ---------------------------------------------------------------------------

/** Thresholds for non-solve API endpoints (health, credits, catalog, keys). */
export const apiThresholds = {
  "http_req_duration{type:api}": [
    "p(50)<200",   // SLA: p50 < 200ms
    "p(95)<1000",  // SLA: p95 < 1,000ms
  ],
};

/** Thresholds for the /solve endpoint. */
export const solveThresholds = {
  "http_req_duration{type:solve}": [
    "p(50)<5000",   // SLA: p50 < 5,000ms  (≤100 vars)
    "p(95)<30000",  // SLA: p95 < 30,000ms (≤1,000 vars)
  ],
};

/** Server-error rate (5xx only; 4xx are expected for error-path traffic). */
export const errorThresholds = {
  http_req_failed: ["rate<0.001"],  // SLA: < 0.1% 5xx
};

/**
 * Merge all threshold objects into one for k6 options.thresholds.
 */
export function mergeThresholds(...sets) {
  return Object.assign({}, ...sets);
}
