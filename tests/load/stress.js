/**
 * Stress Test — ramp to 200 VUs
 *
 * Purpose: Find the breaking point. Document how the platform degrades
 * under load that exceeds normal capacity and how it recovers.
 *
 * Expected: error rate rises, latency increases. We want to capture
 * WHERE it breaks (which VU count, which endpoints first).
 *
 * Run:
 *   k6 run tests/load/stress.js -e BASE_URL=http://localhost:8001 -e API_KEY=ok_test_...
 */

import { errorThresholds } from "./lib/config.js";
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
    { duration: "1m",  target: 50 },   // normal load
    { duration: "2m",  target: 100 },  // above normal
    { duration: "2m",  target: 200 },  // stress zone
    { duration: "2m",  target: 200 },  // sustain stress
    { duration: "1m",  target: 50 },   // recovery
    { duration: "1m",  target: 0 },    // cool-down
  ],
  thresholds: {
    // No strict latency thresholds — this test documents degradation.
    // Only track that the server does not fully crash (some requests succeed).
    ...errorThresholds,
    checks: ["rate>0.50"],  // At least half the checks should pass
  },
};

export default function () {
  const roll = Math.random();

  if (roll < 0.15) {
    healthCheck();
  } else if (roll < 0.30) {
    creditBalance();
  } else if (roll < 0.45) {
    modelCatalog();
  } else if (roll < 0.60) {
    solveSmall();
  } else if (roll < 0.72) {
    solveMedium();
  } else if (roll < 0.80) {
    solveInvalid();
  } else if (roll < 0.90) {
    unauthorized();
  } else {
    rateLimitBurst();
  }
}
