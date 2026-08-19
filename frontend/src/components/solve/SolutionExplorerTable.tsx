"use client";

import { useState, useMemo } from "react";
import { VariableSolution, VariableType } from "@/lib/types";
import { useTranslations } from "next-intl";
import { boundStatus, type VariableBounds } from "@/lib/variable-bounds";

interface SolutionExplorerTableProps {
  variables: VariableSolution[];
  /** The range each variable was declared with, read off the run's own stored
   * problem. Absent for a run whose payload is not on the page; the four
   * columns that need it then say so instead of guessing. */
  bounds?: Record<string, VariableBounds>;
}

type TypeFilter = "all" | VariableType;

/** Below this magnitude a value renders as visual noise ("0" rows) — the same
 * threshold the MCP solution_filter and the printable report use. */
const NEAR_ZERO = 1e-9;

export function SolutionExplorerTable({ variables, bounds }: SolutionExplorerTableProps) {
  const t = useTranslations("solve.explorer");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  // Default ON (owner ask 2026-07-16): big models are mostly zeros — show the
  // variables that carry the solution; the toggle reveals the rest.
  const [nonZeroOnly, setNonZeroOnly] = useState(true);

  const filtered = useMemo(() => {
    return variables.filter((v) => {
      const nameMatch = v.name.toLowerCase().includes(search.toLowerCase());
      const typeMatch = typeFilter === "all" || v.type === typeFilter;
      const valueMatch = !nonZeroOnly || Math.abs(v.value) > NEAR_ZERO;
      return nameMatch && typeMatch && valueMatch;
    });
  }, [variables, search, typeFilter, nonZeroOnly]);

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
          <label className="flex items-center gap-1.5 cursor-pointer border-l border-border pl-3">
            <input
              type="checkbox"
              checked={nonZeroOnly}
              onChange={(e) => setNonZeroOnly(e.target.checked)}
              className="accent-primary w-3.5 h-3.5"
              data-testid="explorer-nonzero-toggle"
            />
            <span className="text-sm text-foreground whitespace-nowrap">{t("nonZeroOnly")}</span>
          </label>
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
                    <BoundCells value={v.value} bounds={bounds?.[v.name]} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}

/** How a number reads in these four columns. */
function num(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

/**
 * Lower Bound, Upper Bound, Binding and Slack for one variable.
 *
 * All four used to be placeholders: two em-dashes and two cells reading "N/A"
 * under a tooltip that blamed MIP problems, shown on a pure LP with two
 * continuous variables. What they say now comes from the range the variable
 * was declared with and the value the solver returned.
 */
function BoundCells({ value, bounds }: { value: number; bounds?: VariableBounds }) {
  const t = useTranslations("solve.explorer");
  const status = boundStatus(value, bounds);
  const unknown = <span className="text-muted-foreground">&mdash;</span>;

  return (
    <>
      <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
        {bounds?.lower != null ? num(bounds.lower) : unknown}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
        {bounds?.upper != null ? num(bounds.upper) : unknown}
      </td>
      <td className="px-3 py-1.5 text-right text-xs">
        {status.at === null ? (
          unknown
        ) : (
          <span className="font-medium text-amber-700 dark:text-amber-400">
            {t(status.at === "lower" ? "atLowerBound" : "atUpperBound")}
          </span>
        )}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums text-muted-foreground">
        {status.slack === null ? unknown : num(status.slack)}
      </td>
    </>
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
