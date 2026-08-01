"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import type { DecisionScenario, RhsScenario, ScenarioAnalysisJob } from "@/lib/types";
import { AdvancedModelToggle } from "@/components/llm/AdvancedModelToggle";
import { useAdvancedModel } from "@/hooks/useAdvancedModel";

interface ScenarioAnalysisSectionProps {
  executionId: string;
}

const POLL_MS = 5000;
const NEAR_ZERO = 1e-9;

/**
 * What-if analysis by real re-solves (Sensitivity L2). Where the exact analysis
 * above reads the solution you already have, this one perturbs the model and
 * solves it again: how much one more unit of a binding constraint is really
 * worth, and what it costs to overrule a decision. That is minutes of solving,
 * so it is opt-in, runs on a worker, and reports a truncated batch as truncated.
 */
export function ScenarioAnalysisSection({ executionId }: ScenarioAnalysisSectionProps) {
  const t = useTranslations("solve.execution.scenarioAnalysis");
  const [job, setJob] = useState<ScenarioAnalysisJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    cancelled.current = false;
    api
      .getExecutionScenarioAnalysis(executionId)
      .then((res) => {
        if (!cancelled.current) setJob(res);
      })
      .catch(() => {
        // A read failure here is not worth a banner: the CTA below still works,
        // and starting the batch surfaces any real problem.
      });
    return () => {
      cancelled.current = true;
    };
  }, [executionId]);

  const running = job?.status === "running";

  useEffect(() => {
    if (!running) return;
    const handle = setInterval(() => {
      api
        .getExecutionScenarioAnalysis(executionId)
        .then((res) => {
          if (!cancelled.current) setJob(res);
        })
        .catch(() => {
          /* transient poll failures keep the previous state */
        });
    }, POLL_MS);
    return () => clearInterval(handle);
  }, [running, executionId]);

  const start = useCallback(() => {
    setStarting(true);
    setError(null);
    api
      .startExecutionScenarioAnalysis(executionId)
      .then((res) => {
        if (!cancelled.current) setJob(res);
      })
      .catch((err: unknown) => {
        if (!cancelled.current) setError(getErrorMessage(err, t("error")));
      })
      .finally(() => {
        if (!cancelled.current) setStarting(false);
      });
  }, [executionId, t]);

  const analysis = job?.status === "completed" ? job.analysis : null;

  return (
    <div className="space-y-3" data-testid="scenario-analysis">
      <div>
        <h3 className="mb-1 text-sm font-semibold text-foreground">{t("title")}</h3>
        <p className="text-xs text-muted-foreground">{t("intro")}</p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {job?.status === "failed" && job.error && (
        <p className="text-sm text-destructive">{job.error}</p>
      )}

      {running && (
        <p className="text-sm text-muted-foreground" data-testid="scenario-analysis-running">
          {/* The batch can run for minutes. Until the first scenario lands there
              is nothing to count, so the generic line stands; after that the
              count is what distinguishes "still working" from "hung". */}
          {job?.progress
            ? t("runningProgress", {
                done: job.progress.done,
                planned: job.progress.planned,
              })
            : t("running")}
        </p>
      )}

      {!running && !analysis && (
        <button
          type="button"
          onClick={start}
          disabled={starting}
          data-testid="scenario-analysis-start"
          className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted/50 disabled:opacity-50"
        >
          {starting ? t("starting") : t("cta")}
        </button>
      )}

      {analysis && !analysis.computed && (
        <p className="text-sm text-muted-foreground">
          {analysis.note === "no_scenarios" ? t("noScenarios") : t("noBaseObjective")}
        </p>
      )}

      {analysis?.computed && (
        <div className="space-y-5">
          <BudgetSummary job={job} t={t} />
          <TornadoChart rows={analysis.rhs_scenarios ?? []} t={t} />
          <RegretTable rows={analysis.decision_scenarios ?? []} t={t} />
          <ScenarioExplanation
            executionId={executionId}
            cached={job?.explanation ?? null}
            t={t}
          />
        </div>
      )}
    </div>
  );
}

function BudgetSummary({
  job,
  t,
}: {
  job: ScenarioAnalysisJob | null;
  t: ReturnType<typeof useTranslations>;
}) {
  const analysis = job?.analysis;
  if (!analysis) return null;
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <p className="text-xs text-muted-foreground">
        {t("budgetSummary", {
          used: analysis.resolves_used ?? 0,
          planned: analysis.resolves_planned ?? 0,
          seconds: Math.round(analysis.seconds_used ?? 0),
        })}
      </p>
      {analysis.partial && (
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-400" data-testid="scenario-partial">
          {t("partialNotice")}
        </p>
      )}
    </div>
  );
}

/** Divergent bars around a zero axis: improvements right, costs left, each row
 * normalised per unit of RHS so constraints with different δ stay comparable. */
