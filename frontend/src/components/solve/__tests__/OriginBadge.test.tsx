/**
 * The badge is the one place that names an origin, and every other surface now
 * reads its labels from the same namespace. What matters here is that it never
 * invents a name: the next-intl mock in src/test/setup.tsx echoes the key path
 * back, so a translated label shows up as "solve.origin.<key>" and a raw slug
 * shows up as itself — which is exactly the distinction being asserted.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { OriginBadge } from "../OriginBadge";

describe("OriginBadge", () => {
  it("names each known origin from the shared namespace", () => {
    render(<OriginBadge origin="mcp" />);
    expect(screen.getByText("solve.origin.mcp")).toBeInTheDocument();
  });

  it("lets a studio source_kind win over the looser origin slug", () => {
    render(<OriginBadge origin="visual_builder" sourceKind="model_project" />);
    expect(screen.getByText("solve.origin.model_project")).toBeInTheDocument();
  });

  it("shows a retired slug as stored rather than calling it manual", () => {
    // `cron` predates `triggered` and still exists on historical rows.
    render(<OriginBadge origin="cron" />);
    expect(screen.getByText("cron")).toBeInTheDocument();
  });

  it("falls back to manual only when no origin was recorded", () => {
    render(<OriginBadge />);
    expect(screen.getByText("solve.origin.manual")).toBeInTheDocument();
  });

  it("explains a triggered run in its tooltip", () => {
    render(<OriginBadge origin="triggered" triggerName="Nightly refresh" />);
    expect(screen.getByText("solve.origin.triggered")).toHaveAttribute(
      "title",
      "solve.origin.triggerName",
    );
  });
});
