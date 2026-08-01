import type { AnalyticsFilters, Period } from "./analytics-types";

export const EVENT_TYPES = [
  "user.signup",
  "user.login",
  "org.create",
  "solver.solve",
  "model.create",
  "ai_builder.message",
  "mcp.tool_call",
  "marketplace.activate",
  "marketplace.publish",
  "template.use",
  "schedule.create",
] as const;

export const DOMAIN_COLORS: Record<string, string> = {
  solver: "#3b82f6",
  marketplace: "#22c55e",
  ai: "#a855f7",
  ai_builder: "#a855f7",
  mcp: "#f97316",
  scheduling: "#eab308",
  schedule: "#eab308",
  user: "#ec4899",
  org: "#8b5cf6",
  template: "#3b82f6",
};

export const TOOLTIP_STYLE = {
  backgroundColor: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  borderRadius: "8px",
  color: "hsl(var(--popover-foreground))",
  fontSize: "13px",
};

export const PERIODS: { value: Period; labelKey: string }[] = [
  { value: "1h", labelKey: "period1h" },
  { value: "12h", labelKey: "period12h" },
  { value: "today", labelKey: "periodToday" },
  { value: "7d", labelKey: "period7d" },
  { value: "30d", labelKey: "period30d" },
  { value: "90d", labelKey: "period90d" },
  { value: "all", labelKey: "periodAll" },
];

/** Minimal shape of next-intl's translator, so these helpers stay pure. */
export interface AnalyticsTranslator {
  (key: string, values?: Record<string, string | number>): string;
  has(key: string): boolean;
}

/**
 * Name an event type for a reader. Event types are wire values ("solver.solve");
 * title-casing them produced screen text like "Solver Solve" and "Marketplace
 * Activate". A type with no translation still falls back to title case, so a new
 * one added on the server shows up readable rather than blank.
 */
export function formatEventType(eventType: string, t?: AnalyticsTranslator): string {
  const key = `eventTypes.${eventType}`;
  if (t?.has(key)) return t(key);
  return eventType
    .replace(/\./g, " ")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** "hace 5 min" / "5m ago" — reuses the same wording as the notification bell. */
export function relativeTime(iso: string, t: AnalyticsTranslator): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return t("justNow");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("minutesAgo", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("hoursAgo", { count: hours });
  const days = Math.floor(hours / 24);
  return t("daysAgo", { count: days });
}

export function getDomainForEvent(eventType: string): string {
  return eventType.split(".")[0];
}

export function getColorForEvent(eventType: string): string {
  const prefix = getDomainForEvent(eventType);
  return DOMAIN_COLORS[prefix] || "#6b7280";
}

export function truncateId(id: string, len = 8): string {
  return id.length > len ? id.slice(0, len) + "..." : id;
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function computeDelta(
  current: number,
  previous: number | null | undefined
): { pct: number; direction: "up" | "down" | "flat" } | null {
  if (previous == null || previous === 0) return null;
  const pct = ((current - previous) / previous) * 100;
  if (Math.abs(pct) < 0.5) return { pct: 0, direction: "flat" };
  return {
    pct: Math.round(Math.abs(pct)),
    direction: pct > 0 ? "up" : "down",
  };
}

export function buildQueryString(
  period: string,
  filters: AnalyticsFilters
): string {
  const params = new URLSearchParams({ period });
  if (filters.eventType) params.set("event_type", filters.eventType);
  if (filters.countryCode) params.set("country_code", filters.countryCode);
  if (filters.domain) params.set("domain", filters.domain);
  if (filters.compare) params.set("compare", "true");
  return params.toString();
}
