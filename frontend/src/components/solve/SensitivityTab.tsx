"use client";

import { useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { SensitivityResult, ConstraintSensitivity } from "@/lib/types";
import { ConceptTooltip } from "@/components/ui/concept-tooltip";
import { useTranslations } from "next-intl";

interface SensitivityTabProps {
  sensitivity?: SensitivityResult | null;
}

interface ChartEntry {
  name: string;
  shadow_price: number;
  is_binding: boolean | null;
}

function formatShadowPrice(value: number | null | undefined): string {
  if (value == null) return "\u2014";
  return value.toFixed(6);
}

export function SensitivityTab({ sensitivity }: SensitivityTabProps) {
  const t = useTranslations("solve.sensitivity");
  // Default ON (owner ask 2026-07-16): in large models most BASIC variables
  // have a zero reduced cost — the informative rows are the non-zero ones.
  // (Filtering by variable VALUE would be wrong here: variables AT ZERO are
  // exactly the ones whose reduced cost matters.)
  const [nonZeroRcOnly, setNonZeroRcOnly] = useState(true);

  if (!sensitivity) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground text-sm">
        {t("noData")}
      </div>
    );
  }

  const { constraints, is_approximate } = sensitivity;
  // Additive fields — older persisted results may not carry them.
  const allVariables = sensitivity.variables ?? [];
  const variables = nonZeroRcOnly
    ? allVariables.filter((v) => v.reduced_cost != null && Math.abs(v.reduced_cost) > 1e-9)
    : allVariables;
  const rangingUnavailable =
    (sensitivity.objective_ranges?.length ?? 0) === 0 &&
    (sensitivity.rhs_ranges?.length ?? 0) === 0;

  // Chart shows NON-ZERO shadow prices only, sorted by magnitude descending —
  // an all-zero MIP used to render a wall of invisible bars (owner live-test
  // 2026-07-17); zeros carry no chart information, the table still lists them.
  const computableCount = constraints.filter(
    (c) => c.shadow_price !== null && c.shadow_price !== undefined
  ).length;
  const chartData: ChartEntry[] = constraints
    .filter((c): c is ConstraintSensitivity & { shadow_price: number } =>
      c.shadow_price !== null &&
      c.shadow_price !== undefined &&
      Math.abs(c.shadow_price) > 1e-9
    )
    .sort((a, b) => Math.abs(b.shadow_price) - Math.abs(a.shadow_price))
    .map((c) => ({
      name: c.name,
      shadow_price: c.shadow_price,
      is_binding: c.is_binding ?? null,
    }));

  // Table rows sorted same way (all constraints, nulls last)
  const tableRows = [...constraints].sort((a, b) => {
    const magA = a.shadow_price != null ? Math.abs(a.shadow_price) : -Infinity;
    const magB = b.shadow_price != null ? Math.abs(b.shadow_price) : -Infinity;
    return magB - magA;
  });

  // Group identical shadow prices. In a MIP the LP relaxation is often (near-)
  // degenerate — dozens/hundreds of constraints share the exact same dual — and a
  // per-constraint bar chart of identical full-width bars carries zero information
  // (owner live-test 2026-07-20, the 100×100 assignment). When duplication dominates,
  // the chart collapses to one row per DISTINCT value; otherwise the chart stays,
  // capped to the top bars by magnitude.
  const valueGroups = (() => {
    const byValue = new Map<string, { value: number; count: number; binding: number }>();
    for (const c of chartData) {
      const key = c.shadow_price.toFixed(6);
      const g = byValue.get(key) ?? { value: c.shadow_price, count: 0, binding: 0 };
      g.count += 1;
      if (c.is_binding) g.binding += 1;
      byValue.set(key, g);
    }
    return [...byValue.values()].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  })();
  const degenerate =
    chartData.length >= 12 && valueGroups.length <= Math.max(3, chartData.length / 10);

  const CHART_CAP = 30;
  const TABLE_CAP = 50;
  const chartShown = chartData.slice(0, CHART_CAP);
  const tableShown = tableRows.slice(0, TABLE_CAP);
  const rcShown = variables.slice(0, TABLE_CAP);

  const chartHeight = Math.max(120, chartShown.length * 40 + 60);

  return (
    <div className="space-y-6">
      {is_approximate && (
        <div className="flex items-start gap-3 px-4 py-3 bg-yellow-50 border border-yellow-200 rounded-lg dark:bg-yellow-900/20 dark:border-yellow-800">
          <span className="text-yellow-600 dark:text-yellow-400 text-sm font-medium mt-0.5">
            {t("approximate")}
          </span>
          <p className="text-sm text-yellow-700 dark:text-yellow-300">
            {/* Always the localized copy — the backend `note` is English-only
                and leaked raw into every other locale (owner live-test). */}
            {t("approximateNote")}
          </p>
        </div>
      )}

      {chartData.length === 0 ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground text-sm text-center px-6">
          {computableCount > 0 ? t("allZeroShadowPrices") : t("noShadowPrices")}
        </div>
      ) : degenerate ? (
        <div data-testid="sensitivity-shadow-groups">
          <h3 className="text-sm font-semibold text-foreground mb-3">
            {t("shadowPricesByConstraint")}
          </h3>
          <div className="bg-card border border-border rounded-lg px-4 py-3 space-y-1.5">
            {valueGroups.map((g) => (
              <div
                key={g.value.toFixed(6)}
                className="flex items-baseline justify-between gap-3 text-sm"
              >
                <span className="text-muted-foreground">
                  {t("shadowPriceGroup", { count: g.count, binding: g.binding })}
                </span>
                <span className="font-mono tabular-nums text-foreground">
                  <ConceptTooltip termKey="shadow-price">{g.value.toFixed(4)}</ConceptTooltip>
                </span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">{t("degenerateNote")}</p>
        </div>
      ) : (
        <>
          <div>
            <h3 className="text-sm font-semibold text-foreground mb-3">
              {t("shadowPricesByConstraint")}
            </h3>
            <div style={{ height: chartHeight }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={chartShown}
                  layout="vertical"
                  margin={{ top: 4, right: 24, left: 8, bottom: 4 }}
                >
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                    tickFormatter={(v: number) => v.toFixed(4)}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={140}
                    tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "var(--card)",
                      border: "1px solid var(--border)",
                      borderRadius: "4px",
                      fontSize: 12,
                    }}
                    labelStyle={{ color: "var(--foreground)", fontWeight: 600, marginBottom: 4 }}
                    formatter={(value) => [
                      typeof value === "number" ? value.toFixed(6) : String(value ?? ""),
                      t("shadowPrice"),
                    ]}
                  />
                  <Bar dataKey="shadow_price" name={t("shadowPrice")} radius={[0, 3, 3, 0]}>
                    {chartShown.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={
                          entry.is_binding
                            ? "var(--primary)"
                            : "var(--muted-foreground)"
                        }
                        fillOpacity={entry.is_binding ? 1 : 0.5}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {t("bindingNote")}
              {chartData.length > CHART_CAP &&
                " " + t("truncatedRows", { shown: chartShown.length, total: chartData.length })}
            </p>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-foreground mb-3">
              {t("constraintSensitivityDetails")}
            </h3>
            <div className="bg-card border border-border rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-muted/40 border-b border-border">
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {t("constraint")}
                      </th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                        <ConceptTooltip termKey="shadow-price">{t("shadowPrice")}</ConceptTooltip>
                      </th>
                      <th className="px-3 py-2 text-center font-medium text-muted-foreground">
                        <ConceptTooltip termKey="binding-constraint">{t("binding")}</ConceptTooltip>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {tableShown.map((row, idx) => (
                      <tr
                        key={`${row.name}-${idx}`}
                        className={
                          row.is_binding
                            ? "bg-green-50/50 dark:bg-green-900/10 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors"
                            : "hover:bg-muted/20 transition-colors"
                        }
                      >
                        <td className="px-3 py-1.5 font-mono text-xs text-foreground truncate max-w-[200px]">
                          {row.name}
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                          {formatShadowPrice(row.shadow_price)}
                        </td>
                        <td className="px-3 py-1.5 text-center">
                          {row.is_binding === null ? (
                            <span className="text-xs text-muted-foreground">&mdash;</span>
                          ) : row.is_binding ? (
                            <span className="inline-block px-1.5 py-0.5 rounded text-[0.625rem] font-medium uppercase tracking-wide bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                              {t("yes")}
                            </span>
                          ) : (
                            <span className="inline-block px-1.5 py-0.5 rounded text-[0.625rem] font-medium uppercase tracking-wide bg-muted text-muted-foreground">
                              {t("no")}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {tableRows.length > TABLE_CAP && (
                <p className="px-3 py-2 text-xs text-muted-foreground border-t border-border">
                  {t("truncatedRows", { shown: tableShown.length, total: tableRows.length })}
                </p>
              )}
            </div>
          </div>
        </>
      )}

      {allVariables.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-foreground">
              {t("variableReducedCosts")}
            </h3>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={nonZeroRcOnly}
                onChange={(e) => setNonZeroRcOnly(e.target.checked)}
                className="accent-primary w-3.5 h-3.5"
                data-testid="sensitivity-nonzero-rc-toggle"
              />
              <span className="text-xs text-muted-foreground whitespace-nowrap">
                {t("nonZeroRcOnly", { shown: variables.length, total: allVariables.length })}
              </span>
            </label>
          </div>
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-muted/40 border-b border-border">
                    <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                      {t("variable")}
                    </th>
                    <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                      <ConceptTooltip termKey="reduced-cost">{t("reducedCost")}</ConceptTooltip>
                    </th>
                    <th className="px-3 py-2 text-center font-medium text-muted-foreground">
                      {t("atBound")}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {variables.length === 0 && (
                    <tr>
                      <td colSpan={3} className="px-3 py-6 text-center text-xs text-muted-foreground">
                        {t("allRcZero")}
                      </td>
                    </tr>
                  )}
                  {rcShown.map((v, idx) => (
                    <tr
                      key={`${v.name}-${idx}`}
                      className={
                        v.is_at_bound
                          ? "bg-green-50/50 dark:bg-green-900/10 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors"
                          : "hover:bg-muted/20 transition-colors"
                      }
                    >
                      <td className="px-3 py-1.5 font-mono text-xs text-foreground truncate max-w-[200px]">
                        {v.name}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                        {formatShadowPrice(v.reduced_cost)}
                      </td>
                      <td className="px-3 py-1.5 text-center">
                        {v.is_at_bound === null || v.is_at_bound === undefined ? (
                          <span className="text-xs text-muted-foreground">&mdash;</span>
                        ) : v.is_at_bound ? (
                          <span className="inline-block px-1.5 py-0.5 rounded text-[0.625rem] font-medium uppercase tracking-wide bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
                            {t("yes")}
                          </span>
                        ) : (
                          <span className="inline-block px-1.5 py-0.5 rounded text-[0.625rem] font-medium uppercase tracking-wide bg-muted text-muted-foreground">
                            {t("no")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {variables.length > TABLE_CAP && (
              <p className="px-3 py-2 text-xs text-muted-foreground border-t border-border">
                {t("truncatedRows", { shown: rcShown.length, total: variables.length })}
              </p>
            )}
          </div>
        </div>
      )}

      {rangingUnavailable && (
        <p className="text-xs text-muted-foreground">{t("rangingUnavailable")}</p>
      )}
    </div>
  );
}
