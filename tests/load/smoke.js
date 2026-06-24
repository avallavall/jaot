/**
 * Smoke Test — 5 VUs, 30 seconds
 *
 * Purpose: Quick sanity check that the API is alive and responding.
 * Use as a CI baseline — must pass with ZERO errors.
 *
 * Run:
 *   k6 run tests/load/smoke.js
 *   k6 run tests/load/smoke.js -e BASE_URL=http://localhost:8001 -e API_KEY=ok_test_...
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
  solveInvalid,
  unauthorized,
} from "./lib/requests.js";

export const options = {
  vus: 5,
  duration: "30s",
  thresholds: {
    ...mergeThresholds(apiThresholds, solveThresholds, errorThresholds),
    checks: ["rate>0.95"],           // ≥95% of checks must pass
    http_req_duration: ["p(95)<2000"], // Overall p95 < 2s for smoke
  },
};

export default function () {
  // Weighted traffic mix: mostly happy-path, some error paths
  const roll = Math.random();

  if (roll < 0.30) {
    healthCheck();
  } else if (roll < 0.50) {
    creditBalance();
  } else if (roll < 0.65) {
    modelCatalog();
  } else if (roll < 0.80) {
    solveSmall();
  } else if (roll < 0.90) {
    solveInvalid();
  } else {
    unauthorized();
  }
}
