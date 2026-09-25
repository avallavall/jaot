"use client";

import type { MultiObjectiveConfig, ObjectiveSpec, ObjectiveSense } from "@/lib/types";
import { useTranslations } from "next-intl";

interface MultiObjectiveConfigProps {
  value: MultiObjectiveConfig;
  onChange: (config: MultiObjectiveConfig) => void;
  variables?: string[];
}

// The backend solves exactly two objectives (epsilon-constraint / weighted
// scalarization over a 2-D Pareto front — see app/schemas/optimization.py
// MultiObjectiveConfig). The UI mirrors that contract: always two objectives,
// no add/remove. Supporting N>2 objectives would need a new n-dimensional
// multi-objective backend, tracked as a follow-up.

/**
 * Default objective spec shared by page.tsx and this component.
 *
 * No `weight`: weighted mode sweeps the weights on the server (n_points solves,
 * from all weight on objective 2 to all on objective 1). This form used to ask
 * for a weight per objective and refuse to solve unless they summed to 1, and
 * the server never read them.
 */
export const DEFAULT_OBJECTIVE: ObjectiveSpec = {
  expression: "",
  sense: "minimize",
  label: "",
};

/** Generate a short random id for keying list items. */
function objUid(): string {
  return Math.random().toString(36).slice(2, 9);
}

/** Ensure every objective in the list carries a stable `_key` for React keying. */
function ensureKeys(objectives: readonly ObjectiveSpec[]): readonly ObjectiveSpec[] {
  return objectives.map((o) => {
    if ((o as ObjectiveSpec & { _key?: string })._key) return o;
    return { ...o, _key: objUid() } as ObjectiveSpec;
  });
}

/** Read the stable key from an objective (falls back to index). */
function keyOf(obj: ObjectiveSpec, fallbackIndex: number): string {
  return (obj as ObjectiveSpec & { _key?: string })._key ?? String(fallbackIndex);
}

function ObjectiveSection({
  index,
  objective,
  onChange,
  onRemove,
}: {
  index: number;
  objective: ObjectiveSpec;
  onChange: (obj: ObjectiveSpec) => void;
  onRemove: (() => void) | null;
}) {
  const t = useTranslations("solve.multiObjectiveConfig");

  return (
    <div className="bg-card border border-border rounded-lg p-4 relative">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-foreground">
          {t("objectiveN", { n: index + 1 })}
        </h3>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="text-xs text-muted-foreground hover:text-destructive transition-colors"
            aria-label={t("removeObjective")}
          >
            {t("removeObjective")}
          </button>
        )}
      </div>
      <div className="space-y-3">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">
            {t("label")} <span className="text-muted-foreground/60">{t("labelOptional")}</span>
          </label>
          <input
            type="text"
            value={objective.label ?? ""}
            onChange={(e) => onChange({ ...objective, label: e.target.value })}
            placeholder={t("labelPlaceholderN", { n: index + 1 })}
            className="w-full px-3 py-1.5 text-sm bg-background border border-border rounded focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50 placeholder:text-muted-foreground"
            data-testid={`objective-label-${index}`}
          />
        </div>

        <div>
          <label className="block text-xs text-muted-foreground mb-1">
            {t("expression")} <span className="text-destructive">*</span>
          </label>
          <input
            type="text"
            value={objective.expression}
            onChange={(e) => onChange({ ...objective, expression: e.target.value })}
            placeholder={t("expressionPlaceholderN", { n: index + 1 })}
            className="w-full px-3 py-1.5 text-sm bg-background border border-border rounded focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50 placeholder:text-muted-foreground font-mono"
            data-testid={`objective-expression-${index}`}
          />
        </div>

        <div>
          <label className="block text-xs text-muted-foreground mb-1">{t("direction")}</label>
          <select
            value={objective.sense}
            onChange={(e) => onChange({ ...objective, sense: e.target.value as ObjectiveSense })}
            className="w-full px-3 py-1.5 text-sm bg-background border border-border rounded focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50"
            data-testid={`objective-sense-${index}`}
          >
            <option value="minimize">{t("minimize")}</option>
            <option value="maximize">{t("maximize")}</option>
          </select>
        </div>

      </div>
    </div>
  );
}

