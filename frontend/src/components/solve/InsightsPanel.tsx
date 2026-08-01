"use client";

import { useState, useEffect } from "react";
import { Lightbulb, AlertTriangle, CheckCircle, Info } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { api } from "@/lib/api";

interface InsightData {
  category: string;
  message: string;
  severity: string;
  /** Stable identifier for the localized text; empty on older stored insights. */
  code?: string;
  params?: Record<string, unknown>;
}

interface InsightsPanelProps {
  executionId: string;
}

const SEVERITY_STYLES: Record<string, { icon: typeof Info; bg: string; border: string; text: string }> = {
  success: {
    icon: CheckCircle,
    bg: "bg-green-50 dark:bg-green-900/20",
    border: "border-green-200 dark:border-green-800",
    text: "text-green-800 dark:text-green-200",
  },
  warning: {
    icon: AlertTriangle,
    bg: "bg-yellow-50 dark:bg-yellow-900/20",
    border: "border-yellow-200 dark:border-yellow-800",
    text: "text-yellow-800 dark:text-yellow-200",
  },
  info: {
    icon: Info,
    bg: "bg-blue-50 dark:bg-blue-900/20",
    border: "border-blue-200 dark:border-blue-800",
    text: "text-blue-800 dark:text-blue-200",
  },
};

const VARIABLE_TYPES = ["binary", "integer", "continuous"] as const;

export function InsightsPanel({ executionId }: InsightsPanelProps) {
  const t = useTranslations("solve.visualization");
  const ti = useTranslations("solve.insights");
  const locale = useLocale();
  const [insights, setInsights] = useState<InsightData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchInsights() {
      try {
        const data = await api.getExecutionInsights(executionId);
        if (!cancelled) {
          setInsights(data.insights ?? []);
        }
      } catch {
        // Silently fail — insights are non-critical
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchInsights();
    return () => { cancelled = true; };
  }, [executionId]);

  // The API's `message` stays English — it is what MCP and API clients read. The UI
  // renders the `code` instead, so the numbers get the reader's notation too, and
  // falls back to the message for any insight whose code we do not have a text for.
  const insightText = (insight: InsightData): string => {
    if (!insight.code) return insight.message;
    const key = `codes.${insight.code}`;
    if (!ti.has(key)) return insight.message;
    const params =
      insight.code === "variables.type_mix"
        ? { mix: variableMix(insight.params ?? {}) }
        : (insight.params ?? {});
    return ti(key, params as Record<string, string | number>);
  };

  // "8 binary, 12 continuous" is three translatable words and a list separator, so
  // the backend sends counts and the phrase is assembled here.
  const variableMix = (params: Record<string, unknown>): string => {
    const parts = VARIABLE_TYPES.filter((type) => typeof params[type] === "number").map((type) =>
      ti("varTypeCount", { count: params[type] as number, type: ti(`varTypes.${type}`) }),
    );
    return new Intl.ListFormat(locale, { style: "long", type: "conjunction" }).format(parts);
  };

  const categoryLabel = (category: string): string =>
    ti.has(`category.${category}`) ? ti(`category.${category}`) : category;

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm py-4">
        <Lightbulb className="h-4 w-4 animate-pulse" />
        {t("loadingInsights")}
      </div>
    );
  }

  if (insights.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4">{t("noInsights")}</p>
    );
  }

  return (
    <div className="space-y-2">
      {insights.map((insight, i) => {
        const style = SEVERITY_STYLES[insight.severity] || SEVERITY_STYLES.info;
        const Icon = style.icon;
        return (
          <div
            key={i}
            className={`flex items-start gap-3 p-3 rounded-md border ${style.bg} ${style.border}`}
          >
            <Icon className={`h-4 w-4 mt-0.5 flex-shrink-0 ${style.text}`} />
            <div>
              <span className={`text-xs font-medium uppercase tracking-wide ${style.text}`}>
                {categoryLabel(insight.category)}
              </span>
              <p className={`text-sm mt-0.5 ${style.text}`}>{insightText(insight)}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
