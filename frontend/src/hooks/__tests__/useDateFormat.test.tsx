/**
 * # CONTRACT-TEST: a date follows the page's language, not the browser's.
 *
 * `toLocaleDateString()` with no argument follows the browser. On a Spanish
 * page read from an English system it printed `8/18/2026`, and that is not just
 * the wrong language: `5/8` reads as 5 August to a Spanish reader and means
 * 8 May. The day and the month change places silently.
 */
import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";

let locale = "en";
vi.mock("next-intl", () => ({ useLocale: () => locale }));

import { useDateFormat } from "../useDateFormat";

function formattersFor(pageLocale: string) {
  locale = pageLocale;
  return renderHook(() => useDateFormat()).result.current;
}

describe("useDateFormat", () => {
  it("puts the day and the month in the order the page's language uses", () => {
    // 8 May 2026 — the case where guessing wrong is invisible and wrong.
    const eighthOfMay = "2026-05-08T10:00:00Z";

    expect(formattersFor("en").day(eighthOfMay)).toBe("5/8/2026");
    expect(formattersFor("es").day(eighthOfMay)).toBe("8/5/2026");
  });

  it("formats each language on its own terms", () => {
    const d = "2026-05-08T10:00:00Z";
    const rendered = ["en", "es", "ca", "fr", "de"].map((l) => formattersFor(l).day(d));
    // Not a snapshot of every locale's punctuation — just that they are not all
    // the same string, which is what a browser-bound formatter would give.
    expect(new Set(rendered).size).toBeGreaterThan(1);
  });

  it("reads the API's naive-UTC timestamps as UTC", () => {
    /**
     * The backend serializes without a `Z`. Read as local time, an evening run
     * lands on the previous day for anyone west of UTC. `apiDate` is what
     * stops that, and both formatters go through it.
     */
    const withoutZ = "2026-05-08T23:30:00.123456";
    const withZ = "2026-05-08T23:30:00.123456Z";

    expect(formattersFor("es").day(withoutZ)).toBe(formattersFor("es").day(withZ));
  });

  it("shows a time as well when asked for one", () => {
    const out = formattersFor("es").dayTime("2026-05-08T10:09:07Z");
    expect(out).toContain("8/5/2026");
    // Hours and minutes at least; the separator is the locale's business.
    expect(out).toMatch(/\d{1,2}[:.]\d{2}/);
  });

  it("returns an empty string rather than 'Invalid Date'", () => {
    const f = formattersFor("es");
    expect(f.day(null)).toBe("");
    expect(f.day(undefined)).toBe("");
    expect(f.day("")).toBe("");
    expect(f.day("not a date at all")).toBe("");
    expect(f.dayTime(null)).toBe("");
  });

  it("accepts a Date as well as a string", () => {
    expect(formattersFor("es").day(new Date(Date.UTC(2026, 4, 8, 12)))).toBe("8/5/2026");
  });
});
