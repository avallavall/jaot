import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";

// Mock web-vitals: capture each callback the component registers.
// The component calls onLCP(report), onINP(report), onCLS(report), onFCP(report), onTTFB(report)
// directly from web-vitals (not via next/web-vitals useReportWebVitals).
const captured: Record<string, (metric: { name: string; value: number; rating: string }) => void> =
  {};

vi.mock("web-vitals", () => ({
  onLCP: (cb: (m: { name: string; value: number; rating: string }) => void) => {
    captured.LCP = cb;
  },
  onINP: (cb: (m: { name: string; value: number; rating: string }) => void) => {
    captured.INP = cb;
  },
  onCLS: (cb: (m: { name: string; value: number; rating: string }) => void) => {
    captured.CLS = cb;
  },
  onFCP: (cb: (m: { name: string; value: number; rating: string }) => void) => {
    captured.FCP = cb;
  },
  onTTFB: (cb: (m: { name: string; value: number; rating: string }) => void) => {
    captured.TTFB = cb;
  },
}));

import { CwvReporter } from "../CwvReporter";

describe("CwvReporter", () => {
  beforeEach(() => {
    // Reset captured callbacks between tests
    for (const k of Object.keys(captured)) {
      delete captured[k];
    }
    // Reset window.plausible between tests
    delete (window as unknown as { plausible?: unknown }).plausible;
  });

  it("fires window.plausible('CWV') for LCP — rounds 1234ms to nearest 250 = 1250", () => {
    const plausibleMock = vi.fn();
    (window as unknown as { plausible: typeof plausibleMock }).plausible = plausibleMock;
    render(<CwvReporter />);
    act(() => {
      captured.LCP?.({ name: "LCP", value: 1234, rating: "good" });
    });
    expect(plausibleMock).toHaveBeenCalledOnce();
    expect(plausibleMock).toHaveBeenCalledWith("CWV", {
      props: { metric: "LCP", rating: "good", value: 1250 },
    });
  });

  it("fires window.plausible('CWV') for INP — rounds 173ms to nearest 50 = 150", () => {
    const plausibleMock = vi.fn();
    (window as unknown as { plausible: typeof plausibleMock }).plausible = plausibleMock;
    render(<CwvReporter />);
    act(() => {
      captured.INP?.({ name: "INP", value: 173, rating: "needs-improvement" });
    });
    expect(plausibleMock).toHaveBeenCalledOnce();
    expect(plausibleMock).toHaveBeenCalledWith("CWV", {
      props: { metric: "INP", rating: "needs-improvement", value: 150 },
    });
  });

  it("fires window.plausible('CWV') for CLS — rounds 0.12 to nearest 0.05 = 0.10", () => {
    const plausibleMock = vi.fn();
    (window as unknown as { plausible: typeof plausibleMock }).plausible = plausibleMock;
    render(<CwvReporter />);
    act(() => {
      captured.CLS?.({ name: "CLS", value: 0.12, rating: "good" });
    });
    expect(plausibleMock).toHaveBeenCalledOnce();
    expect(plausibleMock).toHaveBeenCalledWith("CWV", {
      props: { metric: "CLS", rating: "good", value: expect.closeTo(0.1, 5) },
    });
  });

  it("fires window.plausible('CWV') for TTFB — rounds 640ms to nearest 100 = 600", () => {
    const plausibleMock = vi.fn();
    (window as unknown as { plausible: typeof plausibleMock }).plausible = plausibleMock;
    render(<CwvReporter />);
    act(() => {
      captured.TTFB?.({ name: "TTFB", value: 640, rating: "good" });
    });
    expect(plausibleMock).toHaveBeenCalledOnce();
    expect(plausibleMock).toHaveBeenCalledWith("CWV", {
      props: { metric: "TTFB", rating: "good", value: 600 },
    });
  });

  it("fires window.plausible('CWV') for FCP — rounds 1700ms to nearest 250 = 1750", () => {
    const plausibleMock = vi.fn();
    (window as unknown as { plausible: typeof plausibleMock }).plausible = plausibleMock;
    render(<CwvReporter />);
    act(() => {
      captured.FCP?.({ name: "FCP", value: 1700, rating: "good" });
    });
    expect(plausibleMock).toHaveBeenCalledOnce();
    expect(plausibleMock).toHaveBeenCalledWith("CWV", {
      props: { metric: "FCP", rating: "good", value: 1750 },
    });
  });

  it("does NOT call window.plausible for a non-CWV metric name (FID guard)", () => {
    const plausibleMock = vi.fn();
    (window as unknown as { plausible: typeof plausibleMock }).plausible = plausibleMock;
    render(<CwvReporter />);
    act(() => {
      // Invoke via the LCP captured callback but pass FID name to test the defensive guard
      captured.LCP?.({ name: "FID", value: 10, rating: "good" });
    });
    expect(plausibleMock).not.toHaveBeenCalled();
  });

  it("installs queue stub so window.plausible is always callable", () => {
    // window.plausible is NOT set before render — queue stub should install it
    expect((window as unknown as { plausible?: unknown }).plausible).toBeUndefined();
    render(<CwvReporter />);
    // After render+useEffect, queue stub should have installed window.plausible
    expect((window as unknown as { plausible?: unknown }).plausible).toBeDefined();
  });
});
