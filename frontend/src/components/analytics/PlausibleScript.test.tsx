import { describe, it, expect, vi } from "vitest";
import { createElement } from "react";
import { render } from "@testing-library/react";

// Mock `next/script` so jsdom honors the attributes synchronously. The real
// next/script defers DOM injection to runtime, which jsdom does not execute.
vi.mock("next/script", () => ({
  default: (props: Record<string, unknown>) => createElement("script", props),
}));

import { PlausibleScript } from "./PlausibleScript";

const TRACKER_SELECTOR = 'script[src="https://plausible.jaot.io/js/script.js"]';

describe("PlausibleScript", () => {
  it("renders a script tag pointing at the Plausible tracker", () => {
    const { container } = render(<PlausibleScript />);
    expect(container.querySelector(TRACKER_SELECTOR)).toBeTruthy();
  });

  it("sets data-domain to jaot.io", () => {
    const { container } = render(<PlausibleScript />);
    const script = container.querySelector(TRACKER_SELECTOR);
    expect(script).not.toBeNull();
    expect(script?.getAttribute("data-domain")).toBe("jaot.io");
  });

  it("applies defer attribute", () => {
    const { container } = render(<PlausibleScript />);
    const script = container.querySelector(TRACKER_SELECTOR);
    expect(script).not.toBeNull();
    expect(script?.hasAttribute("defer")).toBe(true);
  });

  it("uses afterInteractive strategy", () => {
    const { container } = render(<PlausibleScript />);
    const script = container.querySelector<HTMLElement>(TRACKER_SELECTOR);
    expect(script).not.toBeNull();
    // next/script receives `strategy` as a prop; the mock passes it through,
    // so it lands as an attribute (or dataset entry, depending on React's
    // prop forwarding). Accept either shape.
    const strategy = script?.getAttribute("strategy") ?? script?.dataset.strategy ?? null;
    expect(strategy).toBe("afterInteractive");
  });
});
