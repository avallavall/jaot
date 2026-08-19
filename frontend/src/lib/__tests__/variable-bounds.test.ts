import { describe, it, expect } from "vitest";

/**
 * Four of the Solution Explorer's seven columns could never hold a value:
 * Lower Bound and Upper Bound were em-dashes written into the JSX, and Binding
 * and Slack always read "N/A" under a tooltip blaming MIP problems — on a pure
 * LP with two continuous variables. The bounds were in the run's own
 * `input_data.variables` the whole time.
 */

import { boundStatus, readVariableBounds } from "../variable-bounds";

describe("readVariableBounds", () => {
  it("reads the range each variable was declared with", () => {
    const bounds = readVariableBounds({
      variables: [
        { name: "x", type: "continuous", lower_bound: 0, upper_bound: 3 },
        { name: "y", type: "integer", lower_bound: 2, upper_bound: 9 },
      ],
    });

    expect(bounds.x).toEqual({ lower: 0, upper: 3 });
    expect(bounds.y).toEqual({ lower: 2, upper: 9 });
  });

  // A solver writes "no bound" as a very large number. Printed as-is it reads
  // as a real limit the model does not have.
  it("reads a solver's infinity as no bound at all", () => {
    const bounds = readVariableBounds({
      variables: [
        { name: "scip", lower_bound: 0, upper_bound: 1e20 },
        { name: "highs", lower_bound: -1e30, upper_bound: 5 },
      ],
    });

    expect(bounds.scip).toEqual({ lower: 0, upper: null });
    expect(bounds.highs).toEqual({ lower: null, upper: 5 });
  });

  it("reads a missing bound as no bound", () => {
    expect(readVariableBounds({ variables: [{ name: "free" }] }).free).toEqual({
      lower: null,
      upper: null,
    });
  });

  // A run recorded before this, or one whose payload the list endpoint omits.
  it("comes back empty rather than failing on a payload it cannot read", () => {
    expect(readVariableBounds(undefined)).toEqual({});
    expect(readVariableBounds(null)).toEqual({});
    expect(readVariableBounds({})).toEqual({});
    expect(readVariableBounds({ variables: "not a list" })).toEqual({});
  });
});

describe("boundStatus", () => {
  it("says which bound the answer pushed the variable onto", () => {
    expect(boundStatus(3, { lower: 0, upper: 3 })).toEqual({ at: "upper", slack: 0 });
    expect(boundStatus(0, { lower: 0, upper: 3 })).toEqual({ at: "lower", slack: 0 });
  });

  it("measures the room left to the nearest bound when it is on neither", () => {
    expect(boundStatus(1, { lower: 0, upper: 10 })).toEqual({ at: null, slack: 1 });
    expect(boundStatus(9, { lower: 0, upper: 10 })).toEqual({ at: null, slack: 1 });
  });

  // CONTRACT-TEST: a solver's rounding does not hide a variable sitting on its bound
  // An integer at its upper bound of 3 comes back as 2.9999999996.
  it("reads a value within the solvers' tolerance as being on the bound", () => {
    expect(boundStatus(2.9999999996, { lower: 0, upper: 3 }).at).toBe("upper");
    expect(boundStatus(1e-11, { lower: 0, upper: 3 }).at).toBe("lower");
  });

  it("says nothing about a variable nobody bounded", () => {
    expect(boundStatus(42, { lower: null, upper: null })).toEqual({ at: null, slack: null });
    expect(boundStatus(42, undefined)).toEqual({ at: null, slack: null });
  });

  it("measures against the one bound there is", () => {
    expect(boundStatus(7, { lower: 0, upper: null })).toEqual({ at: null, slack: 7 });
  });

  it("treats a variable fixed to one number as being on its bound", () => {
    expect(boundStatus(5, { lower: 5, upper: 5 })).toEqual({ at: "lower", slack: 0 });
  });
});
