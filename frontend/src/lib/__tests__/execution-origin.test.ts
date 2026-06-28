import { describe, it, expect } from "vitest";
import { executionOriginHref } from "../execution-origin";

describe("executionOriginHref", () => {
  it("routes the visual builder to its document", () => {
    expect(executionOriginHref("visual_builder", "bld_1")).toBe("/builder/bld_1");
  });

  it("routes the AI builder to the chat view of its document", () => {
    expect(executionOriginHref("ai_builder", "bld_2")).toBe("/builder/bld_2/chat");
  });

  it("routes a template run to the template form", () => {
    expect(executionOriginHref("template", "mcat_9")).toBe("/builder/templates/mcat_9");
  });

  it("routes a marketplace run to the model run page", () => {
    expect(executionOriginHref("marketplace", "org_model_3")).toBe("/solve/org_model_3");
  });

  it("returns null for imports (no persistent origin)", () => {
    expect(executionOriginHref("import", null)).toBeNull();
  });

  it("returns null when there is no source id", () => {
    expect(executionOriginHref("visual_builder", null)).toBeNull();
    expect(executionOriginHref("visual_builder", undefined)).toBeNull();
  });

  it("returns null for unknown origins", () => {
    expect(executionOriginHref("manual", "x")).toBeNull();
    expect(executionOriginHref(undefined, "x")).toBeNull();
  });
});