interface PairSelectorProps {
  labels: readonly string[];
  selectedPair: readonly [number, number];
  onChange: (pair: [number, number]) => void;
}

function PairSelector({ labels, selectedPair, onChange }: PairSelectorProps) {
  const t = useTranslations("solve.multiObjectiveConfig");

  // Generate all pairs
  const pairs: Array<[number, number]> = [];
  for (let i = 0; i < labels.length; i++) {
    for (let j = i + 1; j < labels.length; j++) {
      pairs.push([i, j]);
    }
  }

  if (pairs.length <= 1) return null;

  return (
    <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1">
        {t("pairSelector")}
      </label>
      <select
        value={`${selectedPair[0]}-${selectedPair[1]}`}
        onChange={(e) => {
          const [a, b] = e.target.value.split("-").map(Number);
          onChange([a, b]);
        }}
        className="px-3 py-1.5 text-sm bg-background border border-border rounded focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50"
        data-testid="pair-selector"
      >
        {pairs.map(([a, b]) => (
          <option key={`${a}-${b}`} value={`${a}-${b}`}>
            {labels[a] || t("objectiveN", { n: a + 1 })} vs{" "}
            {labels[b] || t("objectiveN", { n: b + 1 })}
          </option>
        ))}
      </select>
    </div>
  );
}

export { PairSelector };

export function MultiObjectiveConfigForm({
  value,
  onChange,
}: MultiObjectiveConfigProps) {
  const t = useTranslations("solve.multiObjectiveConfig");

  const objectives = ensureKeys(value.objectives);
  const total = objectives.length;

  function setMode(mode: "epsilon" | "weighted") {
    onChange({ ...value, mode });
  }

  function setObjective(idx: number, obj: ObjectiveSpec) {
    const newObjs = objectives.map((o, i) =>
      i === idx ? { ...obj, _key: keyOf(o, i) } as ObjectiveSpec : o
    );
    onChange({ ...value, objectives: newObjs });
  }

  function setNPoints(n: number) {
    onChange({ ...value, n_points: n });
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-muted-foreground mb-2">
          {t("solvingMode")}
        </label>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMode("epsilon")}
            className={`flex-1 px-4 py-2 text-sm rounded-md border transition-colors ${
              value.mode === "epsilon"
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background text-foreground border-border hover:bg-muted"
            }`}
          >
            {t("epsilonConstraint")}
          </button>
          <button
            type="button"
            onClick={() => setMode("weighted")}
            className={`flex-1 px-4 py-2 text-sm rounded-md border transition-colors ${
              value.mode === "weighted"
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background text-foreground border-border hover:bg-muted"
            }`}
          >
            {t("weightedCombination")}
          </button>
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          {value.mode === "epsilon"
            ? t("epsilonDescription")
            : t("weightedDescription")}
        </p>
      </div>

      <div className={`grid grid-cols-1 ${total <= 2 ? "lg:grid-cols-2" : ""} gap-4`}>
        {objectives.map((obj, idx) => (
          <ObjectiveSection
            key={keyOf(obj, idx)}
            index={idx}
            objective={obj}
            onChange={(o) => setObjective(idx, o)}
            onRemove={null}
          />
        ))}
      </div>

      <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1">
          {t("paretoPoints")}
        </label>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={2}
            max={50}
            step={1}
            value={value.n_points ?? 10}
            onChange={(e) => setNPoints(parseInt(e.target.value, 10))}
            className="flex-1 accent-primary"
          />
          <span className="text-sm font-mono w-8 text-right tabular-nums">
            {value.n_points ?? 10}
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-1">
          {t("morePointsNote")}
        </p>
      </div>
    </div>
  );
}
