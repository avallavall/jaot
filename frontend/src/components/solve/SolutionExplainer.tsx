"use client";

import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useSolutionExplanation } from "@/hooks/useSolutionExplanation";
import { resolveErrorKey } from "@/lib/llm-event-codes";
import { ByokHint } from "@/components/llm/ByokHint";
import type { Conversation } from "@/lib/llm-types";

interface SolutionExplainerProps {
  /** Execution whose solution + sensitivity the backend will load and explain. */
  executionId: string;
  /** Only solved (optimal/feasible) executions can be explained. */
  canExplain: boolean;
}

/**
 * "Explain this solution" panel on the execution result page.
 *
 * Creates a short-lived LLM conversation on first use, then streams a grounded,
 * plain-language explanation from POST /llm/conversations/{id}/explain-solution.
 * The backend loads the solution + sensitivity from the execution itself, so the
 * client only passes the execution id.
 */
export function SolutionExplainer({ executionId, canExplain }: SolutionExplainerProps) {
  const t = useTranslations("solve.explainer");
  const tBuilder = useTranslations("builder");
  const stream = useSolutionExplanation();
  const conversationIdRef = useRef<string | null>(null);
  const [started, setStarted] = useState(false);
  const [setupFailed, setSetupFailed] = useState(false);

  const runExplain = useCallback(async () => {
    setSetupFailed(false);
    setStarted(true);
    try {
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
  }, [executionId, stream]);

  if (!canExplain) {
    return (
      <div className="bg-card border border-border rounded-lg p-4">
        <p className="text-sm text-muted-foreground">{t("unavailable")}</p>
      </div>
    );
  }

  const showError = setupFailed || stream.errorCode !== null;
  const errorMessage = stream.errorCode
    ? tBuilder(resolveErrorKey(stream.errorCode))
    : tBuilder(resolveErrorKey("service_unavailable"));

  return (
    <div className="bg-card border border-border rounded-lg p-4 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            {t("title")}
          </h3>
          <p className="text-sm text-muted-foreground max-w-prose">{t("description")}</p>
        </div>
        {!stream.streaming && (
          <Button variant="outline" size="sm" className="gap-2" onClick={runExplain}>
            <Sparkles className="h-4 w-4" />
            {started ? t("regenerate") : t("button")}
          </Button>
        )}
      </div>

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
