/**
 * Cron expression utilities for the schedule picker.
 * Maps between UI state (selected days + hour) and 5-field cron strings.
 * Standard cron day numbering: 0=Sun, 1=Mon, ..., 6=Sat.
 */

const DAY_MAP: Record<string, number> = {
  sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6,
};

const REVERSE_DAY_MAP: Record<number, string> = Object.fromEntries(
  Object.entries(DAY_MAP).map(([k, v]) => [v, k])
);

/** All day keys in display order (Monday first). */
export const DAYS_ORDERED = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

/** Build 5-field cron expression from selected days and hour. */
export function buildCronExpression(days: string[], hour: number): string {
  if (days.length === 0) throw new Error("At least one day must be selected");
  if (hour < 0 || hour > 23) throw new Error("Hour must be 0-23");
  const dayNums = days
    .map((d) => DAY_MAP[d.toLowerCase()])
    .filter((n) => n !== undefined)
    .sort((a, b) => a - b);
  return `0 ${hour} * * ${dayNums.join(",")}`;
}

/** Parse 5-field cron expression into days and hour. */
export function parseCronExpression(cron: string): { days: string[]; hour: number } {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) throw new Error("Invalid cron expression");
  const hour = parseInt(parts[1], 10);
  const dayNums = parts[4].split(",").map(Number);
  const days = dayNums.map((n) => REVERSE_DAY_MAP[n]).filter(Boolean);
  return { days, hour };
}

/**
 * Format next run as relative + absolute time using Intl APIs.
 * Returns { relative: "in 3 hours", absolute: "Mon 9:00 AM EST" }
 */
export function formatNextRun(
  isoString: string,
  locale: string
): { relative: string; absolute: string } {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffHours = Math.round(diffMs / 3600000);
  const diffDays = Math.round(diffMs / 86400000);

  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const relative =
    Math.abs(diffHours) < 48
      ? rtf.format(diffHours, "hour")
      : rtf.format(diffDays, "day");

  const absolute = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);

  return { relative, absolute };
}

/** Get all IANA timezones grouped by region. */
export function getGroupedTimezones(): Record<string, string[]> {
  const all = Intl.supportedValuesOf("timeZone");
  return all.reduce((acc, tz) => {
    const region = tz.split("/")[0];
    (acc[region] ??= []).push(tz);
    return acc;
  }, {} as Record<string, string[]>);
}

/** Get the browser's detected timezone. */
export function getBrowserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}
