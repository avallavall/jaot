"use client";

// TemplateFormPage -- Renders a dynamic form for any template
// by fetching its input_fields schema from the API and using
// the DynamicFormRenderer component.

import { useState, useCallback, useEffect } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import type { SolveResult } from "@/lib/types";
import { SolveResultsDrawer } from "./SolveResultsDrawer";
import { DynamicFormRenderer } from "./DynamicFormRenderer";
import type { FieldSchema } from "./FormFieldRenderer";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "next-intl";

interface TemplateDetail {
  id: string;
  name: string;
  display_name: string;
  description: string;
  scenario_description?: string;
  category: string;
  input_fields: FieldSchema[];
  example_input: Record<string, unknown>;
}

interface TemplateFormPageProps {
  templateId: string;
  templateName?: string;
}

export function TemplateFormPage({ templateId, templateName }: TemplateFormPageProps) {
  const t = useTranslations("builder");
  const [template, setTemplate] = useState<TemplateDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [solveResult, setSolveResult] = useState<SolveResult | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Fetch template details
  useEffect(() => {
    let cancelled = false;

    async function fetchTemplate() {
      setLoading(true);
      setFetchError(null);
      try {
        const data = await api.getTemplate(templateId);
        if (!cancelled) {
          setTemplate(data as unknown as TemplateDetail);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setFetchError(getErrorMessage(err, t("templateForm.failedToLoad")));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchTemplate();
    return () => {
      cancelled = true;
    };
  }, [templateId, t]);

  const handleSubmit = useCallback(
    async (formData: Record<string, unknown>) => {
      setIsSubmitting(true);
      try {
        const result = await api.solveTemplate(templateId, formData);
        setSolveResult(result);
        setDrawerOpen(true);
      } catch (err: unknown) {
        const status = getErrorStatus(err);
        if (status === 402) {
          toast.error(t("templateForm.insufficientCredits"));
        } else if (status === 422) {
          toast.error(t("templateForm.invalidInput", { detail: getErrorMessage(err, "") }));
        } else {
          toast.error(getErrorMessage(err, t("templateForm.solveFailed")));
        }
      } finally {
        setIsSubmitting(false);
      }
    },
    [templateId, t]
  );

  const displayName = templateName ?? template?.display_name ?? template?.name ?? templateId;

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto py-8 px-4 space-y-6">
        <div className="space-y-2">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-4 w-96" />
        </div>
        <div className="space-y-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      </div>
    );
  }

  if (fetchError || !template) {
    return (
      <div className="max-w-2xl mx-auto py-8 px-4">
        <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-6 text-center">
          <h2 className="text-lg font-semibold text-destructive mb-2">
            {t("templateForm.failedToLoad")}
          </h2>
          <p className="text-sm text-muted-foreground">
            {fetchError ?? t("templateForm.templateNotFound")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{displayName}</h1>
        {template.description && (
          <p className="text-muted-foreground mt-1">{template.description}</p>
        )}
      </div>

      <div className="bg-card border rounded-lg p-6">
        <DynamicFormRenderer
          inputFields={template.input_fields}
          exampleInput={template.example_input}
          scenarioDescription={template.scenario_description}
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
          getExportProblem={(values) => api.previewTemplate(templateId, values)}
          exportFilenameBase={displayName}
        />
      </div>

      <SolveResultsDrawer
        result={solveResult}
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
