"use client";

import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, Sparkles } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useInfeasibilityExplanation } from "@/hooks/useInfeasibilityExplanation";
import { resolveErrorKey } from "@/lib/llm-event-codes";
import { ByokHint } from "@/components/llm/ByokHint";
import type { Conversation, InfeasibilityAnalysis } from "@/lib/llm-types";

interface InfeasibilityPanelProps {
  /** Execution whose conflict (IIS) the backend computes and the LLM explains. */
  executionId: string;
  /** Pre-computed IIS persisted on the execution, shown immediately on revisit. */
  initialAnalysis?: InfeasibilityAnalysis | null;
}

/**
 * "Why is this infeasible?" panel on the execution result page.
 *
 * Shown only for INFEASIBLE executions. On demand it (1) computes the minimal
 * conflicting set via POST /solve/{id}/infeasibility-analysis, surfaces the exact
 * conflicting constraints/bounds, then (2) streams a grounded plain-language
 * explanation + fixes from POST /llm/conversations/{id}/explain-infeasibility.
 * When the model is too large for an exact IIS the explanation is flagged heuristic.
 */
export function InfeasibilityPanel({ executionId, initialAnalysis }: InfeasibilityPanelProps) {
  const t = useTranslations("solve.infeasibility");
  const tBuilder = useTranslations("builder");
  const stream = useInfeasibilityExplanation();
  const conversationIdRef = useRef<string | null>(null);
  const [analysis, setAnalysis] = useState<InfeasibilityAnalysis | null>(initialAnalysis ?? null);
  const [analyzing, setAnalyzing] = useState(false);
  const [started, setStarted] = useState(false);
  const [setupFailed, setSetupFailed] = useState(false);

  const runExplain = useCallback(async () => {
    setSetupFailed(false);
    setStarted(true);
    try {
      // 1. Compute (or reuse) the minimal conflicting set so the LLM grounds on it.
      let current = analysis;
      if (!current) {
        setAnalyzing(true);
        try {
          current = await api.analyzeInfeasibility(executionId);
          setAnalysis(current);
        } finally {
          setAnalyzing(false);
        }
      }

      // 2. Open a short-lived conversation and stream the explanation.
      if (!conversationIdRef.current) {
        const conv = await api.request<Conversation>("/api/v2/llm/conversations", {
          method: "POST",
          body: JSON.stringify({}),
        });
        conversationIdRef.current = conv.id;
      }
      await stream.explain(conversationIdRef.current, { execution_id: executionId });
    } catch {
      setSetupFailed(true);
    }
  }, [analysis, executionId, stream]);

  const showError = setupFailed || stream.errorCode !== null;
  const errorMessage = stream.errorCode
    ? tBuilder(resolveErrorKey(stream.errorCode))
    : tBuilder(resolveErrorKey("service_unavailable"));

  const isHeuristic = analysis?.method === "llm_only";
  const hasConflictMembers =
    (analysis?.iis_constraints.length ?? 0) > 0 ||
    (analysis?.iis_variable_bounds.length ?? 0) > 0;

  return (
    <div className="bg-card border border-border rounded-lg p-4 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            {t("title")}
          </h3>
          <p className="text-sm text-muted-foreground max-w-prose">{t("description")}</p>
        </div>
        {!stream.streaming && !analyzing && (
          <Button variant="outline" size="sm" className="gap-2" onClick={runExplain}>
            <Sparkles className="h-4 w-4" />
            {started ? t("regenerate") : t("button")}
          </Button>
        )}
      </div>

      {analyzing && (
        <p className="text-sm text-muted-foreground animate-pulse">{t("analyzing")}</p>
      )}

      {analysis && hasConflictMembers && (
        <div className="rounded-md border border-amber-200 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/30 p-3 space-y-2">
          <p className="text-sm font-medium text-amber-900 dark:text-amber-200">
            {t("conflictHeading")}
          </p>
          <div className="flex flex-wrap gap-2">
            {analysis.iis_constraints.map((name) => (
              <code
                key={`c-${name}`}
                className="rounded bg-amber-100 dark:bg-amber-900/50 px-2 py-1 text-xs font-mono text-amber-900 dark:text-amber-100"
              >
                {name}
              </code>
            ))}
            {analysis.iis_variable_bounds.map((bound) => (
              <code
                key={`b-${bound}`}
                className="rounded bg-amber-100 dark:bg-amber-900/50 px-2 py-1 text-xs font-mono text-amber-900 dark:text-amber-100"
              >
                {bound}
              </code>
            ))}
          </div>
          <p className="text-xs text-amber-800 dark:text-amber-300">{t("conflictHint")}</p>
        </div>
      )}

      {isHeuristic && (
        <p className="text-xs text-muted-foreground">
          <span className="inline-block rounded bg-muted px-1.5 py-0.5 font-medium text-foreground">
            {t("heuristic")}
          </span>{" "}
          {t("heuristicHint")}
        </p>
      )}

      {stream.streaming && !stream.text && (
        <p className="text-sm text-muted-foreground animate-pulse">{t("thinking")}</p>
      )}

      {stream.text && (
        <div className="prose prose-sm dark:prose-invert max-w-none text-foreground">
          <Markdown remarkPlugins={[remarkGfm]}>{stream.text}</Markdown>
        </div>
      )}

      {showError && (
        <p className="text-sm text-destructive">
          {errorMessage}
          {stream.requestId && (
            <span className="text-muted-foreground">
              {" "}
              {t("ref", { requestId: stream.requestId })}
            </span>
          )}
        </p>
      )}

      {stream.text && !stream.streaming && !showError && (
        <p className="text-xs text-muted-foreground">{t("grounded")}</p>
      )}

      {started && <ByokHint />}
    </div>
  );
}
