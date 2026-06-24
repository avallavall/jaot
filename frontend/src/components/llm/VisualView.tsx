"use client";

import { AlertTriangle } from "lucide-react";
import type { Formulation, ValidationError } from "@/lib/llm-types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ValidationMarkers } from "./ValidationMarkers";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

interface VisualViewProps {
  formulation: Formulation;
  validationErrors: ValidationError[];
  /** True when the formulation uses parametric notation that the visual
   *  cards cannot represent. When set, the view shows an explanatory notice
   *  instead of silently empty tables. */
  parametric?: boolean;
}

function hasError(errors: ValidationError[], field: string, index: number | null): boolean {
  return errors.some((e) => e.field === field && e.index === index);
}

function getErrorsForItem(
  errors: ValidationError[],
  field: string,
  index: number | null
): ValidationError[] {
  return errors.filter((e) => e.field === field && e.index === index);
}

/**
 * Structured cards/table view of a formulation.
 * Shows variables as a table, constraints and objective as cards.
 */
export function VisualView({ formulation, validationErrors, parametric = false }: VisualViewProps) {
  const t = useTranslations("builder");
  return (
    <div className="space-y-6">
      {/* Without this notice, parametric formulations render as empty
          Variables(0)/Constraints(0) tables with no explanation. */}
      {parametric && (
        <Alert className="border-orange-500 bg-orange-50 dark:bg-orange-950/30">
          <AlertTriangle className="h-4 w-4 text-orange-600" />
          <AlertDescription className="text-orange-700 dark:text-orange-300">
            {t("aiAssistant.parametricError")}
          </AlertDescription>
        </Alert>
      )}

      {formulation.summary && (
        <p className="text-sm text-muted-foreground leading-relaxed">
          {formulation.summary}
        </p>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-semibold">{t("llm.formulation.variables")}</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {formulation.variables.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("llm.formulation.noVariables")}</p>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[150px]">{t("llm.formulation.variableColumns.name")}</TableHead>
                    <TableHead className="w-[100px]">{t("llm.formulation.variableColumns.type")}</TableHead>
                    <TableHead className="w-[100px]">{t("llm.formulation.variableColumns.lower")}</TableHead>
                    <TableHead className="w-[100px]">{t("llm.formulation.variableColumns.upper")}</TableHead>
                    <TableHead>{t("llm.formulation.variableColumns.description")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {formulation.variables.map((v, i) => (
                    <TableRow
                      key={i}
                      className={cn(
                        hasError(validationErrors, "variable", i) &&
                          "border-l-2 border-l-destructive bg-destructive/5"
                      )}
                    >
                      <TableCell className="font-mono text-sm font-medium">
                        {v.name}
                        <ValidationMarkers
                          errors={validationErrors}
                          field="variable"
                          index={i}
                        />
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-xs">
                          {v.type}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-sm">
                        {v.lower_bound !== null ? v.lower_bound : "-inf"}
                      </TableCell>
                      <TableCell className="font-mono text-sm">
                        {v.upper_bound !== null ? v.upper_bound : "+inf"}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {v.description}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-semibold">
            {t("llm.formulation.constraints")} ({formulation.constraints.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {formulation.constraints.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("llm.formulation.noConstraints")}</p>
          ) : (
            <div className="space-y-3">
              {formulation.constraints.map((c, i) => {
                const itemErrors = getErrorsForItem(validationErrors, "constraint", i);
                return (
                  <div
                    key={i}
                    className={cn(
                      "rounded-lg border p-4",
                      itemErrors.length > 0 && "border-l-2 border-l-destructive bg-destructive/5"
                    )}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-semibold">{c.name}</span>
                      <ValidationMarkers
                        errors={validationErrors}
                        field="constraint"
                        index={i}
                      />
                    </div>
                    <code className="block rounded bg-muted px-3 py-2 text-sm font-mono">
                      {c.expression}
                    </code>
                    {c.description && (
                      <p className="mt-2 text-sm text-muted-foreground">{c.description}</p>
                    )}
                    {itemErrors.map((err, errIdx) => (
                      <div
                        key={errIdx}
                        className="mt-2 rounded border border-destructive/30 bg-destructive/10 p-2 text-sm"
                      >
                        <p className="text-destructive font-medium">{err.message}</p>
                        {err.suggestion && (
                          <p className="mt-1 text-muted-foreground">
                            <span className="font-medium">{t("llm.formulation.fix")}</span> {err.suggestion}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-semibold">{t("llm.formulation.objective")}</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <div
            className={cn(
              "rounded-lg border p-4",
              hasError(validationErrors, "objective", null) &&
                "border-l-2 border-l-destructive bg-destructive/5"
            )}
          >
            <div className="flex items-center gap-2 mb-1">
              <Badge
                variant={formulation.objective.sense === "minimize" ? "default" : "secondary"}
              >
                {formulation.objective.sense === "minimize" ? t("llm.formulation.minimize") : t("llm.formulation.maximize")}
              </Badge>
              <ValidationMarkers
                errors={validationErrors}
                field="objective"
                index={null}
              />
            </div>
            <code className="block rounded bg-muted px-3 py-2 text-sm font-mono mt-2">
              {formulation.objective.expression}
            </code>
            {formulation.objective.description && (
              <p className="mt-2 text-sm text-muted-foreground">
                {formulation.objective.description}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
