"use client";

import { useState, useEffect } from "react";
import { Lightbulb, AlertTriangle, CheckCircle, Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";

interface InsightData {
  category: string;
  message: string;
  severity: string;
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

export function InsightsPanel({ executionId }: InsightsPanelProps) {
  const t = useTranslations("solve.visualization");
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
                {insight.category}
              </span>
              <p className={`text-sm mt-0.5 ${style.text}`}>{insight.message}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
