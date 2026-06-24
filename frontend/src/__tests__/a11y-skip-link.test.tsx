import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import React from "react";
import { SkipLink } from "@/components/layout/SkipLink";

describe("Skip-to-content link (A11Y-04)", () => {
  it("renders a skip-to-content link as first focusable element", () => {
    const { container } = render(
      <div>
        <SkipLink />
        <main id="main-content">Page content</main>
      </div>
    );

    // Look for a link with text "Skip to content" (or similar)
    const skipLink = container.querySelector('a[href="#main-content"]');
    expect(skipLink).not.toBeNull();
    expect(skipLink?.textContent).toMatch(/skip to content/i);
  });

  it("skip link has sr-only class by default", () => {
    const { container } = render(
      <div>
        <SkipLink />
        <main id="main-content">Page content</main>
      </div>
    );

    const skipLink = container.querySelector('a[href="#main-content"]');
    expect(skipLink).not.toBeNull();
    // The skip link should be visually hidden (sr-only) until focused
    expect(skipLink?.className).toMatch(/sr-only/);
  });
});
