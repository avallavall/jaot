import type { ComparisonDetail } from "@/lib/types";

/** Execution states with something still to happen. The matrix reads this too:
 * one definition of "still going" for both comparison surfaces. */
export const LIVE_STATUSES = new Set(["pending", "running"]);

/**
 * Whether the page should keep asking the server for a fresher table.
 *
 * Not simply "is the comparison running". Stopping a comparison marks the
 * comparison itself cancelled straight away, but the solve already inside a
 * solver cannot be interrupted: the worker finishes it and writes its real
 * verdict a few seconds later. Polling on the parent alone stopped at the click
 * and left that column reading "Running" until the user reloaded the page.
 *
 * So the parent's state is not enough — a row that has not reached a verdict
 * keeps the polling alive on its own.
 */
export function shouldKeepPolling(comparison: ComparisonDetail | null): boolean {
  if (!comparison) return false;
  if (LIVE_STATUSES.has(comparison.status)) return true;
  return comparison.results.some((row) => LIVE_STATUSES.has(row.status));
}

/** Whether the user can still stop this comparison.
 *
 * Only while the comparison itself is live. Once it is cancelled there is
 * nothing left to stop, even though a column may still be finishing.
 */
export function canStop(comparison: ComparisonDetail | null): boolean {
  return comparison !== null && LIVE_STATUSES.has(comparison.status);
}
