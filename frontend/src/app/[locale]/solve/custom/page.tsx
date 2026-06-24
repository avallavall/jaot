"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { SolveResult, AsyncTask } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Loader2,
  ArrowLeft,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Coins,
  Code,
  FileJson,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { SolverSelect } from "@/components/solve/SolverSelect";
import { useSolvers } from "@/hooks/useSolvers";

const EXAMPLE_PROBLEM = {
  name: "production_planning",
  description: "Maximize profit from production",
  objective: {
    sense: "maximize",
    expression: "50*widgets + 40*gadgets + 60*gizmos"
  },
  variables: [
    { name: "widgets", type: "integer", lower_bound: 0, upper_bound: 100 },
    { name: "gadgets", type: "integer", lower_bound: 0, upper_bound: 80 },
    { name: "gizmos", type: "integer", lower_bound: 0, upper_bound: 50 }
  ],
  constraints: [
    { name: "machine_hours", expression: "2*widgets + 3*gadgets + 2*gizmos <= 240" },
    { name: "labor_hours", expression: "4*widgets + 2*gadgets + 3*gizmos <= 200" },
    { name: "raw_material", expression: "widgets + gadgets + gizmos <= 150" }
  ],
  options: {
    time_limit_seconds: 30
  }
};

export default function CustomSolvePage() {
  const t = useTranslations("solve.custom");
  const router = useRouter();
  const { solverName, setSolverName, availableSolvers, solversLoading } = useSolvers();
  const [solving, setSolving] = useState(false);
  const [inputJson, setInputJson] = useState(JSON.stringify(EXAMPLE_PROBLEM, null, 2));
  const [result, setResult] = useState<SolveResult | null>(null);
  const [asyncTask, setAsyncTask] = useState<AsyncTask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors?: string[];
    estimated_credits?: number;
  } | null>(null);

  const handleValidate = async () => {
    setError(null);
    setValidationResult(null);

    try {
      const problem = JSON.parse(inputJson);
      const validation = await api.validateProblem(problem);
      setValidationResult(validation);
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        setError(t("invalidJsonFormat"));
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError(t("validationFailed"));
      }
    }
  };

  const handleSolve = async () => {
    setError(null);
    setResult(null);
    setAsyncTask(null);
    setSolving(true);

    try {
      const problem = JSON.parse(inputJson);

      const solveResult = await api.solve({ ...problem, solver_name: solverName });
      setResult(solveResult);
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        setError(t("invalidJsonFormat"));
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError(t("failedToSolve"));
      }
    } finally {
      setSolving(false);
    }
  };

  const loadExample = () => {
    setInputJson(JSON.stringify(EXAMPLE_PROBLEM, null, 2));
    setValidationResult(null);
    setResult(null);
    setError(null);
  };

  return (
    <div className="container mx-auto py-8 px-4">
      <Button variant="ghost" onClick={() => router.push("/solve")} className="mb-4">
        <ArrowLeft className="h-4 w-4 mr-2" />
        {t("backToTemplates")}
      </Button>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-foreground flex items-center gap-3">
            <Code className="h-8 w-8" />
            {t("title")}
          </h1>
          <p className="text-muted-foreground mt-1">
            {t("subtitle")}
          </p>
        </div>
        <Badge variant="secondary" className="text-lg px-3 py-1">
          {t("credits", { count: validationResult?.estimated_credits || "1+" })}
        </Badge>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <FileJson className="h-5 w-5" />
                {t("problemDefinition")}
              </CardTitle>
              <Button variant="outline" size="sm" onClick={loadExample}>
                {t("loadExample")}
              </Button>
            </div>
            <CardDescription>
              {t("defineInJson")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea
              value={inputJson}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInputJson(e.target.value)}
              className="font-mono text-sm min-h-[400px]"
              placeholder={t("enterProblemDefinition")}
            />

            {/* Solver selector — Phase 7.1 / D-7.1-02 */}
            <SolverSelect
              solverName={solverName}
              onSolverChange={setSolverName}
              availableSolvers={availableSolvers}
              loading={solversLoading}
            />

            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={handleValidate}
                className="flex-1"
              >
                {t("validate")}
              </Button>
              <Button
                data-testid="solve-submit-btn"
                onClick={handleSolve}
                disabled={solving}
                className="flex-1"
              >
                {solving ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    {t("solving")}
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    {t("solve")}
                  </>
                )}
              </Button>
            </div>

            {validationResult && (
              <div
                className={`p-4 rounded-lg border ${
                  validationResult.valid
                    ? "bg-green-50 border-green-200"
                    : "bg-red-50 border-red-200"
                }`}
              >
                <div className="flex items-center gap-2">
                  {validationResult.valid ? (
                    <CheckCircle2 className="h-5 w-5 text-green-600" />
                  ) : (
                    <XCircle className="h-5 w-5 text-red-600" />
                  )}
                  <span className="font-medium">
                    {validationResult.valid ? t("validProblem") : t("invalidProblem")}
                  </span>
                </div>
                {validationResult.valid && validationResult.estimated_credits && (
                  <p className="mt-2 text-sm text-green-700">
                    {t("estimatedCost", { credits: validationResult.estimated_credits })}
                  </p>
                )}
                {validationResult.errors && validationResult.errors.length > 0 && (
                  <ul className="mt-2 text-sm text-red-700 list-disc list-inside">
                    {validationResult.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("result")}</CardTitle>
            <CardDescription>{t("resultDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            {error && (
              <div className="p-4 bg-destructive/10 border border-destructive/20 rounded-lg">
                <div className="flex items-center gap-2 text-destructive">
                  <XCircle className="h-5 w-5" />
                  <span className="font-medium">{t("error")}</span>
                </div>
                <p className="mt-2 text-sm text-destructive">{error}</p>
              </div>
            )}

            {result && (
              <div className="space-y-6">
                <div className="flex items-center gap-3">
                  {result.status === "optimal" ? (
                    <CheckCircle2 className="h-8 w-8 text-green-600" />
                  ) : result.status === "feasible" ? (
                    <CheckCircle2 className="h-8 w-8 text-yellow-600" />
                  ) : (
                    <XCircle className="h-8 w-8 text-destructive" />
                  )}
                  <div>
                    <p className="font-semibold text-lg capitalize">{result.status}</p>
                    {result.objective_value != null && (
                      <p className="text-2xl font-bold text-primary">
                        {result.objective_value.toLocaleString(undefined, {
                          maximumFractionDigits: 4,
                        })}
                      </p>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="p-3 bg-muted rounded-lg">
                    <div className="flex items-center gap-2 text-muted-foreground text-sm">
                      <Clock className="h-4 w-4" />
                      {t("solveTime")}
                    </div>
                    <p className="font-semibold mt-1">
                      {(result.solve_time_seconds * 1000).toFixed(2)} ms
                    </p>
                  </div>
                  <div className="p-3 bg-muted rounded-lg">
                    <div className="flex items-center gap-2 text-muted-foreground text-sm">
                      <Coins className="h-4 w-4" />
                      {t("creditsLabel")}
                    </div>
                    <p className="font-semibold mt-1">
                      {t("creditsUsedRemaining", { used: result.credits_used, remaining: result.credits_remaining ?? 0 })}
                    </p>
                  </div>
                </div>

                {(() => {
                  const modelData = (result as unknown as Record<string, unknown>).model;
                  if (!modelData || typeof modelData !== 'object') return null;
                  const entries = Object.entries(modelData as Record<string, unknown>);
                  if (entries.length === 0) return null;
                  return (
                    <div>
                      <Label className="text-sm text-muted-foreground">{t("modelLabel")}</Label>
                      <div className="mt-2 p-4 bg-muted rounded-lg">
                        <div className="grid grid-cols-2 gap-2">
                          {entries.map(([name, value]) => (
                            <div key={name} className="flex justify-between">
                              <span className="font-mono text-sm">{name}</span>
                              <span className="font-semibold">
                                {typeof value === "number"
                                  ? value.toLocaleString(undefined, { maximumFractionDigits: 4 })
                                  : String(value)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })()}

                {result.error_message && (
                  <div className="p-4 bg-destructive/10 border border-destructive/20 rounded-lg">
                    <p className="text-sm text-destructive">{result.error_message}</p>
                  </div>
                )}
              </div>
            )}

            {/* Async task dispatched — Phase 7.1 / D-7.1-02 */}
            {asyncTask && !result && !error && (
              <div className="p-4 bg-primary/5 border border-primary/20 rounded-lg">
                <div className="flex items-center gap-2 text-primary">
                  <CheckCircle2 className="h-5 w-5" />
                  <span className="font-medium">{t("asyncTaskQueued")}</span>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  {t("asyncTaskId", { id: asyncTask.task_id })}
                </p>
              </div>
            )}

            {!result && !asyncTask && !error && (
              <div className="h-64 flex items-center justify-center text-muted-foreground">
                <p>{t("runSolverToSeeResults")}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>{t("formatReference")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
            <div>
              <h4 className="font-semibold mb-2">{t("objective")}</h4>
              <pre className="bg-muted p-2 rounded text-xs overflow-auto">
{`{
  "sense": "maximize",
  "expression": "3*x + 2*y"
}`}
              </pre>
            </div>
            <div>
              <h4 className="font-semibold mb-2">{t("variables")}</h4>
              <pre className="bg-muted p-2 rounded text-xs overflow-auto">
{`[
  {"name": "x", "type": "integer",
   "lower_bound": 0, "upper_bound": 100},
  {"name": "y", "type": "binary"}
]`}
              </pre>
            </div>
            <div>
              <h4 className="font-semibold mb-2">{t("constraints")}</h4>
              <pre className="bg-muted p-2 rounded text-xs overflow-auto">
{`[
  {"expression": "x + y <= 10"},
  {"expression": "2*x >= 5"}
]`}
              </pre>
            </div>
          </div>
          <p className="mt-4 text-muted-foreground text-sm">
            {t("variableTypes")}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
