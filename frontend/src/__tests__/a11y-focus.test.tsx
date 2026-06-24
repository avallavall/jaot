import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

// Read globals.css content for pattern assertions
const globalsCssPath = path.resolve(__dirname, "../app/globals.css");
const cssContent = fs.readFileSync(globalsCssPath, "utf-8");

describe("Focus-visible styles (A11Y-03)", () => {
  it("globals.css contains focus-visible base styles for interactive elements", () => {
    // Should have focus-visible rules for common interactive elements
    expect(cssContent).toContain("focus-visible");

    // Should target interactive element selectors
    const interactiveSelectors = ["a", "button", "input", "textarea", "select", '[role="button"]'];
    const hasInteractiveTargets = interactiveSelectors.some((selector) =>
      cssContent.includes(selector)
    );
    expect(hasInteractiveTargets).toBe(true);

    // Should use the design system ring color variable
    expect(cssContent).toContain("var(--ring)");

    // Should have outline-offset for visual clarity
    expect(cssContent).toContain("outline-offset: 0.125rem");
  });

  it("focus-visible styles use outline (not box-shadow ring)", () => {
    // Accessible focus indicators should use CSS outline, not box-shadow
    // because outline respects high-contrast mode
    expect(cssContent).toMatch(/outline:\s*0\.125rem\s+solid/);
  });
});
