import { describe, it, expect } from "vitest";

/**
 * The objective node read "1000google_ads + 800facebook_instagram +
 * 500000tv_prime_time": the coefficient was glued onto the name, so every term
 * looked like a single identifier.
 */

import { objectiveTerm } from "../ObjectiveNode";

describe("one term of the objective", () => {
  // CONTRACT-TEST: a coefficient never reads as part of the variable's name
  it("separates the coefficient from the name", () => {
    expect(objectiveTerm(1000, "google_ads")).toBe("1000 · google_ads");
    expect(objectiveTerm(0.5, "x")).toBe("0.5 · x");
  });

  it("says nothing about a coefficient of one", () => {
    expect(objectiveTerm(1, "x")).toBe("x");
  });

  it("writes minus one as a sign, not as a factor", () => {
    expect(objectiveTerm(-1, "x")).toBe("-x");
  });

  // The formula joins terms with " + " and rewrites "+ -" as "- ", which only
  // worked while a negative coefficient started with the minus.
  it("keeps a negative coefficient's sign at the front, so the join can fix it", () => {
    expect(objectiveTerm(-3, "x").startsWith("-")).toBe(true);
  });
});
