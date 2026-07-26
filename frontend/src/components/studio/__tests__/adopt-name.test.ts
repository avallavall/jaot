import { describe, it, expect } from "vitest";
import { nameToAdopt, PLACEHOLDER_PROJECT_NAME } from "../adopt-name";

describe("nameToAdopt", () => {
  it("adopts the compiled model's name while the project is untitled", () => {
    expect(nameToAdopt(PLACEHOLDER_PROJECT_NAME, "total_cost")).toBe("Total Cost");
  });

  // A JModel source names itself through its objective; without this a model
  // written in the DSL stayed "Untitled Model" in the list forever, while one
  // built by chatting arrived titled.
  it("handles the objective names a JModel source produces", () => {
    expect(nameToAdopt(PLACEHOLDER_PROJECT_NAME, "minimise_shipping_cost")).toBe(
      "Minimise Shipping Cost",
    );
  });

  it("never overwrites a name the user chose", () => {
    expect(nameToAdopt("Q3 roster", "total_cost")).toBeNull();
  });

  it("leaves the placeholder alone when the model has no name", () => {
    expect(nameToAdopt(PLACEHOLDER_PROJECT_NAME, null)).toBeNull();
    expect(nameToAdopt(PLACEHOLDER_PROJECT_NAME, undefined)).toBeNull();
    expect(nameToAdopt(PLACEHOLDER_PROJECT_NAME, "   ")).toBeNull();
  });

  it("does not rename when the humanized name is what is already there", () => {
    expect(nameToAdopt(PLACEHOLDER_PROJECT_NAME, "untitled_model")).toBeNull();
  });

  it("tolerates surrounding whitespace on the current name", () => {
    expect(nameToAdopt("  Untitled Model  ", "profit")).toBe("Profit");
  });
});
