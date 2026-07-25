/**
 * capabilitiesOf — the lookup every solver-aware panel funnels through (v3.2).
 *
 * Its whole job is to answer "what may the UI promise about this run?", and the
 * dangerous answers are the confident wrong ones: claiming a solver lacks
 * something because we could not look it up, or claiming anything at all about
 * "auto", whose effective solver the backend picks per problem.
 */
import { describe, it, expect } from "vitest";

import { capabilitiesOf } from "../useSolvers";
import type { SolverInfo } from "@/lib/types";

const SCIP_CAPS = { sensitivity: true, warm_start: true, quadratic: true, progress: true };
const HEXALY_CAPS = { sensitivity: false, warm_start: true, quadratic: true, progress: false };

const SOLVERS: SolverInfo[] = [
  { name: "scip", available: true, capabilities: SCIP_CAPS },
  { name: "hexaly", available: false, reason: "maintenance", capabilities: HEXALY_CAPS },
  { name: "mystery", available: true },
];

describe("capabilitiesOf", () => {
  it("returns the declaration of a listed solver", () => {
    expect(capabilitiesOf(SOLVERS, "scip")).toEqual(SCIP_CAPS);
    expect(capabilitiesOf(SOLVERS, "hexaly")).toEqual(HEXALY_CAPS);
  });

  // Names travel through the API lowercase but reach this helper from stored
  // executions and pickers alike.
  it("matches case-insensitively", () => {
    expect(capabilitiesOf(SOLVERS, "SCIP")).toEqual(SCIP_CAPS);
    expect(capabilitiesOf(SOLVERS, "HeXaLy")).toEqual(HEXALY_CAPS);
  });

  // A solver in maintenance still ran past executions; its capabilities did not
  // change because a worker is down.
  it("reports capabilities for an unavailable solver", () => {
    expect(capabilitiesOf(SOLVERS, "hexaly")).toEqual(HEXALY_CAPS);
  });

  it("declines to answer for auto-routing", () => {
    expect(capabilitiesOf(SOLVERS, "auto")).toBeUndefined();
  });

  it("declines to answer for a solver that is not listed", () => {
    expect(capabilitiesOf(SOLVERS, "gurobi")).toBeUndefined();
  });

  it("declines to answer when the listing carries no declaration", () => {
    expect(capabilitiesOf(SOLVERS, "mystery")).toBeUndefined();
  });

  it("declines to answer with no name and with an empty listing", () => {
    expect(capabilitiesOf(SOLVERS, null)).toBeUndefined();
    expect(capabilitiesOf(SOLVERS, undefined)).toBeUndefined();
    expect(capabilitiesOf(SOLVERS, "")).toBeUndefined();
    expect(capabilitiesOf([], "scip")).toBeUndefined();
  });
});
