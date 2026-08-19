"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { ComparisonDetail, ComparisonSolverResult } from "@/lib/types";
import { ComparisonCharts } from "./ComparisonCharts";
import { ComparisonExportButtons } from "./ComparisonExportButtons";
import { searchOverstatedBy, searchSecondsOf } from "./comparison-charts";
import { comparisonRows, toJson } from "./export";

/** Solver verdicts that mean a real answer came back. */
const SOLVED_STATUSES = new Set(["optimal", "feasible"]);

/**
 * A comparison is read as evidence, so this table has one rule above the rest:
 * every solver asked for gets a row, and a solver that never ran says why. An
 * empty cell in a comparison is read as zero.
 */
export function ComparisonTable({ comparison }: { comparison: ComparisonDetail }) {
  const t = useTranslations("solverCompare");
  const fastest = fastestOf(comparison);

  return (
    <div className="space-y-4">
      <ConditionsNotice comparison={comparison} />

      <ComparisonExportButtons
        // The problem's name, not the comparison id: the file lands in a
        // downloads folder next to a hundred others and has to say what it is.
        base={comparison.problem_name ?? "comparison"}
        rows={() => comparisonRows(comparison)}
        json={() => toJson(comparison)}
      />

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("table.solver")}</TableHead>
              <TableHead>{t("table.status")}</TableHead>
              <TableHead className="text-right">{t("table.objective")}</TableHead>
              <TableHead className="text-right">{t("table.bound")}</TableHead>
              <TableHead className="text-right">{t("table.gap")}</TableHead>
              <TableHead className="text-right">{t("table.time")}</TableHead>
              <TableHead className="text-right">{t("table.searchTime")}</TableHead>
              <TableHead className="text-right">{t("table.nodes")}</TableHead>
              <TableHead className="text-right">{t("table.iterations")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {comparison.results.map((row) => (
              <ResultRow
                key={row.solver_name}
                row={row}
                fastest={fastest}
                ratio={ratioOf(row, comparison)}
                overrun={overrunOf(row, comparison)}
              />
            ))}
          </TableBody>
        </Table>
      </div>

      <OverrunNotice comparison={comparison} />

      <ClockDisagreementNotice comparison={comparison} />

      <AgreementNotice comparison={comparison} />

      {/* The three things the numbers above state and cannot show: how far each
          solver was from proving its answer, how the times compare across two
          orders of magnitude, and how much of the wait was ours. */}
      <ComparisonCharts comparison={comparison} />
    </div>
  );
}

/**
 * The terms and the machine, above the numbers rather than buried under them.
 *
 * Times are comparable inside one comparison and nowhere else — the machine is
 * shared and its load is not. Saying so here is what keeps someone from putting
 * two comparisons side by side.
 */
function ConditionsNotice({ comparison }: { comparison: ComparisonDetail }) {
  const t = useTranslations("solverCompare");
  const { settings, machine_note } = comparison;

  return (
    <div className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
      <p>
        {t("conditions.terms", {
          seconds: settings.time_limit_seconds,
          gap: formatGapTolerance(settings.gap_tolerance),
          threads: settings.threads,
        })}
      </p>
      {/* The machine is rendered beside its label rather than inside a
          translated sentence, so the value itself is real text a test can
          assert on and a reader can copy. */}
      {machine_note ? (
        <p className="mt-1">
          {t("conditions.machineLabel")} <span className="font-mono">{machine_note}</span>
        </p>
      ) : null}
      {comparison.problem_class ? (
        <p>
          {t("conditions.problem", {
            problemClass: comparison.problem_class,
            variables: comparison.variable_count ?? 0,
            constraints: comparison.constraint_count ?? 0,
          })}
        </p>
      ) : null}
      <p className="mt-1">{t("conditions.scope")}</p>
      {/* Nodes and iterations are each solver's own count of its own work. They
          survive a busy machine, which is why they are here at all, but they are
          not the same quantity from one solver to the next. */}
      <p className="mt-1">{t("conditions.counters")}</p>
    </div>
  );
}

