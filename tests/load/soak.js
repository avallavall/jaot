/**
 * Soak Test — 30 VUs, 30 minutes
 *
 * Purpose: Run moderate load for an extended period to detect:
 *   - Memory leaks (gradual latency increase)
 *   - Connection pool exhaustion (sudden error spikes)
 *   - File descriptor leaks
 *   - Database connection saturation
 *
 * Indicators of problems:
 *   - p95 latency trending upward over time
 *   - Error rate increasing after sustained period
 *   - Server OOM or process crash
 *
 * Run:
 *   k6 run tests/load/soak.js -e BASE_URL=http://localhost:8001 -e API_KEY=ok_test_...
 *
 * Tip: Use --out json=soak-results.json to capture time-series data
 *      for post-hoc analysis of latency drift.
 */

import {
  mergeThresholds,
  apiThresholds,
  solveThresholds,
  errorThresholds,
} from "./lib/config.js";
import {
  healthCheck,
  creditBalance,
  modelCatalog,
  solveSmall,
  solveMedium,
  solveInvalid,
  unauthorized,
  rateLimitBurst,
} from "./lib/requests.js";

export const options = {
  stages: [
    { duration: "1m",  target: 30 },  // ramp-up
    { duration: "30m", target: 30 },  // sustained soak
    { duration: "1m",  target: 0 },   // cool-down
  ],
  thresholds: {
    ...mergeThresholds(apiThresholds, solveThresholds, errorThresholds),
    checks: ["rate>0.90"],
    // Soak-specific: overall p95 should stay stable
    http_req_duration: ["p(95)<3000"],
  },
};

export default function () {
  const roll = Math.random();

  if (roll < 0.20) {
    healthCheck();
  } else if (roll < 0.35) {
    creditBalance();
  } else if (roll < 0.50) {
    modelCatalog();
  } else if (roll < 0.65) {
    solveSmall();
  } else if (roll < 0.75) {
    solveMedium();
  } else if (roll < 0.82) {
    solveInvalid();
  } else if (roll < 0.90) {
    unauthorized();
  } else {
    rateLimitBurst();
  }
}
