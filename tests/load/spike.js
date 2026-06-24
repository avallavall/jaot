/**
 * Spike Test — instant surge from 0 to 300 VUs
 *
 * Purpose: Simulate a sudden traffic spike (e.g., Show HN front page,
 * marketing campaign launch). Documents:
 *   - How the platform handles sudden load
 *   - Whether it recovers after the spike subsides
 *   - If connections or resources are properly released
 *
 * Run:
 *   k6 run tests/load/spike.js -e BASE_URL=http://localhost:8001 -e API_KEY=ok_test_...
 */

import { errorThresholds } from "./lib/config.js";
import {
  healthCheck,
  creditBalance,
  modelCatalog,
  solveSmall,
  solveInvalid,
  unauthorized,
} from "./lib/requests.js";

export const options = {
  stages: [
    { duration: "10s", target: 5 },    // baseline
    { duration: "5s",  target: 300 },  // SPIKE — near-instant ramp
    { duration: "1m",  target: 300 },  // sustain spike
    { duration: "5s",  target: 5 },    // sudden drop
    { duration: "1m",  target: 5 },    // recovery observation
    { duration: "10s", target: 0 },    // cool-down
  ],
  thresholds: {
    // Spike test is about behavior, not strict SLA.
    // Server must not fully crash.
    ...errorThresholds,
    checks: ["rate>0.30"],  // Expect high error rate during spike
  },
};

export default function () {
  const roll = Math.random();

  if (roll < 0.25) {
    healthCheck();
  } else if (roll < 0.40) {
    creditBalance();
  } else if (roll < 0.55) {
    modelCatalog();
  } else if (roll < 0.75) {
    solveSmall();
  } else if (roll < 0.88) {
    solveInvalid();
  } else {
    unauthorized();
  }
}
