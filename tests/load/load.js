/**
 * Load Test — ramp to 50 VUs, sustain 5 minutes
 *
 * Purpose: Validate the platform meets SLA targets under expected peak load.
 *   - p95 < 500ms for API endpoints
 *   - p95 < 30s for solve
 *   - Error rate (5xx) < 0.1%
 *
 * Run:
 *   k6 run tests/load/load.js -e BASE_URL=http://localhost:8001 -e API_KEY=ok_test_...
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
    { duration: "30s", target: 10 },  // warm-up
    { duration: "1m",  target: 50 },  // ramp to peak
    { duration: "5m",  target: 50 },  // sustain peak
    { duration: "30s", target: 0 },   // cool-down
  ],
  thresholds: {
    ...mergeThresholds(apiThresholds, solveThresholds, errorThresholds),
    checks: ["rate>0.90"],
    "http_req_duration{type:api}": ["p(95)<500"],  // Tighter for load test
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
