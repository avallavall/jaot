// Formatting + chart helpers for the platform-analytics dashboard.
import type { PeriodOption } from "./platform-types";

export const PERIODS: PeriodOption[] = [
  { labelKey: "period.last7Days", days: 7 },
  { labelKey: "period.last30Days", days: 30 },
  { labelKey: "period.last90Days", days: 90 },
  { labelKey: "period.allTime", days: 0 },
];

const numberFormat = new Intl.NumberFormat("en-US");

export const fmtInt = (n: number): string => numberFormat.format(Math.round(n));

export const fmtNum = (n: number, digits = 1): string => n.toFixed(digits);

export const fmtPct = (ratio: number): string => `${(ratio * 100).toFixed(1)}%`;

export const fmtMs = (ms: number | null): string => {
  if (ms == null) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`;
};

export const fmtSeconds = (s: number | null): string =>
  s == null ? "—" : s < 60 ? `${s.toFixed(1)} s` : `${(s / 60).toFixed(1)} min`;

export const fmtEur = (n: number): string => `€${n.toFixed(2)}`;

// Vintage chart palette (defined in globals.css).
export const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

export const TOOLTIP_STYLE = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: "0.5rem",
  fontSize: "12px",
  color: "var(--popover-foreground)",
} as const;
