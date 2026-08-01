import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  EVENT_TYPES,
  formatEventType,
  relativeTime,
  type AnalyticsTranslator,
} from "../analytics-helpers";

/**
 * The Feature Analytics screen showed event types as title-cased wire values —
 * "Solver Solve", "Marketplace Activate" — under a translated heading. They are
 * named from the locale files now, and an unknown type still degrades to
 * something readable rather than to a key.
 */

function translator(messages: Record<string, string>): AnalyticsTranslator {
  return Object.assign(
    (key: string, values?: Record<string, string | number>): string =>
      (messages[key] ?? key).replace(/\{(\w+)\}/g, (_, n) => String(values?.[n] ?? `{${n}}`)),
    { has: (key: string) => key in messages },
  ) as AnalyticsTranslator;
}

describe("formatEventType", () => {
  const t = translator({ "eventTypes.solver.solve": "Resolución" });

  it("names a known event type from the locale file", () => {
    expect(formatEventType("solver.solve", t)).toBe("Resolución");
  });

  it("falls back to readable title case for a type with no translation", () => {
    expect(formatEventType("billing.invoice_paid", t)).toBe("Billing Invoice Paid");
  });

  it("still works with no translator at all", () => {
    expect(formatEventType("marketplace.activate")).toBe("Marketplace Activate");
  });
});

describe("relativeTime", () => {
  const t = translator({
    justNow: "ahora mismo",
    minutesAgo: "hace {count} min",
    hoursAgo: "hace {count} h",
    daysAgo: "hace {count} d",
  });
  const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString();

  it("uses the same wording as the notification bell", () => {
    expect(relativeTime(iso(5_000), t)).toBe("ahora mismo");
    expect(relativeTime(iso(5 * 60_000), t)).toBe("hace 5 min");
    expect(relativeTime(iso(3 * 3_600_000), t)).toBe("hace 3 h");
    expect(relativeTime(iso(2 * 86_400_000), t)).toBe("hace 2 d");
  });
});

describe("feature analytics translations", () => {
  const LOCALES = ["en", "es", "ca", "fr", "de"];

  // CONTRACT-TEST: the entries must be NESTED, because next-intl splits a key on
  // dots — a flat "solver.solve" entry is unreachable and silently falls back to
  // the title-cased wire value, which is what shipped and what QA saw on screen.
  it.each(LOCALES)("%s names every event type the filters offer", (locale) => {
    const m = JSON.parse(readFileSync(join(process.cwd(), "messages", `${locale}.json`), "utf8"));
    const types = m.admin.featureAnalytics.eventTypes;
    const missing = EVENT_TYPES.filter((et) => {
      const [group, leaf] = et.split(".");
      return typeof types?.[group]?.[leaf] !== "string";
    });
    expect(missing).toEqual([]);
  });
});
