"use client";

import { useTranslations } from "next-intl";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { PlatformKpiCard } from "./PlatformKpiCard";
import { fmtInt, fmtNum, fmtPct, fmtEur } from "./platform-helpers";
import type { AiUsage } from "./platform-types";

export function AiSection({ data }: { data: AiUsage }) {
  const t = useTranslations("admin.platformAnalytics");

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">{t("ai.title")}</h2>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <PlatformKpiCard label={t("ai.conversations")} value={fmtInt(data.conversations)} />
        <PlatformKpiCard label={t("ai.messages")} value={fmtInt(data.messages)} />
        <PlatformKpiCard label={t("ai.orgsUsingAi")} value={fmtInt(data.orgs_using_ai)} />
        <PlatformKpiCard label={t("ai.totalCost")} value={fmtEur(data.total_cost_eur)} />
        <PlatformKpiCard
          label={t("ai.acceptanceRate")}
          value={fmtPct(data.acceptance_rate)}
          hint={t("ai.acceptanceHint")}
        />
        <PlatformKpiCard label={t("ai.inputTokens")} value={fmtInt(data.total_input_tokens)} />
        <PlatformKpiCard label={t("ai.outputTokens")} value={fmtInt(data.total_output_tokens)} />
        <PlatformKpiCard
          label={t("ai.costPerConversation")}
          value={fmtEur(data.avg_cost_per_conversation)}
        />
        <PlatformKpiCard
          label={t("ai.messagesPerConversation")}
          value={fmtNum(data.messages_per_conversation)}
        />
        <Card>
          <CardContent className="flex h-full items-center justify-around gap-2 p-4">
            <span className="flex items-center gap-1.5 text-sm">
              <ThumbsUp className="h-4 w-4 text-[var(--success)]" />
              <span className="font-semibold tabular-nums">{fmtInt(data.thumbs_up)}</span>
            </span>
            <span className="flex items-center gap-1.5 text-sm">
              <ThumbsDown className="h-4 w-4 text-destructive" />
              <span className="font-semibold tabular-nums">{fmtInt(data.thumbs_down)}</span>
            </span>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
