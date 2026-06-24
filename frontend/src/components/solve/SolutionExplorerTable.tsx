"use client";

import { useState, useMemo } from "react";
import { VariableSolution, VariableType, SensitivityResult } from "@/lib/types";
import { ConceptTooltip } from "@/components/ui/concept-tooltip";
import { useTranslations } from "next-intl";

interface SolutionExplorerTableProps {
  variables: VariableSolution[];
  sensitivity?: SensitivityResult;
}

type TypeFilter = "all" | VariableType;

export function SolutionExplorerTable({ variables, sensitivity }: SolutionExplorerTableProps) {
  const t = useTranslations("solve.explorer");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");

  const filtered = useMemo(() => {
    return variables.filter((v) => {
      const nameMatch = v.name.toLowerCase().includes(search.toLowerCase());
      const typeMatch = typeFilter === "all" || v.type === typeFilter;
      return nameMatch && typeMatch;
    });
  }, [variables, search, typeFilter]);

  const typeOptions: { label: string; value: TypeFilter }[] = [
    { label: t("all"), value: "all" },
    { label: t("continuous"), value: "continuous" },
    { label: t("integer"), value: "integer" },
    { label: t("binary"), value: "binary" },
  ];

  return (
    <div className="space-y-6">
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="flex flex-col sm:flex-row gap-3 p-4 border-b border-border bg-muted/30">
          <input
            type="text"
            placeholder={t("searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 px-3 py-1.5 text-sm bg-background border border-border rounded focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50 placeholder:text-muted-foreground"
          />
          <div className="flex gap-1 items-center">
            {typeOptions.map((opt) => (
              <label key={opt.value} className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="typeFilter"
                  value={opt.value}
                  checked={typeFilter === opt.value}
                  onChange={() => setTypeFilter(opt.value)}
                  className="accent-primary w-3.5 h-3.5"
                />
                <span className="text-sm text-foreground whitespace-nowrap">{opt.label}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="px-4 py-2 border-b border-border bg-muted/10">
          <span className="text-xs text-muted-foreground">
            {t("showingOf", { filtered: filtered.length, total: variables.length })}
          </span>
        </div>

        {filtered.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <p className="text-sm text-muted-foreground">{t("noMatch")}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/40 border-b border-border">
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">{t("name")}</th>
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">{t("type")}</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">{t("value")}</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">{t("lowerBound")}</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">{t("upperBound")}</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">{t("bindingStatus")}</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">{t("slack")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filtered.map((v, idx) => (
                  <tr
                    key={`${v.name}-${idx}`}
                    className="hover:bg-muted/20 transition-colors"
                  >
                    <td className="px-3 py-1.5 font-mono text-xs text-foreground truncate max-w-[180px]">
                      {v.name}
                    </td>
                    <td className="px-3 py-1.5">
                      <TypeBadge type={v.type} />
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                      {v.value.toLocaleString(undefined, { maximumFractionDigits: 6 })}
                    </td>
                    <td className="px-3 py-1.5 text-right text-muted-foreground text-xs">
                      &mdash;
                    </td>
                    <td className="px-3 py-1.5 text-right text-muted-foreground text-xs">
                      &mdash;
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <span
                        className="text-xs text-muted-foreground cursor-help"
                        title={t("naBindingTooltip")}
                      >
                        {t("naBinding")}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      <span
                        className="text-xs text-muted-foreground cursor-help"
                        title={t("naSlackTooltip")}
                      >
                        {t("naBinding")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Constraint Sensitivity subsection (shown when sensitivity data is available) */}
      {sensitivity && sensitivity.constraints.length > 0 && (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border bg-muted/30 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">{t("constraintSensitivity")}</h3>
            {sensitivity.is_approximate && (
              <span className="text-xs px-2 py-0.5 bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400 rounded-full font-medium">
                {t("approximateLpRelaxation")}
              </span>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-muted/40 border-b border-border">
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">{t("constraint")}</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground"><ConceptTooltip termKey="shadow-price">{t("shadowPrice")}</ConceptTooltip></th>
                  <th className="px-3 py-2 text-center font-medium text-muted-foreground"><ConceptTooltip termKey="binding-constraint">{t("bindingStatus")}</ConceptTooltip></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {sensitivity.constraints.map((c, idx) => (
                  <tr
                    key={`${c.name}-${idx}`}
                    className={
                      c.is_binding
                        ? "bg-green-50/50 dark:bg-green-900/10 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors"
                        : "hover:bg-muted/20 transition-colors"
                    }
                  >
                    <td className="px-3 py-1.5 font-mono text-xs text-foreground truncate max-w-[200px]">
                      {c.name}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                      {c.shadow_price !== null && c.shadow_price !== undefined
                        ? c.shadow_price.toFixed(6)
                        : "\u2014"}
                    </td>
                    <td className="px-3 py-1.5 text-center">
                      {c.is_binding === null ? (
                        <span className="text-xs text-muted-foreground">&mdash;</span>
                      ) : c.is_binding ? (
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
      )}
    </div>
  );
}

function TypeBadge({ type }: { type: VariableType }) {
  const styles: Record<VariableType, string> = {
    continuous: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    integer: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
    binary: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  };
  const labels: Record<VariableType, string> = {
    continuous: "cont",
    integer: "int",
    binary: "bin",
  };
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[0.625rem] font-medium uppercase tracking-wide ${styles[type] ?? ""}`}>
      {labels[type] ?? type}
    </span>
  );
}
