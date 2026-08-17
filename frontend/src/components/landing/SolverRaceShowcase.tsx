import { getFormatter, getTranslations } from "next-intl/server";
import { cn } from "@/lib/utils";
import { COMPARISON_META, COMPARISON_ROWS } from "./data/comparisonShowcase";

/**
 * The same plan, run by all four solvers under the same terms.
 *
 * Every other section on this page shows what JAOT does with a model. This one
 * shows the choice underneath it: there is no best solver, and the ranking
 * changes with the model. The numbers are real
 * (scripts/gen_landing_comparison.py drives the same adapters the comparer
 * uses) on a quarter's burn-in chamber plan for the plant the rest of the page
 * already solves.
 *
 * The bar is drawn on a logarithmic scale, for the same reason the product's
 * own chart is: this run spans 1.5 seconds to a minute, and on a linear axis
 * every solver but the slowest is a hairline against the left edge. The number
 * is written next to each bar, because on a log scale the length is not
 * proportional to it.
 *
 * A solver that ran out of time keeps its row and its bar, marked. Dropping it
 * would read as "that solver was not asked", which is the opposite of what
 * happened — it is the one fact this section exists to show.
 *
 * Server Component: no client JavaScript.
 */
export async function SolverRaceShowcase() {
  const t = await getTranslations("public.solverRace");
  const format = await getFormatter();

  const answered = COMPARISON_ROWS.filter((row) => row.slowdown !== null);
  const winner = answered.reduce((best, row) => (row.wallMs < best.wallMs ? row : best));
  const slowestAnswer = answered.reduce((worst, row) =>
    row.wallMs > worst.wallMs ? row : worst,
  );
  const cutOff = COMPARISON_ROWS.filter((row) => row.slowdown === null);

  // Log scale, floored at the quickest run so the shortest bar is still visible.
  const maxMs = Math.max(...COMPARISON_ROWS.map((row) => row.wallMs));
  const minMs = Math.min(...COMPARISON_ROWS.map((row) => row.wallMs));
  const span = Math.log10(maxMs) - Math.log10(minMs) || 1;
  const widthOf = (ms: number) => 8 + ((Math.log10(ms) - Math.log10(minMs)) / span) * 92;

  const seconds = (ms: number) =>
    format.number(ms / 1000, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className="border border-border bg-card p-6 sm:p-8">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h3 className="font-mono text-[0.6875rem] uppercase tracking-widest text-muted-foreground">
          {t("chartHeading")}
        </h3>
        <span className="font-mono text-[0.6875rem] text-muted-foreground">
          {t("instance", {
            variables: format.number(COMPARISON_META.variables),
            constraints: format.number(COMPARISON_META.constraints),
          })}
        </span>
      </div>

      <ul className="mt-8 space-y-6">
        {COMPARISON_ROWS.map((row) => {
          const timedOut = row.slowdown === null;
          return (
            <li key={row.solver}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="font-mono text-sm uppercase tracking-wide text-foreground">
                  {row.solver}
                </span>
                <span
                  className={cn(
                    "font-mono text-xs tabular-nums",
                    timedOut ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  {timedOut
                    ? t("outOfTime")
                    : t("proved", { objective: format.number(row.objective ?? 0) })}
                </span>
              </div>

              <div className="mt-2 flex items-center gap-3">
                <div className="h-2 flex-1 bg-muted">
                  <div
                    className={cn("h-full", timedOut ? "bg-primary/40" : "bg-accent")}
                    style={{ width: `${widthOf(row.wallMs)}%` }}
                  />
                </div>
                <span className="w-20 shrink-0 text-right font-mono text-xs tabular-nums text-foreground">
                  {t("seconds", { seconds: seconds(row.wallMs) })}
                </span>
              </div>

              <p className="mt-1.5 font-mono text-[0.6875rem] text-muted-foreground">
                {timedOut
                  ? t("rowCutOff", {
                      bound: format.number(row.bound ?? 0),
                      nodes: format.number(row.nodes ?? 0),
                    })
                  : t("rowWork", {
                      nodes: format.number(row.nodes ?? 0),
                      iterations: format.number(row.iterations ?? 0),
                    })}
              </p>
            </li>
          );
        })}
      </ul>

      <p className="mt-6 font-mono text-[0.6875rem] leading-relaxed text-muted-foreground">
        {t("scaleNote")}
      </p>

      <div className="mt-8 space-y-3 border-t border-border pt-5 text-sm leading-relaxed text-muted-foreground">
        <p>
          {t("verdict", {
            winner: winner.solver,
            slowest: slowestAnswer.solver,
            ratio: format.number(slowestAnswer.slowdown ?? 0, {
              minimumFractionDigits: 1,
              maximumFractionDigits: 1,
            }),
          })}
        </p>
        {cutOff.length > 0 && (
          <p>
            {t("cutOffNote", {
              solvers: cutOff.map((row) => row.solver).join(", "),
              limit: format.number(COMPARISON_META.timeLimitSeconds),
              bound: format.number(cutOff[0].bound ?? 0),
            })}
          </p>
        )}
        <p>
          {t("terms", {
            limit: format.number(COMPARISON_META.timeLimitSeconds),
            threads: COMPARISON_META.threads,
            cores: COMPARISON_META.cores,
          })}
        </p>
      </div>
    </div>
  );
}
