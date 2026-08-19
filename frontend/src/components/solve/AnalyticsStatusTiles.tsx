"use client";

import { useTranslations } from "next-intl";

/**
 * The row of counts under "Total Executions" on the analytics page.
 *
 * It showed three of the six statuses a run can be in, so the parts did not
 * account for the whole: Completed 972 + Failed 27 + Timed Out 0 came to 999
 * under a Total Executions of 1,002, and the three cancelled runs had nowhere
 * to be. Cancelled, Running and Pending appear as soon as a run is in one.
 */

/** Every status a run can hold, in the order they are worth reading. Mirrors
 * `ExecutionStatus` in `app/models/optimization_model.py`. */
const STATUS_TILES = [
  { status: "completed", labelKey: "completed", className: "text-green-600" },
  { status: "failed", labelKey: "failed", className: "text-red-600" },
  { status: "timeout", labelKey: "timedOut", className: "text-yellow-600" },
  { status: "cancelled", labelKey: "cancelled", className: "text-muted-foreground" },
  { status: "running", labelKey: "running", className: "text-blue-600" },
  { status: "pending", labelKey: "pending", className: "text-muted-foreground" },
] as const;

/** The three that are always shown, even at zero, so the row does not jump
 * around between periods. The rest appear only when they hold a run. */
const ALWAYS_SHOWN = new Set(["completed", "failed", "timeout"]);

export interface AnalyticsStatusTilesProps {
  /** Count per status, as the summary endpoint returns it. */
  byStatus: Record<string, number> | undefined;
}

export function AnalyticsStatusTiles({ byStatus }: AnalyticsStatusTilesProps) {
  const t = useTranslations("solve.analytics");

  return (
    <>
      {STATUS_TILES.map(({ status, labelKey, className }) => {
        const count = byStatus?.[status] ?? 0;
        if (count === 0 && !ALWAYS_SHOWN.has(status)) return null;
        return (
          <div
            key={status}
            className="bg-card border border-border rounded-lg p-3 text-center"
            data-testid={`analytics-tile-${status}`}
          >
            <div className="text-xs text-muted-foreground">{t(labelKey)}</div>
            <div className={`text-lg font-semibold ${className}`}>{count}</div>
          </div>
        );
      })}
    </>
  );
}
