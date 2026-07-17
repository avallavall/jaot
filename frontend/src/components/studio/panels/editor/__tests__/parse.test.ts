import { describe, it, expect } from "vitest";
import { parseModelText } from "../parse";

const VALID = JSON.stringify({
  variables: [{ name: "x", type: "continuous", lower_bound: 0 }],
  objective: { sense: "minimize", expression: "x" },
  constraints: [{ name: "c1", expression: "x >= 1" }],
});

describe("parseModelText", () => {
  it("accepts a well-formed model and returns the parsed problem", () => {
    const r = parseModelText(VALID);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.problem.variables).toHaveLength(1);
      expect(r.problem.objective.expression).toBe("x");
    }
  });

  it("flags a syntax error with the raw parser message", () => {
    const r = parseModelText("{ not json");
    expect(r).toMatchObject({ ok: false, kind: "syntax" });
    if (!r.ok && r.kind === "syntax") expect(r.detail.length).toBeGreaterThan(0);
  });

  it("rejects a JSON array or scalar (not a model object)", () => {
    expect(parseModelText("[]")).toMatchObject({ ok: false, kind: "shape", field: "object" });
    expect(parseModelText("42")).toMatchObject({ ok: false, kind: "shape", field: "object" });
    expect(parseModelText("null")).toMatchObject({ ok: false, kind: "shape", field: "object" });
  });

  it("reports the first missing structural field", () => {
    expect(parseModelText("{}")).toMatchObject({
      ok: false,
      kind: "shape",
      field: "variables",
    });
    expect(parseModelText('{"variables":[]}')).toMatchObject({
      ok: false,
      kind: "shape",
      field: "constraints",
    });
    expect(parseModelText('{"variables":[],"constraints":[]}')).toMatchObject({
      ok: false,
      kind: "shape",
      field: "objective",
    });
  });

  it("accepts an empty-but-shaped model (semantic checks are the backend's job)", () => {
    const r = parseModelText('{"variables":[],"constraints":[],"objective":{}}');
    expect(r.ok).toBe(true);
  });
});
