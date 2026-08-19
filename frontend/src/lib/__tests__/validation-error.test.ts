import { describe, it, expect } from "vitest";
import { fieldPath, readValidationProblems } from "@/lib/validation-error";

describe("fieldPath", () => {
  it("drops the plumbing segment and keeps the field", () => {
    expect(fieldPath(["body", "objective"])).toBe("objective");
    expect(fieldPath(["query", "page"])).toBe("page");
  });

  it("keeps a nested path readable", () => {
    expect(fieldPath(["body", "variables", 0, "name"])).toBe("variables.0.name");
  });

  it("answers empty for a problem with no location", () => {
    expect(fieldPath(undefined)).toBe("");
    expect(fieldPath([])).toBe("");
  });
});

describe("readValidationProblems", () => {
  // The Result panel used to read "Field required" — which field unsaid.
  it("names the field in the English message", () => {
    const read = readValidationProblems([
      { type: "missing", loc: ["body", "objective"], msg: "Field required" },
    ]);

    expect(read.message).toBe("objective: Field required");
  });

  it("gives a code and the field names for a page to translate", () => {
    const read = readValidationProblems([
      { type: "missing", loc: ["body", "objective"], msg: "Field required" },
      { type: "missing", loc: ["body", "variables"], msg: "Field required" },
    ]);

    expect(read.code).toBe("validation.missing_fields");
    expect(read.params).toEqual({ fields: "objective, variables", count: 2 });
  });

  it("tells a wrong value from a missing one", () => {
    const read = readValidationProblems([
      { type: "string_type", loc: ["body", "name"], msg: "Input should be a valid string" },
    ]);

    expect(read.code).toBe("validation.invalid_fields");
    expect(read.params).toEqual({ fields: "name", count: 1 });
  });

  it("counts a field named twice once", () => {
    const read = readValidationProblems([
      { type: "missing", loc: ["body", "objective"], msg: "Field required" },
      { type: "missing", loc: ["body", "objective"], msg: "Field required" },
    ]);

    expect(read.params).toEqual({ fields: "objective", count: 1 });
  });

  it("leaves a problem with no field without a code", () => {
    const read = readValidationProblems([{ type: "value_error", msg: "Something is off" }]);

    expect(read.message).toBe("Something is off");
    expect(read.code).toBeUndefined();
  });
});
