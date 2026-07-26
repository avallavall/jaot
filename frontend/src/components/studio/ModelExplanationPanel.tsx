"use client";

import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { resolveErrorKey } from "@/lib/llm-event-codes";
import { AdvancedModelToggle } from "@/components/llm/AdvancedModelToggle";
import { ByokHint } from "@/components/llm/ByokHint";
import { useAdvancedModel } from "@/hooks/useAdvancedModel";
import { useModelExplanation } from "./explain/ModelExplanationProvider";

/**
 * "Explain this model" card on the Analyze lens. The streaming state + conversation
 * live in `ModelExplanationProvider` (mounted above the tabs), so an in-flight
 * explanation survives leaving and re-entering the Analyze tab — this component is a
 * pure consumer/view. The backend loads the model + its computed stats from the
 * project draft itself (Python computes; the model only narrates).
 */
export function ModelExplanationPanel() {
  const t = useTranslations("studio");
  const tBuilder = useTranslations("builder");
  const {
    text,
    streaming,
    errorCode,
    requestId,
    started,
    setupFailed,
    runExplain,
  } = useModelExplanation();
  const [advanced, setAdvanced] = useAdvancedModel();

  const showError = setupFailed || errorCode !== null;
  const errorMessage = errorCode
    ? tBuilder(resolveErrorKey(errorCode))
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
          <p className="text-sm text-muted-foreground max-w-prose">
            {t("explainDescription")}
          </p>
        </div>
        {!streaming && (
          <div className="flex items-center gap-3">
            <AdvancedModelToggle checked={advanced} onChange={setAdvanced} />
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
          </div>
        )}
      </div>

      {streaming && !text && (
        <p className="text-sm text-muted-foreground animate-pulse">
          {t("explainThinking")}
        </p>
      )}

      {text && (
        <div className="prose prose-sm dark:prose-invert max-w-none text-foreground">
          <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
        </div>
      )}

      {showError && (
        <p className="text-sm text-destructive">
          {errorMessage}
          {requestId && (
            <span className="text-muted-foreground">
              {" "}
              {t("explainRef", { requestId })}
            </span>
          )}
        </p>
      )}

      {text && !streaming && !showError && (
        <p className="text-xs text-muted-foreground">{t("explainGrounded")}</p>
      )}

      {started && <ByokHint />}
    </div>
  );
}
