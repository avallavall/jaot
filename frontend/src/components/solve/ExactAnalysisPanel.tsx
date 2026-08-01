"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import type { ConstraintFamilyStats, ExactAnalysis } from "@/lib/types";

interface ExactAnalysisPanelProps {
  executionId: string;
}

const NEAR_ZERO = 1e-9;

/**
 * Post-solve analysis (A3): EXACT, solution-based facts computed from x* + the
 * problem — binding constraints, per-constraint slack/utilization, and which
 * terms drive the objective — all exact for the integer solution and
 * solver-agnostic. This answers "how did my solution come out?".
 *
 * "What if it changed?" is a different question and now lives entirely in the
 * Sensitivity tab, together with the LP-relaxation duals it approximates. Both
 * used to render here as well, which put the same shadow prices on screen three
 * times and buried the what-if under five sections of a tab named Results.
 */
export function ExactAnalysisPanel({ executionId }: ExactAnalysisPanelProps) {
  const t = useTranslations("solve.execution.exactAnalysis");
  const [data, setData] = useState<ExactAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Mounts with loading=true; only the async callbacks touch state (no
    // synchronous setState in the effect body). executionId is stable per page.
    let cancelled = false;
    api
      .getExecutionExactAnalysis(executionId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(getErrorMessage(err, t("error")));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [executionId, t]);

  if (loading) {
    return <p className="text-sm text-muted-foreground py-6 text-center">{t("loading")}</p>;
  }
  if (error) {
    return <p className="text-sm text-destructive py-6 text-center">{error}</p>;
  }
  if (!data || !data.computed) {
    return (
      <p className="text-sm text-muted-foreground py-6 text-center">
        {data?.note === "not_a_problem" ? t("notAProblem") : t("noSolution")}
      </p>
    );
  }

  const binding = data.constraints.filter((c) => c.is_binding);
  // Additive fields (Sensitivity L1) — a stale backend may not send them yet.
  const families = data.families ?? [];
  const contributionFamilies = data.contribution_families ?? [];

  return (
    <div className="space-y-6" data-testid="exact-analysis">
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="text-sm text-foreground">
          {t("bindingSummary", { binding: data.binding_count, total: data.total_constraints })}
        </p>
        {binding.length > 0 && (
          <ul className="mt-3 space-y-1">
            {binding.slice(0, 12).map((c) => (
              <li key={c.name} className="flex items-baseline justify-between gap-3 text-xs">
                <span className="font-mono truncate text-foreground">{c.name}</span>
                <span className="shrink-0 font-mono tabular-nums text-muted-foreground">
                  {fmt(c.activity)} {c.operator} {fmt(c.rhs)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {families.length > 0 && (
        <Section title={t("families")}>
          <FamilyTable rows={families} t={t} />
          <p className="mt-2 text-xs text-muted-foreground">
            {t("familiesNote")}
            {data.truncated_families && " " + t("truncatedFamilies")}
          </p>
        </Section>
      )}

      {contributionFamilies.length > 0 && (
        <Section title={t("familyContributions")} testId="exact-analysis-family-contributions">
          <ContributionBars
            contributions={contributionFamilies.map((f) => ({
              label: f.family,
              contribution: f.contribution,
            }))}
            label={t("contribution")}
          />
        </Section>
      )}

      {data.contributions.length > 0 && (
        <Section title={t("objectiveContributions")}>
          <ContributionBars
            contributions={data.contributions}
            label={t("contribution")}
          />
        </Section>
      )}

      {data.constraints.length > 0 && (
        <Section title={t("utilization")}>
          <UtilizationTable rows={data.constraints} t={t} />
          {data.truncated_constraints && (
            <p className="mt-2 text-xs text-muted-foreground">{t("truncated")}</p>
          )}
        </Section>
      )}

    </div>
  );
}

function Section({
  title,
  children,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <div data-testid={testId}>
      <h3 className="mb-3 text-sm font-semibold text-foreground">{title}</h3>
      {children}
    </div>
  );
}

function ContributionBars({
  contributions,
  label,
}: {
  contributions: { label: string; contribution: number }[];
  label: string;
}) {
  const max = Math.max(...contributions.map((c) => Math.abs(c.contribution)), NEAR_ZERO);
  return (
    <div className="space-y-1.5">
      {contributions.slice(0, 15).map((c) => (
        <div key={c.label} className="flex items-center gap-2">
          <span className="w-40 shrink-0 truncate font-mono text-xs text-foreground" title={c.label}>
            {c.label}
          </span>
          <div className="relative h-4 flex-1 rounded bg-muted/40">
            <div
              className="absolute inset-y-0 left-0 rounded bg-primary/70"
              style={{ width: `${(Math.abs(c.contribution) / max) * 100}%` }}
            />
          </div>
          <span className="w-24 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
            {fmt(c.contribution)}
          </span>
        </div>
      ))}
      <p className="sr-only">{label}</p>
    </div>
  );
}

/** Family-level KPIs (Sensitivity L1): saturation, slack spread, utilization.
 * Rows arrive ranked by the backend — most saturated first, so the headroom
 * ranking reads bottom-up. A fully-binding family gets the binding highlight. */
function FamilyTable({
  rows,
  t,
}: {
  rows: ConstraintFamilyStats[];
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div
      className="overflow-x-auto rounded-lg border border-border bg-card"
      data-testid="exact-analysis-families"
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/40">
            <th className="px-3 py-2 text-left font-medium text-muted-foreground">{t("family")}</th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">
              {t("bindingRatio")}
            </th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">
              {t("slackHeader")}
            </th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">
              {t("utilizationHeader")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((f) => {
            const ratio = f.total > 0 ? f.binding_count / f.total : 0;
            return (
              <tr
                key={f.family}
                className={ratio === 1 ? "bg-green-50/50 dark:bg-green-900/10" : ""}
              >
                <td className="px-3 py-1.5 font-mono text-xs text-foreground truncate max-w-[200px]">
                  {f.family}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                  {f.binding_count}/{f.total}
                  <span className="ml-1 text-muted-foreground">({Math.round(ratio * 100)}%)</span>
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
                  {fmt(f.slack_min)} / {fmt(f.slack_mean)} / {fmt(f.slack_max)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
                  {f.utilization_mean != null && f.utilization_max != null
                    ? `${(f.utilization_mean * 100).toFixed(0)}% · ${(f.utilization_max * 100).toFixed(0)}%`
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function UtilizationTable({
  rows,
  t,
}: {
  rows: ExactAnalysis["constraints"];
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/40">
            <th className="px-3 py-2 text-left font-medium text-muted-foreground">{t("constraint")}</th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">{t("activity")}</th>
            <th className="px-3 py-2 text-right font-medium text-muted-foreground">{t("slack")}</th>
            <th className="px-3 py-2 text-center font-medium text-muted-foreground">{t("binding")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.slice(0, 40).map((c) => (
            <tr
              key={c.name}
              className={c.is_binding ? "bg-green-50/50 dark:bg-green-900/10" : ""}
            >
              <td className="px-3 py-1.5 font-mono text-xs text-foreground truncate max-w-[200px]">
                {c.name}
              </td>
              <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                {fmt(c.activity)} {c.operator} {fmt(c.rhs)}
                {c.utilization != null && (
                  <span className="ml-1 text-muted-foreground">
                    ({(c.utilization * 100).toFixed(0)}%)
                  </span>
                )}
              </td>
              <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
                {fmt(c.slack)}
              </td>
              <td className="px-3 py-1.5 text-center">
                {c.is_binding ? (
                  <span className="inline-block rounded bg-green-100 px-1.5 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide text-green-700 dark:bg-green-900/30 dark:text-green-400">
                    {t("yes")}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmt(v: number): string {
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}
