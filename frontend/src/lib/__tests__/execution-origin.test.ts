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

  it("routes a marketplace run to its project workspace (P1.5 fusion)", () => {
    expect(executionOriginHref("marketplace", "mp_3")).toBe("/studio/mp_3/build");
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

  it("routes a studio model project to its workspace (source_kind wins over the origin slug)", () => {
    expect(executionOriginHref("visual_builder", "mp_42", "model_project")).toBe(
      "/studio/mp_42/build",
    );
  });
});
