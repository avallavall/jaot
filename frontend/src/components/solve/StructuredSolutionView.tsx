"use client";

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useVirtualizer } from "@tanstack/react-virtual";
import { VariableSolution, SensitivityResult } from "@/lib/types";
import { SolutionExplorerTable } from "./SolutionExplorerTable";
import {
  buildSolutionGroups,
  flattenSolutionRows,
  type SolutionLeaf,
  type SolutionRow,
} from "@/lib/solution-grouping";

/** Same near-zero threshold the flat table, chart and MCP filter use. */
const NEAR_ZERO = 1e-9;

/** Above this many rows the list is windowed inside its own scroller. Below it,
 *  the rows render straight into the page — a normal solution keeps behaving
 *  exactly as before, with no nested scrollbar and nothing to measure. */
const VIRTUALIZE_ABOVE = 40;

/** Height the windowed list starts from before rows report their real size. */
const ESTIMATED_ROW_PX = 44;

/** Viewport the virtualizer assumes for the first paint, before the browser has
 *  measured the scroller — without it the first frame would window over a
 *  zero-height viewport and flash empty. */
const INITIAL_RECT = { width: 900, height: 640 };

interface StructuredSolutionViewProps {
  variables: VariableSolution[];
  sensitivity?: SensitivityResult;
}

/**
 * Primary post-solve variable view. When the solution carries recovered index
 * structure (A1), it leads with a family → first-index grouping — the answer to
 * "what did the model decide?" — instead of a wall of identical `assign_v3_o107
 * = 1` rows. The full flat table (with constraint sensitivity) is one toggle
 * away. When no structure was recovered it renders the flat table directly, so
 * nothing regresses for continuous / custom-named / legacy solutions.
 *
 * Large solutions are WINDOWED, not truncated: only the rows near the viewport
 * are mounted, so a 20k-variable solution scrolls at full fidelity instead of
 * showing a bounded prefix behind a "show all" that then froze the page.
 */
export function StructuredSolutionView({ variables, sensitivity }: StructuredSolutionViewProps) {
  const t = useTranslations("solve.explorer");
  const [nonZeroOnly, setNonZeroOnly] = useState(true);
  const [view, setView] = useState<"grouped" | "table">("grouped");

  const hasStructure = useMemo(() => variables.some((v) => v.family), [variables]);
  const shown = useMemo(
    () => (nonZeroOnly ? variables.filter((v) => Math.abs(v.value) > NEAR_ZERO) : variables),
    [variables, nonZeroOnly],
  );
  const grouped = useMemo(() => buildSolutionGroups(shown), [shown]);
  const rows = useMemo(() => flattenSolutionRows(grouped), [grouped]);

  // No structure recovered → the grouping adds nothing. Fall back to the flat
  // table exactly as before (the graceful degradation the analysis layer relies on).
  if (!hasStructure) {
    return <SolutionExplorerTable variables={variables} sensitivity={sensitivity} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div
          className="inline-flex rounded-md border border-border overflow-hidden"
          role="group"
          aria-label={t("viewLabel")}
        >
          <button
            type="button"
            onClick={() => setView("grouped")}
            data-testid="structured-view-grouped"
            className={`px-3 py-1.5 text-sm font-medium transition-colors ${
              view === "grouped"
                ? "bg-primary text-primary-foreground"
                : "bg-background text-muted-foreground hover:bg-muted/40"
            }`}
          >
            {t("viewGrouped")}
          </button>
          <button
            type="button"
            onClick={() => setView("table")}
            data-testid="structured-view-table"
            className={`px-3 py-1.5 text-sm font-medium transition-colors border-l border-border ${
              view === "table"
                ? "bg-primary text-primary-foreground"
                : "bg-background text-muted-foreground hover:bg-muted/40"
            }`}
          >
            {t("viewTable")}
          </button>
        </div>

        {view === "grouped" && (
          <>
            <label className="flex items-center gap-1.5 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={nonZeroOnly}
                onChange={(e) => setNonZeroOnly(e.target.checked)}
                className="accent-primary w-3.5 h-3.5"
                data-testid="structured-nonzero-toggle"
              />
              <span className="text-foreground whitespace-nowrap">{t("nonZeroOnly")}</span>
            </label>
            <span className="text-xs text-muted-foreground sm:ml-auto">
              {t("showingOf", { filtered: shown.length, total: variables.length })}
            </span>
          </>
        )}
      </div>

      {view === "table" ? (
        <SolutionExplorerTable variables={variables} sensitivity={sensitivity} />
      ) : shown.length === 0 ? (
        <div className="bg-card border border-border rounded-lg px-4 py-10 text-center">
          <p className="text-sm text-muted-foreground">{t("noMatch")}</p>
        </div>
      ) : rows.length > VIRTUALIZE_ABOVE ? (
        <VirtualRows rows={rows} label={t("groupedListLabel")} t={t} />
      ) : (
        <div
          className="overflow-hidden rounded-lg border border-border bg-card"
          data-testid="structured-groups"
        >
          {rows.map((row, i) => (
            <SolutionRowView key={rowKey(row, i)} row={row} t={t} />
          ))}
        </div>
      )}
    </div>
  );
}

