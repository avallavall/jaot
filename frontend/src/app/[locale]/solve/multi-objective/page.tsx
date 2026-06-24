"use client";

import { useState, useEffect, useMemo } from "react";
import { api, ApiError } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { downloadCSV } from "@/lib/csv-utils";
import type {
  Variable,
  Constraint,
  OptimizationProblem,
  MultiObjectiveConfig,
  MultiObjectiveResult,
} from "@/lib/types";
import { MultiObjectiveConfigForm, PairSelector, DEFAULT_OBJECTIVE } from "@/components/solve/MultiObjectiveConfig";
import { ParetoChart } from "@/components/solve/ParetoChart";
import { ImportSourcePanel } from "@/components/solve/ImportSourcePanel";
import { ConceptTooltip } from "@/components/ui/concept-tooltip";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { Download, Target } from "lucide-react";

const DEFAULT_CONFIG: MultiObjectiveConfig = {
  mode: "epsilon",
  objectives: [
    { ...DEFAULT_OBJECTIVE, label: "" },
    { ...DEFAULT_OBJECTIVE, label: "" },
  ],
  n_points: 10,
};

interface VariableRow extends Variable {
  id: string;
}

interface ConstraintRow extends Constraint {
  id: string;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 9);
}

export default function MultiObjectivePage() {
  const t = useTranslations("solve.multiObjective");
  const tHelp = useTranslations("solve.helpTooltips");
  const { activeWorkspaceId, activeWorkspaceName } = useAuth();

  // Credit source state
  const [creditSourceLabel, setCreditSourceLabel] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    async function fetchBalance() {
      try {
        if (activeWorkspaceId) {
          const pool = await api.getPoolStats(activeWorkspaceId);
          if (!cancelled) {
            setCreditSourceLabel(
              t("creditSourceWorkspace", { name: activeWorkspaceName ?? "", remaining: pool.available_credits })
            );
          }
        } else {
          const bal = await api.getCreditBalance();
          if (!cancelled) {
            setCreditSourceLabel(t("creditSourcePersonal", { remaining: bal.credits_balance }));
          }
        }
      } catch {
        if (!cancelled) {
          setCreditSourceLabel(
            activeWorkspaceId
              ? t("creditSourceWorkspaceShort", { name: activeWorkspaceName ?? "" })
              : t("creditSourcePersonalShort")
          );
        }
      }
    }
    fetchBalance();
    return () => { cancelled = true; };
  }, [activeWorkspaceId, activeWorkspaceName, t]);

  // Import state
  const [importedFrom, setImportedFrom] = useState<string | null>(null);

  // Problem state
  const [problemName, setProblemName] = useState("");
  const [variables, setVariables] = useState<VariableRow[]>([
    { id: uid(), name: "x", type: "continuous", lower_bound: 0 },
    { id: uid(), name: "y", type: "continuous", lower_bound: 0 },
  ]);
  const [constraints, setConstraints] = useState<ConstraintRow[]>([
    { id: uid(), expression: "x + y <= 10" },
  ]);

  // Multi-objective config
  const [config, setConfig] = useState<MultiObjectiveConfig>({
    ...DEFAULT_CONFIG,
    objectives: [
      { ...DEFAULT_CONFIG.objectives[0], label: t("defaultObjective1") },
      { ...DEFAULT_CONFIG.objectives[1], label: t("defaultObjective2") },
    ],
  });

  // Solve state
  const [result, setResult] = useState<MultiObjectiveResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pair selector for 3+ objectives
  const [axisPair, setAxisPair] = useState<[number, number]>([0, 1]);

  // Derived cost estimate
  const nPoints = config.n_points ?? 10;
  const perSolveCost = 1;
  const estimatedCredits = nPoints * perSolveCost;

  // Labels for pair selector
  const objectiveLabels = useMemo(
    () => config.objectives.map((o, i) => o.label || t("defaultObjectiveN", { n: i + 1 })),
    [config.objectives, t]
  );

  // Validation
  function validate(): string | null {
    if (variables.length === 0) return t("atLeastOneVariable");
    for (const v of variables) {
      if (!v.name.trim()) return t("variablesMustHaveName");
    }
    const hasEmptyExpr = config.objectives.some((o) => !o.expression.trim());
    if (hasEmptyExpr) {
      return t("allExpressionsRequired");
    }
    if (config.mode === "weighted") {
      const weightSum = config.objectives.reduce((sum, o) => sum + (o.weight ?? 0), 0);
      if (Math.abs(weightSum - 1.0) > 0.05) {
        return t("weightsMustSumToOne", { sum: weightSum.toFixed(2) });
      }
    }
    return null;
  }

  async function handleSolve() {
    const validationError = validate();
    if (validationError) {
      toast.error(validationError);
      return;
    }

    if (constraints.length === 0) {
      toast.warning(t("noConstraintsWarning"));
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const problem: OptimizationProblem = {
        name: problemName || t("title"),
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        variables: variables.map(({ id, ...v }) => v),
        objective: {
          sense: "minimize",
          expression: config.objectives[0].expression,
        },
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        constraints: constraints.map(({ id, ...c }) => c),
      };

      const res = await api.solveMultiObjective(problem, config, activeWorkspaceId ?? undefined);
      setResult(res);
      toast.success(t("paretoComputed", { count: res.n_solved }));

      // Credit source feedback
      if (!activeWorkspaceId) {
        toast(t("usingPersonalCredits"));
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 402 && activeWorkspaceId) {
        const msg = t("insufficientCredits");
        setError(msg);
        toast.error(msg);
      } else {
        const msg = getErrorMessage(err, t("solveFailed"));
        setError(msg);
        toast.error(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  function handleExportCsv() {
    if (!result || result.pareto_points.length === 0) return;
    const objLabels = result.labels.length > 0 ? result.labels : ["f1", "f2"];
    const solutionKeys = Object.keys(result.pareto_points[0]?.solution ?? {});
    const rows: (string | number | null | undefined)[][] = [
      ["#", ...objLabels, ...solutionKeys],
      ...result.pareto_points.map((p, i) => {
        const objValues = objLabels.map((label, idx) => {
          if (idx === 0) return p.f1;
          if (idx === 1) return p.f2;
          // For 3+ objectives, read from objective_values map
          const fromMap = p.objective_values?.[label];
          if (fromMap !== undefined) return fromMap;
          const ov = (p as unknown as Record<string, unknown>)[`f${idx + 1}`];
          return typeof ov === "number" ? ov : "";
        });
        return [i + 1, ...objValues, ...solutionKeys.map((k) => p.solution[k] ?? "")];
      }),
    ];
    downloadCSV("pareto_front.csv", rows);
  }

  // Import management
  function handleImport(importedVars: Variable[], importedConstraints: Constraint[], sourceName: string) {
    setVariables(importedVars.map((v) => ({ ...v, id: uid() })));
    setConstraints(importedConstraints.map((c) => ({ ...c, id: uid() })));
    setImportedFrom(sourceName);
    setProblemName(sourceName);
  }

  function handleClearImport() {
    setVariables([
      { id: uid(), name: "x", type: "continuous", lower_bound: 0 },
      { id: uid(), name: "y", type: "continuous", lower_bound: 0 },
    ]);
    setConstraints([{ id: uid(), expression: "x + y <= 10" }]);
    setImportedFrom(null);
    setProblemName("");
  }

  // Variable management
  function addVariable() {
    setVariables((prev) => [
      ...prev,
      { id: uid(), name: `var${prev.length + 1}`, type: "continuous", lower_bound: 0 },
    ]);
  }

  function removeVariable(id: string) {
    setVariables((prev) => prev.filter((v) => v.id !== id));
  }

  function updateVariable(id: string, patch: Partial<Variable>) {
    setVariables((prev) => prev.map((v) => (v.id === id ? { ...v, ...patch } : v)));
  }

  // Constraint management
  function addConstraint() {
    setConstraints((prev) => [...prev, { id: uid(), expression: "" }]);
  }

  function removeConstraint(id: string) {
    setConstraints((prev) => prev.filter((c) => c.id !== id));
  }

  function updateConstraint(id: string, expression: string) {
    setConstraints((prev) =>
      prev.map((c) => (c.id === id ? { ...c, expression } : c))
    );
  }

  const variableNames = variables.map((v) => v.name).filter(Boolean);
  const hasAllExpressions = config.objectives.every((o) => o.expression.trim() !== "");
  const canSolve = !loading && variables.length > 0 && hasAllExpressions;

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-foreground mb-2 flex items-center gap-2">
          <Target className="h-7 w-7 text-primary" />
          {t("title")}
          <HelpTooltip content={tHelp("multiObjective")} side="right" size={18} />
        </h1>
        <p className="text-muted-foreground">
          {t.rich("description", {
            tooltip: (chunks) => <ConceptTooltip termKey="pareto-front">{chunks}</ConceptTooltip>
          })}
        </p>
      </div>

      {!result && !loading && !error && (
        <div className="bg-primary/5 border border-primary/20 rounded-lg p-5 mb-6">
          <h3 className="text-sm font-semibold text-foreground mb-2">{t("gettingStartedTitle")}</h3>
          <ol className="text-sm text-muted-foreground space-y-1 list-decimal list-inside">
            <li>{t("gettingStartedStep1")}</li>
            <li>{t("gettingStartedStep2")}</li>
            <li>{t("gettingStartedStep3")}</li>
            <li>{t("gettingStartedStep4")}</li>
          </ol>
        </div>
      )}

      <ImportSourcePanel
        onImport={handleImport}
        importedFrom={importedFrom}
        onClear={handleClearImport}
      />

      {importedFrom && variables.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {variables.map((v) => (
            <span
              key={v.id}
              className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-mono bg-primary/10 text-primary border border-primary/20"
            >
              {v.name}
            </span>
          ))}
        </div>
      )}

      <div className="bg-card border border-border rounded-lg p-6 mb-6">
        <h2 className="text-lg font-semibold mb-4">{t("problemDefinition")}</h2>

        <div className="mb-4">
          <label className="block text-xs text-muted-foreground mb-1">
            {t("problemName")} <span className="text-muted-foreground/60">{t("problemNameOptional")}</span>
          </label>
          <Input
            value={problemName}
            onChange={(e) => setProblemName(e.target.value)}
            placeholder={t("problemNamePlaceholder")}
            className="max-w-md"
          />
        </div>

        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium">{t("variables")}</h3>
            <Button variant="outline" size="sm" onClick={addVariable} data-testid="add-variable-btn">
              {t("addVariable")}
            </Button>
          </div>
          <div className="space-y-2">
            {variables.map((v) => (
              <div
                key={v.id}
                className="flex flex-wrap gap-2 items-center p-3 bg-muted/20 border border-border rounded-md"
              >
                <input
                  type="text"
                  value={v.name}
                  onChange={(e) => updateVariable(v.id, { name: e.target.value })}
                  placeholder="name"
                  className="w-24 px-2 py-1 text-sm bg-background border border-border rounded font-mono focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50"
                  data-testid={`variable-name-${v.id}`}
                />
                <select
                  value={v.type}
                  onChange={(e) =>
                    updateVariable(v.id, { type: e.target.value as Variable["type"] })
                  }
                  className="px-2 py-1 text-sm bg-background border border-border rounded focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50"
                >
                  <option value="continuous">{t("continuous")}</option>
                  <option value="integer">{t("integer")}</option>
                  <option value="binary">{t("binary")}</option>
                </select>
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <span>{t("lowerBound")}</span>
                  <input
                    type="number"
                    value={v.lower_bound ?? ""}
                    onChange={(e) =>
                      updateVariable(v.id, {
                        lower_bound: e.target.value === "" ? undefined : parseFloat(e.target.value),
                      })
                    }
                    placeholder="0"
                    className="w-16 px-2 py-1 text-sm bg-background border border-border rounded font-mono focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50"
                  />
                  <span>{t("upperBound")}</span>
                  <input
                    type="number"
                    value={v.upper_bound ?? ""}
                    onChange={(e) =>
                      updateVariable(v.id, {
                        upper_bound: e.target.value === "" ? undefined : parseFloat(e.target.value),
                      })
                    }
                    placeholder="none"
                    className="w-16 px-2 py-1 text-sm bg-background border border-border rounded font-mono focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50"
                  />
                </div>
                <button
                  onClick={() => removeVariable(v.id)}
                  className="ml-auto text-muted-foreground hover:text-destructive transition-colors text-xs"
                  title={t("remove")}
                >
                  {t("remove")}
                </button>
              </div>
            ))}
            {variables.length === 0 && (
              <p className="text-xs text-muted-foreground italic">
                {t("noVariables")}
              </p>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium">{t("constraintsLabel")}</h3>
            <Button variant="outline" size="sm" onClick={addConstraint} data-testid="add-constraint-btn">
              {t("addConstraint")}
            </Button>
          </div>
          <div className="space-y-2">
            {constraints.map((c) => (
              <div key={c.id} className="flex gap-2 items-center">
                <input
                  type="text"
                  value={c.expression}
                  onChange={(e) => updateConstraint(c.id, e.target.value)}
                  placeholder={t("constraintPlaceholder")}
                  className="flex-1 px-3 py-1.5 text-sm bg-background border border-border rounded font-mono focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/50 placeholder:text-muted-foreground"
                  data-testid={`constraint-expr-${c.id}`}
                />
                <button
                  onClick={() => removeConstraint(c.id)}
                  className="text-muted-foreground hover:text-destructive transition-colors text-xs flex-shrink-0"
                >
                  {t("remove")}
                </button>
              </div>
            ))}
            {constraints.length === 0 && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                {t("noConstraints")}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="bg-card border border-border rounded-lg p-6 mb-6">
        <h2 className="text-lg font-semibold mb-4">{t("objectiveConfiguration")}</h2>
        <MultiObjectiveConfigForm
          value={config}
          onChange={setConfig}
          variables={variableNames}
        />
      </div>

      <div className="bg-card border border-border rounded-lg p-4 mb-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="text-sm text-muted-foreground">
          {t("estimatedCost")}{" "}
          <span className="font-semibold text-foreground tabular-nums">
            {t("estimatedCreditsValue", { credits: estimatedCredits })}
          </span>{" "}
          <span className="text-xs">
            {t("solvesBreakdown", { nPoints, perSolve: perSolveCost })}
          </span>
        </div>
        <div className="flex flex-col items-end gap-1">
          {creditSourceLabel && (
            <span className="text-xs text-muted-foreground">{creditSourceLabel}</span>
          )}
          <Button
            onClick={handleSolve}
            disabled={!canSolve}
            className="min-w-[180px]"
            data-testid="solve-btn"
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-foreground" />
                {t("solving")}
              </span>
            ) : (
              t("generateParetoFront")
            )}
          </Button>
        </div>
      </div>

      {loading && (
        <div className="mb-6 flex items-center justify-center py-12 bg-card border border-border rounded-lg">
          <div className="text-center">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary mx-auto mb-4" />
            <p className="text-sm text-muted-foreground">{t("solvingProgress")}</p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              {t("solvingProgressDetail", { nPoints })}
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 bg-destructive/10 text-destructive rounded-lg text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="bg-card border border-border rounded-lg p-6">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
            <h2 className="text-lg font-semibold">
              <ConceptTooltip termKey="pareto-front">{t("paretoFrontResults")}</ConceptTooltip>
            </h2>
            <div className="flex items-center gap-3">
              {config.objectives.length > 2 && (
                <PairSelector
                  labels={objectiveLabels}
                  selectedPair={axisPair}
                  onChange={setAxisPair}
                />
              )}
              <Button
                variant="default"
                size="sm"
                onClick={handleExportCsv}
                data-testid="export-csv-btn"
              >
                <Download className="h-4 w-4 mr-2" />
                {t("exportCsv")}
              </Button>
            </div>
          </div>
          <ParetoChart result={result} axisPair={axisPair} />
          <p className="mt-4 text-xs text-muted-foreground">
            {activeWorkspaceId
              ? t("chargedFromWorkspace", { name: activeWorkspaceName ?? "" })
              : t("chargedFromPersonal")}
          </p>
        </div>
      )}
    </div>
  );
}
