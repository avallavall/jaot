"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { ComparisonBatchDetail, ComparisonMatrixRow } from "@/lib/types";
import {
  type Heat,
  type MatrixCell,
  type MatrixMetric,
  bestInRow,
  cellOf,
  heatOf,
} from "./matrix-metrics";

/** How far behind the best of its row, as colour. Four steps, one ramp. */
const HEAT_CLASS: Record<Heat, string> = {
  best: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  close: "bg-emerald-50/60 dark:bg-emerald-950/40",
  behind: "bg-amber-50 text-amber-900 dark:bg-amber-950/50 dark:text-amber-200",
  far: "bg-red-50 text-red-900 dark:bg-red-950/50 dark:text-red-200",
};

interface MatrixTableProps {
  batch: ComparisonBatchDetail;
  metric: MatrixMetric;
  /** The row whose full comparison is open below the grid. */
  openRow: string | null;
  onOpenRow: (comparisonId: string) => void;
}

/**
 * The grid: datasets down the side, solvers across the top.
 *
 * Every cell that holds no number says WHY — not supported, still waiting,
 * failed, stopped. A blank cell in a comparison is read as zero, and zero
 * seconds is the best possible score.
 */
export function MatrixTable({ batch, metric, openRow, onOpenRow }: MatrixTableProps) {
  const t = useTranslations("studio");

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm" data-testid="studio-matrix-table">
        <thead>
          <tr className="border-b text-xs uppercase tracking-wider text-muted-foreground">
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t("matrix.colDataset")}
            </th>
            {batch.solver_names.map((solver) => (
              <th key={solver} scope="col" className="px-3 py-2 text-right font-medium">
                {solver.toUpperCase()}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {batch.rows.map((row) => (
            <MatrixRow
              key={row.comparison_id}
              row={row}
              solvers={batch.solver_names}
              metric={metric}
              open={openRow === row.comparison_id}
              onOpen={() => onOpenRow(row.comparison_id)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MatrixRow({
  row,
  solvers,
  metric,
  open,
  onOpen,
}: {
  row: ComparisonMatrixRow;
  solvers: string[];
  metric: MatrixMetric;
  open: boolean;
  onOpen: () => void;
}) {
  const t = useTranslations("studio");
  const byName = new Map(row.results.map((result) => [result.solver_name, result]));
  const cells = solvers.map((solver) => {
    const result = byName.get(solver);
    return result ? cellOf(result, metric) : null;
  });
  const best = bestInRow(cells.filter((cell): cell is MatrixCell => cell !== null), metric);

  return (
    <tr
      className={cn("border-b last:border-0", open && "bg-accent/40")}
      data-testid="studio-matrix-row"
    >
      <th scope="row" className="px-3 py-2 text-left font-medium">
        <button
          type="button"
          onClick={onOpen}
          className="text-left underline-offset-2 hover:underline"
          data-testid="studio-matrix-open-row"
        >
          {row.dataset_name ?? row.comparison_id}
        </button>
        {/* The compiled size belongs next to the row: the same model grounds to
            a different problem per dataset, and that is usually the answer to
            why one row took ten times longer than the one above it. */}
        {row.variable_count !== null ? (
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {t("matrix.rowSize", {
              problemClass: row.problem_class ?? "",
              variables: row.variable_count,
            })}
          </span>
        ) : null}
      </th>
      {cells.map((cell, index) => (
        <Cell key={solvers[index]} cell={cell} best={best} metric={metric} />
      ))}
    </tr>
  );
}

function Cell({
  cell,
  best,
  metric,
}: {
  cell: MatrixCell | null;
  best: number | null;
  metric: MatrixMetric;
}) {
  const t = useTranslations("studio");
  // The four "why this solver sat it out" sentences are the comparer's, and one
  // wording of them is enough for both surfaces.
  const tCompare = useTranslations("solverCompare");

  if (cell === null) {
    return <td className="px-3 py-2 text-right text-muted-foreground">·</td>;
  }

  const heat = heatOf(cell, best, metric);
  const className = cn(
    "px-3 py-2 text-right font-mono tabular-nums",
    heat ? HEAT_CLASS[heat] : undefined,
  );

  switch (cell.kind) {
    case "value":
      return (
        <td className={className} data-testid="studio-matrix-cell">
          {formatMetric(cell.value as number, metric)}
        </td>
      );
    case "waiting":
      return (
        <td className={className} data-testid="studio-matrix-cell">
          <span className="inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-muted-foreground/60 align-middle" />
          <span className="sr-only">{t("matrix.cellWaiting")}</span>
        </td>
      );
    case "unsupported":
      return (
        <td
          className={cn(className, "text-muted-foreground")}
          title={tCompare(`unsupportedReason.${cell.reason ?? "not_available"}`)}
          data-testid="studio-matrix-cell"
        >
          {t("matrix.cellUnsupported")}
        </td>
      );
    case "failed":
      return (
        <td
          className={cn(className, "text-destructive")}
          title={cell.error ?? undefined}
          data-testid="studio-matrix-cell"
        >
          {t("matrix.cellFailed")}
        </td>
      );
    case "cancelled":
      return (
        <td className={cn(className, "text-muted-foreground")} data-testid="studio-matrix-cell">
          {t("matrix.cellCancelled")}
        </td>
      );
    case "none":
      return (
        <td
          className={cn(className, "text-muted-foreground")}
          title={t("matrix.cellNoValue")}
          data-testid="studio-matrix-cell"
        >
          ·
        </td>
      );
  }
}

/** Numbers follow the reader's own locale, as they do everywhere in the app. */
export function formatMetric(value: number, metric: MatrixMetric): string {
  switch (metric) {
    case "time":
      return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} s`;
    case "gap":
      return `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
    case "objective":
      return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
    case "nodes":
    case "iterations":
      return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
}