/** The same rows, windowed: only what is near the viewport is mounted, and each
 *  row reports its real height so wrapped chips do not drift the scrollbar. */
function VirtualRows({
  rows,
  label,
  t,
}: {
  rows: SolutionRow[];
  label: string;
  t: ReturnType<typeof useTranslations>;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // The React Compiler cannot memoize a component that drives a virtualizer (the
  // hook reads and mutates layout refs during render on purpose), so it skips
  // this one. That is expected and harmless — the windowing IS the optimization
  // here — but the skip is worth naming rather than leaving as a standing warning.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_ROW_PX,
    overscan: 8,
    initialRect: INITIAL_RECT,
  });

  return (
    <div
      ref={scrollRef}
      tabIndex={0}
      role="region"
      aria-label={label}
      data-testid="structured-groups"
      data-virtualized="true"
      className="max-h-[70vh] overflow-y-auto rounded-lg border border-border bg-card"
    >
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((item) => (
          <div
            key={item.key}
            data-index={item.index}
            ref={virtualizer.measureElement}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              transform: `translateY(${item.start}px)`,
            }}
          >
            <SolutionRowView row={rows[item.index]} t={t} />
          </div>
        ))}
      </div>
    </div>
  );
}

function rowKey(row: SolutionRow, index: number): string {
  if (row.kind === "family") return `f:${row.family}`;
  if (row.kind === "ungrouped-header") return "u:header";
  return `${row.kind}:${index}`;
}

function SolutionRowView({
  row,
  t,
}: {
  row: SolutionRow;
  t: ReturnType<typeof useTranslations>;
}) {
  if (row.kind === "family") {
    return (
      <div className="flex items-center justify-between border-b border-border bg-muted/30 px-4 py-2">
        <span className="font-mono text-sm font-semibold text-foreground">{row.family}</span>
        <span className="text-xs text-muted-foreground">
          {t("countLabel", { count: row.count })}
        </span>
      </div>
    );
  }

  if (row.kind === "ungrouped-header") {
    return (
      <div className="border-b border-border bg-muted/30 px-4 py-2">
        <span className="text-sm font-semibold text-muted-foreground">{t("otherVariables")}</span>
      </div>
    );
  }

  const indexKey = row.kind === "entries" ? row.key : null;
  const continued = row.kind === "entries" && row.continued;
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-border px-4 py-2">
      {indexKey !== null && !continued && (
        <span className="shrink-0 font-mono text-xs font-medium text-foreground">
          {indexKey}
          <span className="text-muted-foreground"> →</span>
        </span>
      )}
      <div className="flex flex-wrap gap-1.5">
        {row.entries.map((e) => (
          <EntryChip key={e.name} entry={e} />
        ))}
      </div>
    </div>
  );
}

/** A binary "selected" member shows just its label; anything else shows its
 *  value too, since the magnitude is the information there. */
function EntryChip({ entry }: { entry: SolutionLeaf }) {
  const isOnBinary = entry.type === "binary" && Math.abs(entry.value - 1) < NEAR_ZERO;
  return (
    <span
      className="inline-flex items-baseline gap-1 rounded bg-muted/50 px-1.5 py-0.5 font-mono text-xs text-foreground"
      title={entry.name}
    >
      {entry.label}
      {!isOnBinary && (
        <span className="text-muted-foreground tabular-nums">
          = {entry.value.toLocaleString(undefined, { maximumFractionDigits: 6 })}
        </span>
      )}
    </span>
  );
}
