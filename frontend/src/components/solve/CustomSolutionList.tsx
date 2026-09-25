"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";

/** Values this close to zero count as zero, as in the builder's results drawer. */
const NEAR_ZERO = 1e-9;

/**
 * Rows drawn at most. A 3,000-variable transport model drew every variable,
 * 2,897 of them zero, in a page 48,000 px tall. The saved run's page has a
 * searchable explorer for the whole solution.
 */
export const SOLUTION_ROW_CAP = 200;

interface CustomSolutionListProps {
  entries: Array<[string, number]>;
  /** The saved run, which holds the full solution. */
  executionId?: string | null;
}

/**
 * The variable values of a custom solve: one row per variable, the name on the
 * left and its value on the right.
 *
 * The old grid put two name/value pairs on each line, so "x 2 y 1" read as
 * x's value sitting next to y's name.
 */
export function CustomSolutionList({ entries, executionId }: CustomSolutionListProps) {
  const t = useTranslations("solve.custom");
  const locale = useLocale();
  const [nonZeroOnly, setNonZeroOnly] = useState(true);

  const nonZero = useMemo(
    () => entries.filter(([, value]) => Math.abs(value) > NEAR_ZERO),
    [entries],
  );
  const listed = nonZeroOnly ? nonZero : entries;
  const shown = listed.slice(0, SOLUTION_ROW_CAP);
  const zeros = entries.length - nonZero.length;

  return (
    <div data-testid="custom-solution">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-muted-foreground">{t("solutionLabel")}</span>
        {zeros > 0 && (
          <label className="flex items-center gap-1.5 cursor-pointer text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={nonZeroOnly}
              onChange={(e) => setNonZeroOnly(e.target.checked)}
              className="accent-primary w-3.5 h-3.5"
              data-testid="custom-solution-nonzero"
            />
            {t("nonZeroOnly", { zeros })}
          </label>
        )}
      </div>
      <div className="mt-2 max-h-96 overflow-auto rounded-lg bg-muted">
        {shown.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground" data-testid="custom-solution-all-zero">
            {t("allZero", { count: entries.length })}
          </p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {shown.map(([name, value]) => (
                <tr key={name} className="border-b border-border/60 last:border-0">
                  <td className="px-4 py-1.5 font-mono break-all">{name}</td>
                  <td className="px-4 py-1.5 text-right font-semibold tabular-nums">
                    {value.toLocaleString(locale, { maximumFractionDigits: 4 })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {(listed.length > shown.length || executionId) && (
        <p className="mt-2 text-xs text-muted-foreground" data-testid="custom-solution-footer">
          {listed.length > shown.length &&
            t("solutionCapped", { shown: shown.length, total: listed.length })}{" "}
          {executionId && (
            <Link
              href={`/solve/executions/${executionId}`}
              className="text-primary hover:underline"
              data-testid="custom-execution-link"
            >
              {t("openSavedRun")}
            </Link>
          )}
        </p>
      )}
    </div>
  );
}
