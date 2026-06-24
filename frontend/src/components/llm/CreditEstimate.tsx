"use client";

import { Coins } from "lucide-react";
import type { Formulation } from "@/lib/llm-types";
import { useTranslations } from "next-intl";

/**
 * Estimate the credit cost for solving a formulation.
 * Mirrors the backend formula from app/services/credits_service.py:
 *   base(1) + vars * 0.1 + int_vars * 0.3 + bin_vars * 0.2 + constraints * 0.05
 */
export function estimateCredits(formulation: Formulation): number {
  const vars = formulation.variables.length;
  const intVars = formulation.variables.filter((v) => v.type === "integer").length;
  const binVars = formulation.variables.filter((v) => v.type === "binary").length;
  const constraints = formulation.constraints.length;

  const cost = 1 + vars * 0.1 + intVars * 0.3 + binVars * 0.2 + constraints * 0.05;
  return Math.max(1, Math.round(cost));
}

interface CreditEstimateProps {
  formulation: Formulation;
  aiMessagesCount: number;
  creditCostPerMessage?: number;
  /** Token cost for processing an attached document */
  documentTokens?: number;
}

/**
 * Compact card showing estimated credit cost breakdown:
 * solve cost + AI generation cost.
 */
export function CreditEstimate({
  formulation,
  aiMessagesCount,
  creditCostPerMessage = 1,
  documentTokens,
}: CreditEstimateProps) {
  const t = useTranslations("builder");
  const solveCost = estimateCredits(formulation);
  const aiCost = aiMessagesCount * creditCostPerMessage;
  const total = solveCost + aiCost + (documentTokens ?? 0);

  return (
    <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
      <Coins className="h-4 w-4 mt-0.5 flex-shrink-0" />
      <div className="space-y-0.5">
        <div>
          {t("llm.creditEstimate.solveCost")} <span className="font-medium text-foreground">{solveCost}</span> {t("llm.creditEstimate.credits")}
        </div>
        <div>
          {t("llm.creditEstimate.aiGeneration")}{" "}
          <span className="font-medium text-foreground">{aiCost}</span> {t("llm.creditEstimate.credits")}
          {aiMessagesCount > 0 && (
            <span className="text-xs ml-1">{t("llm.creditEstimate.messageCount", { count: aiMessagesCount })}</span>
          )}
        </div>
        {documentTokens != null && documentTokens > 0 && (
          <div>
            {t("llm.attachment.documentCost")}{" "}
            <span className="font-medium text-foreground">~{documentTokens}</span> {t("llm.creditEstimate.credits")}
          </div>
        )}
        <div className="pt-0.5 border-t border-border/50">
          {t("llm.creditEstimate.totalSessionCost")}{" "}
          <span className="font-semibold text-foreground">{total}</span> {t("llm.creditEstimate.credits")}
        </div>
      </div>
    </div>
  );
}
