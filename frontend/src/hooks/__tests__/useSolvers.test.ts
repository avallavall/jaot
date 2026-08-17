/**
 * capabilitiesOf — the lookup every solver-aware panel funnels through (v3.2).
 *
 * Its whole job is to answer "what may the UI promise about this run?", and the
 * dangerous answers are the confident wrong ones: claiming a solver lacks
 * something because we could not look it up, or claiming anything at all about
 * "auto", whose effective solver the backend picks per problem.
 */
import { describe, it, expect } from "vitest";

import { capabilitiesOf, isComparable } from "../useSolvers";
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

/**
 * isComparable — which solvers the comparison pickers may offer (D-31).
 *
 * The dangerous answer here is the opposite of capabilitiesOf's: hiding a
 * solver the user could legitimately pick. A backend that does not send the
 * flag has not said "no", so the picker must keep offering it.
 */
describe("isComparable", () => {
  it("takes the server at its word", () => {
    expect(isComparable({ name: "scip", available: true, comparable: true })).toBe(true);
    expect(
      isComparable({
        name: "hexaly",
        available: true,
        comparable: false,
        not_comparable_reason: "not_available",
      }),
    ).toBe(false);
  });

  // A backend older than D-31 sends no flag at all. Reading that as "cannot
  // compare" would empty the picker on an older server — a silent regression
  // dressed as a fix.
  it("reads a missing flag as comparable", () => {
    expect(isComparable({ name: "scip", available: true })).toBe(true);
    expect(isComparable({ name: "cbc", available: true, comparable: undefined })).toBe(true);
  });
});
