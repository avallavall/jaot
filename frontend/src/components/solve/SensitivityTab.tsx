"use client";

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

  if (!sensitivity) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground text-sm">
        {t("noData")}
      </div>
    );
  }

  const { constraints, is_approximate, note } = sensitivity;
  // Additive fields — older persisted results may not carry them.
  const variables = sensitivity.variables ?? [];
  const rangingUnavailable =
    (sensitivity.objective_ranges?.length ?? 0) === 0 &&
    (sensitivity.rhs_ranges?.length ?? 0) === 0;

  // Filter to constraints with numeric shadow prices, sort by magnitude descending
  const chartData: ChartEntry[] = constraints
    .filter((c): c is ConstraintSensitivity & { shadow_price: number } =>
      c.shadow_price !== null && c.shadow_price !== undefined
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

  const chartHeight = Math.max(120, chartData.length * 40 + 60);

  return (
    <div className="space-y-6">
      {is_approximate && (
        <div className="flex items-start gap-3 px-4 py-3 bg-yellow-50 border border-yellow-200 rounded-lg dark:bg-yellow-900/20 dark:border-yellow-800">
          <span className="text-yellow-600 dark:text-yellow-400 text-sm font-medium mt-0.5">
            {t("approximate")}
          </span>
          <p className="text-sm text-yellow-700 dark:text-yellow-300">
            {note ??
              <>Approximate &mdash; based on <ConceptTooltip termKey="lp-relaxation">LP relaxation</ConceptTooltip>. This problem contains integer/binary variables; shadow prices are derived from the <ConceptTooltip termKey="lp-relaxation">LP relaxation</ConceptTooltip>.</>}
          </p>
        </div>
      )}

      {chartData.length === 0 ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
          {t("noShadowPrices")}
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
                  data={chartData}
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
                    {chartData.map((entry, index) => (
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
                    {tableRows.map((row, idx) => (
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
            </div>
          </div>
        </>
      )}

      {variables.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3">
            {t("variableReducedCosts")}
          </h3>
          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-muted/40 border-b border-border">
                    <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                      {t("variable")}
                    </th>
                    <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                      {t("reducedCost")}
                    </th>
                    <th className="px-3 py-2 text-center font-medium text-muted-foreground">
                      {t("atBound")}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {variables.map((v, idx) => (
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
          </div>
        </div>
      )}

      {rangingUnavailable && (
        <p className="text-xs text-muted-foreground">{t("rangingUnavailable")}</p>
      )}
    </div>
  );
}
