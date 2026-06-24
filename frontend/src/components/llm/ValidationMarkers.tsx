"use client";

import type { ValidationError } from "@/lib/llm-types";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTranslations } from "next-intl";

interface ValidationMarkersProps {
  errors: ValidationError[];
  field: string;
  index: number | null;
}

/**
 * Inline validation markers for formulation items.
 * Shows a red badge with error count and tooltip with details.
 */
export function ValidationMarkers({ errors, field, index }: ValidationMarkersProps) {
  const t = useTranslations("builder");
  const relevantErrors = errors.filter(
    (e) => e.field === field && e.index === index
  );

  if (relevantErrors.length === 0) return null;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="destructive" className="ml-2 cursor-help text-xs">
            {t("llm.validation.errors", { count: relevantErrors.length })}
          </Badge>
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-sm">
          <div className="space-y-2">
            {relevantErrors.map((err, i) => (
              <div key={i} className="text-sm">
                <p className="font-medium text-destructive">{err.message}</p>
                {err.suggestion && (
                  <p className="mt-1 text-muted-foreground">
                    <span className="font-medium">{t("llm.formulation.fix")}</span> {err.suggestion}
                  </p>
                )}
              </div>
            ))}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