function ResultRow({
  row,
  fastest,
  ratio,
  overrun,
}: {
  row: ComparisonSolverResult;
  fastest: string | null;
  /** This row's total time divided by the quickest one's, or null when there is
   * nothing to compare it against. */
  ratio: number | null;
  /** Seconds this solver searched past the shared limit, or null when it kept
   * to it. */
  overrun: number | null;
}) {
  const t = useTranslations("solverCompare");
  const unsupported = row.solver_status === "unsupported";

  return (
    <TableRow className={cn(unsupported && "text-muted-foreground")}>
      <TableCell className="font-medium">
        <span className="uppercase">{row.solver_name}</span>
        {/* The version the row was measured against. Without it a table stored
            today cannot be explained once the images have been rebuilt: seconds
            from CBC 2.10.12 say nothing about 2.11. Absent on a row recorded
            before this was kept, which reads as "not recorded", not as zero. */}
        {row.solver_version ? (
          <span className="ml-1.5 font-normal text-xs text-muted-foreground tabular-nums">
            {row.solver_version}
          </span>
        ) : null}
        {row.solver_name === fastest ? (
          <Badge variant="secondary" className="ml-2">
            {t("table.fastest")}
          </Badge>
        ) : null}
      </TableCell>
      <TableCell>
        <StatusCell row={row} />
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {formatNumber(row.objective_value)}
      </TableCell>
      <TableCell className="text-right tabular-nums">{formatNumber(row.dual_bound)}</TableCell>
      <TableCell className="text-right tabular-nums">{formatGap(row.gap)}</TableCell>
      <TableCell className="text-right tabular-nums">
        {formatMs(row.wall_time_ms)}
        {/* How much slower than the quickest that answered. A ratio is what a
            reader actually wants from two timings side by side. */}
        {ratio !== null && ratio > 1.05 ? (
          <span className="ml-1 text-muted-foreground">
            ({ratio.toLocaleString(undefined, { maximumFractionDigits: 1 })}×)
          </span>
        ) : null}
      </TableCell>
      <TableCell
        className={cn(
          "text-right tabular-nums",
          overrun !== null && "text-amber-700 dark:text-amber-400",
        )}
      >
        {formatSeconds(searchSecondsOf(row))}
      </TableCell>
      <TableCell className="text-right tabular-nums">{formatCount(row.nodes)}</TableCell>
      <TableCell className="text-right tabular-nums">{formatCount(row.iterations)}</TableCell>
    </TableRow>
  );
}

/**
 * What this solver did, in words.
 *
 * "Not supported" is a first-class outcome, not an error: the solver is working
 * exactly as designed and simply cannot express this model. It reads differently
 * from a solver that broke, and the reason is spelled out either way.
 */
function StatusCell({ row }: { row: ComparisonSolverResult }) {
  const t = useTranslations("solverCompare");

  if (row.solver_status === "unsupported") {
    return (
      <div>
        <Badge variant="outline">{t("status.unsupported")}</Badge>
        <p className="mt-1 text-xs">
          {row.unsupported_reason
            ? t(`unsupportedReason.${row.unsupported_reason}`)
            : row.error_message}
        </p>
      </div>
    );
  }

  if (row.status === "pending" || row.status === "running") {
    return <Badge variant="secondary">{t(`status.${row.status}`)}</Badge>;
  }

  if (row.status === "cancelled") {
    return <Badge variant="outline">{t("status.cancelled")}</Badge>;
  }

  if (row.solver_status && SOLVED_STATUSES.has(row.solver_status)) {
    return <Badge variant="default">{t(`status.${row.solver_status}`)}</Badge>;
  }

  return (
    <div>
      <Badge variant="destructive">
        {row.solver_status ? t(`status.${row.solver_status}`) : t("status.failed")}
      </Badge>
      {row.error_message ? <p className="mt-1 text-xs">{row.error_message}</p> : null}
    </div>
  );
}

/**
 * Names every solver whose own search ran well past the shared time limit.
 *
 * The conditions notice above the table promises identical terms, and CBC in
 * particular does not keep them: it counts CPU seconds and checks the clock
 * only between nodes, so it can search seconds past the limit it was given.
 * A row like that is slower partly because it was allowed to run longer, and
 * without this notice the table presents that extra time as a fair loss.
 */
function OverrunNotice({ comparison }: { comparison: ComparisonDetail }) {
  const t = useTranslations("solverCompare");
  const offenders = comparison.results
    .map((row) => ({ row, overrun: overrunOf(row, comparison) }))
    .filter((o): o is { row: ComparisonSolverResult; overrun: number } => o.overrun !== null);
  if (offenders.length === 0) return null;

  return (
    <div className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
      {offenders.map(({ row, overrun }) => (
        <p key={row.solver_name}>
          {t("overrun.notice", {
            solver: row.solver_name.toUpperCase(),
            overrun: formatSeconds(overrun),
          })}
        </p>
      ))}
    </div>
  );
}

/**
 * Seconds this row searched past the shared limit, or null when it kept to it.
 *
 * Solvers check their clocks with different granularity — SCIP and HiGHS land
 * within hundredths of the limit, which is keeping the terms, not breaking
 * them. The allowance below flags whole extra seconds of search, never
 * stopping precision.
 */
