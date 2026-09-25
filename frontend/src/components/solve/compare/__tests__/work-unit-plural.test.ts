import { describe, it, expect } from "vitest";
import { createTranslator } from "use-intl/core";

import en from "../../../../../messages/en.json";
import es from "../../../../../messages/es.json";

/**
 * The work chart said "1 nodes in 0.29 s" for a solve that stopped at the
 * root. The unit is a plural now, rendered here with the real messages.
 */
describe("the work chart's unit", () => {
  it.each([
    ["en", en, "node", "nodes"],
    ["es", es, "nodo", "nodos"],
  ])("agrees with the count in %s", (locale, messages, one, other) => {
    const t = createTranslator({ locale, messages, namespace: "solverCompare.charts" });
    expect(t("workUnit.nodes", { count: 1 })).toBe(one);
    expect(t("workUnit.nodes", { count: 2773 })).toBe(other);
  });
});

// The home race said "1 nodes, 4,214 simplex iterations" for HiGHS.
describe("the home race's work line", () => {
  it.each([
    ["en", en, "1 node, 4,214 simplex iterations"],
    ["es", es, "1 nodo, 4214 iteraciones símplex"],
  ])("agrees with the count in %s", (locale, messages, expected) => {
    const t = createTranslator({ locale, messages, namespace: "public.solverRace" });
    expect(t("rowWork", { nodes: 1, iterations: 4214 })).toBe(expected);
  });
});
