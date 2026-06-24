"use client";

import { useState } from "react";
import { Play } from "lucide-react";
import type { Formulation, ValidationError } from "@/lib/llm-types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { VisualView } from "./VisualView";
import { TextView } from "./TextView";
import { MathView } from "./MathView";
import { useTranslations } from "next-intl";

type ViewMode = "visual" | "text" | "math";

interface FormulationPanelProps {
  formulation: Formulation | null;
  validationErrors: ValidationError[];
  streaming: boolean;
  rawText: string;
  onOpenInBuilder?: () => void;
  onSolve?: () => void;
  solving?: boolean;
  /** True when the formulation uses parametric notation (∑, ∀, x_{i,j}). */
  parametric?: boolean;
}

function SkeletonSection({ title }: { title: string }) {
  return (
    <Card>
      <div className="p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-4 w-4 rounded" />
          <Skeleton className="h-4 w-24" />
          <span className="text-sm font-medium text-muted-foreground">{title}</span>
        </div>
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    </Card>
  );
}

function StreamingPreview({ t }: { t: (key: string, values?: Record<string, string | number | Date>) => string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
          <span className="text-sm font-medium text-muted-foreground">
            {t("llm.formulation.generating")}
          </span>
        </div>
        <div className="space-y-2">
          <SkeletonSection title={t("llm.formulation.variables")} />
          <SkeletonSection title={t("llm.formulation.constraints")} />
          <SkeletonSection title={t("llm.formulation.objective")} />
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Three-view formulation display panel.
 *
 * Renders the same Formulation data in three synchronized views:
 * - Visual: structured cards and tables
 * - Text: markdown description
 * - Math: LaTeX notation via KaTeX
 *
 * Supports streaming state with skeleton placeholders and raw text preview.
 */
export function FormulationPanel({
  formulation,
  validationErrors,
  streaming,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  rawText,
  onOpenInBuilder,
  onSolve,
  solving = false,
  parametric = false,
}: FormulationPanelProps) {
  const t = useTranslations("builder");
  const [activeViews, setActiveViews] = useState<ViewMode[]>(["visual", "math"]);

  const toggleView = (view: ViewMode) => {
    setActiveViews((prev) => {
      if (prev.includes(view)) {
        // Don't allow removing the last view
        if (prev.length <= 1) return prev;
        return prev.filter((v) => v !== view);
      }
      return [...prev, view];
    });
  };

  const errorCount = validationErrors.length;
  const hasFormulation = formulation !== null;

  // Streaming state: show skeleton or raw text preview
  if (streaming && !hasFormulation) {
    return <StreamingPreview t={t} />;
  }

  // No formulation yet and not streaming
  if (!hasFormulation) {
    return null;
  }

  const viewCount = activeViews.length;
  const gridCols =
    viewCount === 3
      ? "grid-cols-3"
      : viewCount === 2
        ? "grid-cols-2"
        : "grid-cols-1";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Tabs value={activeViews[0]} className="w-auto">
          <TabsList>
            <TabsTrigger
              value="visual"
              onClick={() => toggleView("visual")}
              className={cn(!activeViews.includes("visual") && "opacity-50")}
            >
              {t("llm.formulation.visual")}
            </TabsTrigger>
            <TabsTrigger
              value="text"
              onClick={() => toggleView("text")}
              className={cn(!activeViews.includes("text") && "opacity-50")}
            >
              {t("llm.formulation.text")}
            </TabsTrigger>
            <TabsTrigger
              value="math"
              onClick={() => toggleView("math")}
              className={cn(!activeViews.includes("math") && "opacity-50")}
            >
              {t("llm.formulation.math")}
            </TabsTrigger>
          </TabsList>
        </Tabs>

        {streaming && (
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
            <span className="text-xs text-muted-foreground">{t("llm.formulation.updating")}</span>
          </div>
        )}
      </div>

      <div className={cn("grid gap-4", gridCols)}>
        {activeViews.includes("visual") && (
          <Card className="overflow-hidden">
            <CardContent className="p-4">
              <VisualView
                formulation={formulation}
                validationErrors={validationErrors}
                parametric={parametric}
              />
            </CardContent>
          </Card>
        )}

        {activeViews.includes("text") && (
          <Card className="overflow-hidden">
            <CardContent className="p-4">
              <TextView formulation={formulation} />
            </CardContent>
          </Card>
        )}

        {activeViews.includes("math") && (
          <Card className="overflow-hidden">
            <CardContent className="p-4">
              <MathView formulation={formulation} />
            </CardContent>
          </Card>
        )}
      </div>

      {hasFormulation && (
        <TooltipProvider>
          <div className="flex justify-end gap-2">
            {errorCount > 0 ? (
              <Button variant="outline" disabled className="gap-2">
                <span className="h-2 w-2 rounded-full bg-orange-500" />
                {t("llm.formulation.fixIssues", { count: errorCount })}
              </Button>
            ) : (
              <>
                {onSolve && (
                  // Wrap disabled buttons in <span> so Radix Tooltip still
                  // fires on hover — disabled buttons don't dispatch pointer
                  // events, which would make the parametric reason invisible.
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span>
                        <Button
                          variant="default"
                          className="gap-2"
                          disabled={streaming || solving || parametric}
                          onClick={onSolve}
                        >
                          <Play className="h-4 w-4" />
                          {solving ? t("llm.formulation.solving") : t("llm.formulation.solveNow")}
                        </Button>
                      </span>
                    </TooltipTrigger>
                    {parametric && (
                      <TooltipContent className="max-w-xs text-center">
                        {t("aiAssistant.parametricError")}
                      </TooltipContent>
                    )}
                  </Tooltip>
                )}
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button
                        variant="outline"
                        className="gap-2"
                        disabled={streaming || parametric}
                        onClick={onOpenInBuilder}
                      >
                        <span className="h-2 w-2 rounded-full bg-green-500" />
                        {t("llm.formulation.openInBuilder")}
                      </Button>
                    </span>
                  </TooltipTrigger>
                  {parametric && (
                    <TooltipContent className="max-w-xs text-center">
                      {t("aiAssistant.parametricError")}
                    </TooltipContent>
                  )}
                </Tooltip>
              </>
            )}
          </div>
        </TooltipProvider>
      )}
    </div>
  );
}
