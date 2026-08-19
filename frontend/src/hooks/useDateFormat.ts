"use client";

import { useMemo } from "react";
import { useLocale } from "next-intl";

import { apiDate } from "@/lib/dates";

/**
 * Date formatting bound to the page's language, not the browser's.
 *
 * `toLocaleDateString()` with no argument follows the browser. Someone reading
 * the app in Spanish on an English system was shown `8/18/2026` — and that is
 * not merely the wrong language, it is a different date: `5/8` reads as 5
 * August to them and means 8 May. Every screen in the product went through
 * that call.
 *
 * Both formatters accept the API's naive-UTC strings and route them through
 * `apiDate`, so a timestamp without a `Z` is not read as local time.
 */
export interface DateFormatters {
  /** Day only, in the page's language. Empty string for a missing date. */
  day(value: string | Date | null | undefined): string;
  /** Day and time, in the page's language. Empty string for a missing date. */
  dayTime(value: string | Date | null | undefined): string;
}

function toDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = typeof value === "string" ? apiDate(value) : value;
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Same fields `toLocaleString()` shows by default, so this is a drop-in. */
const DAY_TIME: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "numeric",
  second: "numeric",
};

export function useDateFormat(): DateFormatters {
  const locale = useLocale();

  return useMemo(() => {
    const dayFormat = new Intl.DateTimeFormat(locale);
    const dayTimeFormat = new Intl.DateTimeFormat(locale, DAY_TIME);
    return {
      day(value) {
        const d = toDate(value);
        return d ? dayFormat.format(d) : "";
      },
      dayTime(value) {
        const d = toDate(value);
        return d ? dayTimeFormat.format(d) : "";
      },
    };
  }, [locale]);
}