export function overrunOf(
  row: ComparisonSolverResult,
  comparison: ComparisonDetail,
): number | null {
  const limit = comparison.settings.time_limit_seconds;
  if (row.solver_time_seconds === null || limit <= 0) return null;
  const allowance = Math.max(0.5, limit * 0.1);
  const overrun = row.solver_time_seconds - limit;
  return overrun > allowance ? overrun : null;
}

/**
 * Names the rows whose two timings do not agree.
 *
 * The notice above the table says the difference between Time and Search is
 * what the solver spent building its model. When the search comes back longer
 * than the run that contains it, that difference is a negative number and the
 * sentence is wrong for that row. The Search cell shows the wall time instead,
 * so the arithmetic holds; this line says the cell was capped and by how much,
 * because a corrected measurement that says nothing is worse than a wrong one.
 */
function ClockDisagreementNotice({ comparison }: { comparison: ComparisonDetail }) {
  const t = useTranslations("solverCompare");
  const affected = comparison.results
    .map((row) => ({ row, excess: searchOverstatedBy(row) }))
    .filter((o): o is { row: ComparisonSolverResult; excess: number } => o.excess !== null);
  if (affected.length === 0) return null;

  return (
    <div
      className="space-y-1 rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground"
      data-testid="comparison-clock-disagreement"
    >
      {affected.map(({ row, excess }) => (
        <p key={row.solver_name}>
          {t("clockDisagreement.notice", {
            solver: row.solver_name.toUpperCase(),
            excess: formatSeconds(excess),
          })}
        </p>
      ))}
    </div>
  );
}

/**
 * Whether the solvers that finished agree.
 *
 * The case worth naming is the last one: identical objectives with different
 * variable values. Both solvers are right and the problem has more than one
 * optimal solution. Without saying it, a reader sees two different answers and
 * concludes one solver is broken.
 */
function AgreementNotice({ comparison }: { comparison: ComparisonDetail }) {
  const t = useTranslations("solverCompare");
  const agreement = comparison.agreement;
  if (!agreement || agreement.compared_solvers.length < 2) return null;

  if (agreement.objectives_agree === false) {
    return (
      <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
        {t("agreement.objectivesDiffer", {
          delta: formatNumber(agreement.max_objective_delta),
        })}
      </p>
    );
  }

  if (agreement.alternative_optima) {
    return (
      <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
        {t("agreement.alternativeOptima")}
      </p>
    );
  }

  if (agreement.solutions_identical) {
    return (
      <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
        {t("agreement.identical", { count: agreement.compared_solvers.length })}
      </p>
    );
  }

  return null;
}

/** The quickest solver that actually produced an answer, or null when fewer
 * than two did — one result cannot be the fastest of anything. */
export function fastestOf(comparison: ComparisonDetail): string | null {
  const solved = comparison.results.filter(
    (r) =>
      r.solver_status !== null &&
      SOLVED_STATUSES.has(r.solver_status) &&
      r.wall_time_ms !== null,
  );
  if (solved.length < 2) return null;
  return solved.reduce((best, r) =>
    (r.wall_time_ms ?? Infinity) < (best.wall_time_ms ?? Infinity) ? r : best,
  ).solver_name;
}

/** How many times slower this row was than the quickest that answered. */
export function ratioOf(row: ComparisonSolverResult, comparison: ComparisonDetail): number | null {
  const best = bestTimeOf(comparison);
  if (best === null || best <= 0 || row.wall_time_ms === null) return null;
  if (row.solver_status === null || !SOLVED_STATUSES.has(row.solver_status)) return null;
  return row.wall_time_ms / best;
}

function bestTimeOf(comparison: ComparisonDetail): number | null {
  const times = comparison.results
    .filter((r) => r.solver_status !== null && SOLVED_STATUSES.has(r.solver_status))
    .map((r) => r.wall_time_ms)
    .filter((t): t is number => t !== null);
  if (times.length < 2) return null;
  return Math.min(...times);
}

function formatSeconds(value: number | null): string {
  if (value === null || value === undefined) return "—";
  if (value < 0.001) return "<1 ms";
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} s`;
}

function formatNumber(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatCount(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString();
}

function formatGap(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
}

function formatGapTolerance(value: number): string {
  return `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 4 })}%`;
}

function formatMs(value: number | null): string {
  if (value === null || value === undefined) return "—";
  // "0 ms" reads as "took no time", which is not what a sub-millisecond solve
  // means and makes the rest of the row look unmeasured.
  if (value < 1) return "<1 ms";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toLocaleString(undefined, { maximumFractionDigits: 2 })} s`;
}
