"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { VariableSolution, SensitivityResult } from "@/lib/types";
import { SolutionExplorerTable } from "./SolutionExplorerTable";
import {
  buildSolutionGroups,
  type SolutionGroup,
  type SolutionLeaf,
} from "@/lib/solution-grouping";

/** Same near-zero threshold the flat table, chart and MCP filter use. */
const NEAR_ZERO = 1e-9;

interface StructuredSolutionViewProps {
  variables: VariableSolution[];
  sensitivity?: SensitivityResult;
}

/**
 * Primary post-solve variable view. When the solution carries recovered index
 * structure (A1), it leads with a family → first-index grouping — the answer to
 * "what did the model decide?" — instead of a wall of identical `assign_v3_o107
 * = 1` rows. The full flat table (with constraint sensitivity) is one toggle
 * away. When no structure was recovered it renders the flat table directly, so
 * nothing regresses for continuous / custom-named / legacy solutions.
 */
export function StructuredSolutionView({ variables, sensitivity }: StructuredSolutionViewProps) {
  const t = useTranslations("solve.explorer");
  const [nonZeroOnly, setNonZeroOnly] = useState(true);
  const [view, setView] = useState<"grouped" | "table">("grouped");

  const hasStructure = useMemo(() => variables.some((v) => v.family), [variables]);
  const shown = useMemo(
    () => (nonZeroOnly ? variables.filter((v) => Math.abs(v.value) > NEAR_ZERO) : variables),
    [variables, nonZeroOnly],
  );
  const grouped = useMemo(() => buildSolutionGroups(shown), [shown]);

  // No structure recovered → the grouping adds nothing. Fall back to the flat
  // table exactly as before (the graceful degradation the analysis layer relies on).
  if (!hasStructure) {
    return <SolutionExplorerTable variables={variables} sensitivity={sensitivity} />;
  }

  // Families in first-seen order, each with its groups (multi-index families
  // sub-grouped by first index; single-index families in one null-key bucket).
  const families: { family: string; groups: SolutionGroup[] }[] = [];
  const seen = new Map<string, number>();
  for (const g of grouped.groups) {
    const at = seen.get(g.family);
    if (at === undefined) {
      seen.set(g.family, families.length);
      families.push({ family: g.family, groups: [g] });
    } else {
      families[at].groups.push(g);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div
          className="inline-flex rounded-md border border-border overflow-hidden"
          role="group"
          aria-label={t("viewLabel")}
        >
          <button
            type="button"
            onClick={() => setView("grouped")}
            data-testid="structured-view-grouped"
            className={`px-3 py-1.5 text-sm font-medium transition-colors ${
              view === "grouped"
                ? "bg-primary text-primary-foreground"
                : "bg-background text-muted-foreground hover:bg-muted/40"
            }`}
          >
            {t("viewGrouped")}
          </button>
          <button
            type="button"
            onClick={() => setView("table")}
            data-testid="structured-view-table"
            className={`px-3 py-1.5 text-sm font-medium transition-colors border-l border-border ${
              view === "table"
                ? "bg-primary text-primary-foreground"
                : "bg-background text-muted-foreground hover:bg-muted/40"
            }`}
          >
            {t("viewTable")}
          </button>
        </div>

        {view === "grouped" && (
          <>
            <label className="flex items-center gap-1.5 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={nonZeroOnly}
                onChange={(e) => setNonZeroOnly(e.target.checked)}
                className="accent-primary w-3.5 h-3.5"
                data-testid="structured-nonzero-toggle"
              />
              <span className="text-foreground whitespace-nowrap">{t("nonZeroOnly")}</span>
            </label>
            <span className="text-xs text-muted-foreground sm:ml-auto">
              {t("showingOf", { filtered: shown.length, total: variables.length })}
            </span>
          </>
        )}
      </div>

      {view === "table" ? (
        <SolutionExplorerTable variables={variables} sensitivity={sensitivity} />
      ) : shown.length === 0 ? (
        <div className="bg-card border border-border rounded-lg px-4 py-10 text-center">
          <p className="text-sm text-muted-foreground">{t("noMatch")}</p>
        </div>
      ) : (
        <div className="space-y-4" data-testid="structured-groups">
          {families.map(({ family, groups }) => (
            <FamilySection key={family} family={family} groups={groups} t={t} />
          ))}
          {grouped.ungrouped.length > 0 && (
            <UngroupedSection entries={grouped.ungrouped} label={t("otherVariables")} />
          )}
        </div>
      )}
    </div>
  );
}

function FamilySection({
  family,
  groups,
  t,
}: {
  family: string;
  groups: SolutionGroup[];
  t: ReturnType<typeof useTranslations>;
}) {
  const count = groups.reduce((n, g) => n + g.entries.length, 0);
  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-muted/30">
        <span className="font-mono text-sm font-semibold text-foreground">{family}</span>
        <span className="text-xs text-muted-foreground">{t("countLabel", { count })}</span>
      </div>
      <div className="divide-y divide-border">
        {groups.map((g, i) => (
          <div key={g.key ?? `__${i}`} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2">
            {g.key !== null && (
              <span className="font-mono text-xs font-medium text-foreground shrink-0">
                {g.key}
                <span className="text-muted-foreground"> →</span>
              </span>
            )}
            <div className="flex flex-wrap gap-1.5">
              {g.entries.map((e) => (
                <EntryChip key={e.name} entry={e} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function UngroupedSection({ entries, label }: { entries: SolutionLeaf[]; label: string }) {
  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="px-4 py-2 border-b border-border bg-muted/30">
        <span className="text-sm font-semibold text-muted-foreground">{label}</span>
      </div>
      <div className="flex flex-wrap gap-1.5 px-4 py-2">
        {entries.map((e) => (
          <EntryChip key={e.name} entry={e} />
        ))}
      </div>
    </div>
  );
}

/** A binary "selected" member shows just its label; anything else shows its
 *  value too, since the magnitude is the information there. */
function EntryChip({ entry }: { entry: SolutionLeaf }) {
  const isOnBinary = entry.type === "binary" && Math.abs(entry.value - 1) < NEAR_ZERO;
  return (
    <span
      className="inline-flex items-baseline gap-1 rounded bg-muted/50 px-1.5 py-0.5 font-mono text-xs text-foreground"
      title={entry.name}
    >
      {entry.label}
      {!isOnBinary && (
        <span className="text-muted-foreground tabular-nums">
          = {entry.value.toLocaleString(undefined, { maximumFractionDigits: 6 })}
        </span>
      )}
    </span>
  );
}
