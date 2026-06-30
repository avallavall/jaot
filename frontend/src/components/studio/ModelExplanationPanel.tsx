"use client";

import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useExplanationStream } from "@/hooks/useExplanationStream";
import { resolveErrorKey } from "@/lib/llm-event-codes";
import { ByokHint } from "@/components/llm/ByokHint";
import type { Conversation } from "@/lib/llm-types";

interface ModelExplanationPanelProps {
  /** The ModelProject id whose draft (HEAD) the backend loads, stats and all. */
  projectId: string;
}

/**
 * "Explain this model" card on the Analyze lens. Creates a short-lived LLM
 * conversation on first use, then streams a grounded, plain-language explanation
 * from POST /llm/conversations/{id}/explain-model. The backend loads the model +
 * its computed stats from the project draft itself (Python computes; the model only
 * narrates), so the client passes just the project id.
 */
export function ModelExplanationPanel({ projectId }: ModelExplanationPanelProps) {
  const t = useTranslations("studio");
  const tBuilder = useTranslations("builder");
  const stream = useExplanationStream();
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
      await stream.explain(
        `/api/v2/llm/conversations/${conversationIdRef.current}/explain-model`,
        { project_id: projectId }
      );
    } catch {
      setSetupFailed(true);
    }
  }, [projectId, stream]);

  const showError = setupFailed || stream.errorCode !== null;
  const errorMessage = stream.errorCode
    ? tBuilder(resolveErrorKey(stream.errorCode))
    : tBuilder(resolveErrorKey("service_unavailable"));

  return (
    <div
      data-testid="studio-explain-model"
      className="bg-card border rounded-lg p-4 space-y-3"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            {t("explainTitle")}
          </h3>
          <p className="text-sm text-muted-foreground max-w-prose">{t("explainDescription")}</p>
        </div>
        {!stream.streaming && (
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={runExplain}
            data-testid="studio-explain-model-run"
          >
            <Sparkles className="h-4 w-4" />
            {started ? t("explainRegenerate") : t("explainModel")}
          </Button>
        )}
      </div>

      {stream.streaming && !stream.text && (
        <p className="text-sm text-muted-foreground animate-pulse">{t("explainThinking")}</p>
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
              {t("explainRef", { requestId: stream.requestId })}
            </span>
          )}
        </p>
      )}

      {stream.text && !stream.streaming && !showError && (
        <p className="text-xs text-muted-foreground">{t("explainGrounded")}</p>
      )}

      {started && <ByokHint />}
    </div>
  );
}