function TornadoChart({
  rows,
  t,
}: {
  rows: RhsScenario[];
  t: ReturnType<typeof useTranslations>;
}) {
  const shown = useMemo(() => {
    const solved = rows.filter(
      (r) => r.status === "computed" || r.status === "time_limit" || r.status === "infeasible",
    );
    return [...solved].sort(
      (a, b) =>
        Math.abs(b.objective_delta_per_unit ?? 0) - Math.abs(a.objective_delta_per_unit ?? 0),
    );
  }, [rows]);

  const max = useMemo(
    () => Math.max(...shown.map((r) => Math.abs(r.objective_delta_per_unit ?? 0)), NEAR_ZERO),
    [shown],
  );

  if (shown.length === 0) return null;

  return (
    <div data-testid="scenario-tornado">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("tornadoTitle")}
      </h4>
      <div className="space-y-1.5">
        {shown.map((row) => (
          <TornadoRow key={`${row.constraint}-${row.direction}`} row={row} max={max} t={t} />
        ))}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{t("tornadoNote")}</p>
    </div>
  );
}

function TornadoRow({
  row,
  max,
  t,
}: {
  row: RhsScenario;
  max: number;
  t: ReturnType<typeof useTranslations>;
}) {
  const perUnit = row.objective_delta_per_unit ?? 0;
  const width = (Math.abs(perUnit) / max) * 50;
  const improves = row.improves === true;
  // An equality has no slack to give, so "relax/tighten" would be a lie there —
  // it reads as the RHS moving up or down instead.
  const directionLabel = row.is_equality
    ? row.rhs_new > row.rhs
      ? t("increase")
      : t("decrease")
    : row.direction === "relax"
      ? t("relax")
      : t("tighten");

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-44 shrink-0 truncate font-mono text-foreground" title={row.constraint}>
        {row.constraint}
        <span className="ml-1 text-muted-foreground">{directionLabel}</span>
      </span>
      <div className="relative h-4 flex-1 rounded bg-muted/40">
        <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
        {row.status !== "infeasible" && (
          <div
            className={`absolute inset-y-0 rounded ${
              improves ? "bg-green-500/70" : "bg-red-500/60"
            } ${row.status === "time_limit" ? "opacity-50" : ""}`}
            style={
              perUnit >= 0
                ? { left: "50%", width: `${width}%` }
                : { right: "50%", width: `${width}%` }
            }
          />
        )}
      </div>
      <span className="w-28 shrink-0 text-right font-mono tabular-nums text-muted-foreground">
        {row.status === "infeasible" ? (
          t("statusInfeasible")
        ) : (
          <>
            {row.status === "time_limit" && <span title={t("statusTimeLimit")}>≈ </span>}
            {fmt(perUnit)}
          </>
        )}
      </span>
    </div>
  );
}

function RegretTable({
  rows,
  t,
}: {
  rows: DecisionScenario[];
  t: ReturnType<typeof useTranslations>;
}) {
  const shown = rows.filter((r) => r.status !== "skipped_budget");
  if (shown.length === 0) return null;

  return (
    <div data-testid="scenario-regret">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("regretTitle")}
      </h4>
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                {t("decisionHeader")}
              </th>
              <th className="px-3 py-2 text-center font-medium text-muted-foreground">
                {t("overruleHeader")}
              </th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                {t("regretHeader")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {shown.map((row) => (
              <tr key={row.variable}>
                <td className="max-w-[220px] truncate px-3 py-1.5 font-mono text-xs text-foreground">
                  {row.variable}
                </td>
                <td className="px-3 py-1.5 text-center font-mono text-xs tabular-nums text-muted-foreground">
                  {fmt(row.original_value)} → {fmt(row.forced_value)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                  {row.status === "infeasible" ? (
                    <span className="text-muted-foreground">{t("statusInfeasible")}</span>
                  ) : row.regret == null ? (
                    <span className="text-muted-foreground">—</span>
                  ) : (
                    <>
                      {row.status === "time_limit" && <span title={t("statusTimeLimit")}>≈ </span>}
                      {fmt(row.regret)}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{t("regretNote")}</p>
    </div>
  );
}

/** Plain-language reading of the measured scenarios, on demand.
 *
 * Opt-in for the same reason the batch is: it costs a model call. The server
 * caches it on the execution, so a page reload shows it for free — and the
 * assistant is only ever given scenarios that were actually solved. */
function ScenarioExplanation({
  executionId,
  cached,
  t,
}: {
  executionId: string;
  cached: string | null;
  t: ReturnType<typeof useTranslations>;
}) {
  const [text, setText] = useState<string | null>(cached);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useAdvancedModel();

  useEffect(() => {
    setText(cached);
  }, [cached]);

  const explain = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .explainExecutionScenarios(executionId, advanced)
      .then((res) => setText(res.explanation))
      .catch((err: unknown) => setError(getErrorMessage(err, t("explainError"))))
      .finally(() => setLoading(false));
  }, [executionId, t, advanced]);

  return (
    <div className="space-y-2" data-testid="scenario-explanation">
      {!text && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={explain}
            disabled={loading}
            data-testid="scenario-explain-button"
            className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted/50 disabled:opacity-50"
          >
            {loading ? t("explaining") : t("explain")}
          </button>
          <AdvancedModelToggle checked={advanced} onChange={setAdvanced} disabled={loading} />
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {text && (
        <div
          className="prose prose-sm dark:prose-invert max-w-none text-foreground"
          data-testid="scenario-explanation-text"
        >
          <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
        </div>
      )}
    </div>
  );
}

function fmt(v: number): string {
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
