import { describe, it, expect } from "vitest";
import { getZoneFromPath } from "../zones";

describe("getZoneFromPath", () => {
  it("maps /builder/doc123/chat to llm", () => {
    expect(getZoneFromPath("/builder/doc123/chat")).toBe("llm");
  });

  it("maps /builder/doc123 to builder", () => {
    expect(getZoneFromPath("/builder/doc123")).toBe("builder");
  });

  it("maps /builder to builder", () => {
    expect(getZoneFromPath("/builder")).toBe("builder");
  });

  it("maps /solve/executions/exec123 to results", () => {
    expect(getZoneFromPath("/solve/executions/exec123")).toBe("results");
  });

  it("maps /solve to solver", () => {
    expect(getZoneFromPath("/solve")).toBe("solver");
  });

  it("maps /marketplace to models", () => {
    expect(getZoneFromPath("/marketplace")).toBe("models");
  });

  it("maps /workspace/usage to dashboard", () => {
    expect(getZoneFromPath("/workspace/usage")).toBe("dashboard");
  });

  it("maps /workspace to dashboard", () => {
    expect(getZoneFromPath("/workspace")).toBe("dashboard");
  });

  it("maps /admin to dashboard", () => {
    expect(getZoneFromPath("/admin")).toBe("dashboard");
  });

  it("maps unknown path to dashboard fallback", () => {
    expect(getZoneFromPath("/settings")).toBe("dashboard");
  });

  it("maps / to dashboard fallback", () => {
    expect(getZoneFromPath("/")).toBe("dashboard");
  });

  it("maps /builder/abc123/chat/history to llm (nested chat)", () => {
    expect(getZoneFromPath("/builder/abc123/chat/history")).toBe("llm");
  });
});
