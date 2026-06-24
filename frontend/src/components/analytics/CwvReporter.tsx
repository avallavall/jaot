"use client";

import { onLCP, onINP, onCLS, onFCP, onTTFB, type Metric } from "web-vitals";
import { useEffect } from "react";

// Ambient type declaration for the Plausible custom-event API.
// window.plausible is injected by script.js (PlausibleScript.tsx, loaded afterInteractive).
declare global {
  interface Window {
    plausible?: (event: string, opts?: { props?: Record<string, string | number> }) => void;
  }
}

/**
 * Round a raw metric value to reduce cardinality in Plausible (D-05).
 * LCP, FCP → nearest 250 ms
 * INP      → nearest 50 ms
 * TTFB     → nearest 100 ms
 * CLS      → nearest 0.05
 */
function roundMetricValue(name: string, value: number): number {
  if (name === "LCP" || name === "FCP") return Math.round(value / 250) * 250;
  if (name === "INP") return Math.round(value / 50) * 50;
  if (name === "TTFB") return Math.round(value / 100) * 100;
  if (name === "CLS") return Math.round(value / 0.05) * 0.05;
  return value;
}

/**
 * CwvReporter — pipes the 5 Core Web Vitals (LCP, INP, CLS, FCP, TTFB) from
 * web-vitals@5.2.0 to a single Plausible custom event named "CWV" with props
 * { metric, rating, value }.
 *
 * Mount once in (public)/layout.tsx beside <PlausibleScript /> (D-01).
 * Renders nothing — returns null.
 *
 * SC1 compliance: web-vitals callbacks are registered DIRECTLY from the
 * web-vitals@5.2.0 package (not via next/web-vitals useReportWebVitals whose
 * underlying lib is Next's bundled ~v4.2.1 and would not satisfy SC1's >=5.2.0).
 */
export function CwvReporter() {
  useEffect(() => {
    // Queue stub: ensures window.plausible is callable even before script.js loads
    // (the <Script strategy="afterInteractive"> may race with the CWV callbacks).
    window.plausible =
      window.plausible ||
      function (...args: Parameters<NonNullable<Window["plausible"]>>) {
        // Cast needed: the queue-stub .q property is not on the plausible fn type.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        ((window.plausible as any).q = (window.plausible as any).q || []).push(args);
      };

    // Report handler: D-04 — take rating + value straight from the web-vitals callback.
    // D-05 — round value to keep cardinality low in Plausible.
    const report = ({ name, value, rating }: Metric) => {
      // Defensive guard: only the 5 standard CWV metrics are expected from
      // direct registration, but guard against future library changes.
      if (!["LCP", "INP", "CLS", "FCP", "TTFB"].includes(name)) return;
      window.plausible?.("CWV", {
        props: { metric: name, rating, value: roundMetricValue(name, value) },
      });
    };

    // web-vitals@5.2.0 is THE metric source (SC1 requires >=5.2.0).
    // Register the v5 callbacks DIRECTLY — NOT via next/web-vitals useReportWebVitals.
    onLCP(report);
    onINP(report);
    onCLS(report);
    onFCP(report);
    onTTFB(report);
  }, []);

  return null;
}
