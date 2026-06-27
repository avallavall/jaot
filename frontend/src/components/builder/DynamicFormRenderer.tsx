"use client";

// DynamicFormRenderer -- Generates forms from template input_fields
// schema. Replaces all custom per-template forms with a single
// universal component that handles any template.

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FormFieldRenderer, type FieldSchema } from "./FormFieldRenderer";
import { useTranslations } from "next-intl";

export interface DynamicFormRendererProps {
  /** Template input_fields schema */
  inputFields: FieldSchema[];
  /** Example input data for "Load Example" button */
  exampleInput: Record<string, unknown>;
  /** Optional scenario description shown alongside the form */
  scenarioDescription?: string;
  /** Called with form data on submit */
  onSubmit: (data: Record<string, unknown>) => Promise<void>;
  /** Whether a submit is in progress */
  isSubmitting?: boolean;
}

function buildEmptyValues(fields: FieldSchema[]): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.type === "array") {
      values[field.name] = [];
    } else if (field.type === "object") {
      values[field.name] = {};
    } else if (field.type === "boolean") {
      values[field.name] = false;
    } else {
      values[field.name] = undefined;
    }
  }
  return values;
}

type TranslateFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function validate(
  fields: FieldSchema[],
  values: Record<string, unknown>,
  t: TranslateFunc
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const val = values[field.name];
    if (field.required) {
      if (val === undefined || val === null || val === "") {
        errors[field.name] = t("templateForm.fieldRequired", { field: field.label ?? field.name });
        continue;
      }
      if (field.type === "array" && Array.isArray(val) && val.length === 0) {
        errors[field.name] = t("templateForm.atLeastOneItem");
        continue;
      }
    }
    if (
      (field.type === "number" || field.type === "integer") &&
      val !== undefined &&
      val !== null &&
      val !== ""
    ) {
      const num = Number(val);
      if (isNaN(num)) {
        errors[field.name] = t("templateForm.mustBeNumber");
      } else if (field.minimum != null && num < field.minimum) {
        errors[field.name] = t("templateForm.minimumValue", { min: field.minimum });
      } else if (field.maximum != null && num > field.maximum) {
        errors[field.name] = t("templateForm.maximumValue", { max: field.maximum });
      }
    }
  }
  return errors;
}

export function DynamicFormRenderer({
  inputFields,
  exampleInput,
  scenarioDescription,
  onSubmit,
  isSubmitting = false,
}: DynamicFormRendererProps) {
  const t = useTranslations("builder");
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    buildEmptyValues(inputFields)
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [exampleLoaded, setExampleLoaded] = useState(false);

  const updateField = useCallback((name: string, value: unknown) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    // Clear error on change (real-time validation)
    setErrors((prev) => {
      if (!prev[name]) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  }, []);

  const handleLoadExample = useCallback(() => {
    const loaded: Record<string, unknown> = {};
    for (const field of inputFields) {
      loaded[field.name] =
        exampleInput[field.name] !== undefined ? exampleInput[field.name] : undefined;
    }
    setValues(loaded);
    setErrors({});
    setExampleLoaded(true);
  }, [inputFields, exampleInput]);

  const handleClearSection = useCallback(
    (fieldName: string, field: FieldSchema) => {
      const empty = buildEmptyValues([field]);
      setValues((prev) => ({ ...prev, [fieldName]: empty[fieldName] }));
    },
    []
  );

  const handleClearAll = useCallback(() => {
    setValues(buildEmptyValues(inputFields));
    setErrors({});
    setExampleLoaded(false);
  }, [inputFields]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      // Validate
      const validationErrors = validate(inputFields, values, t);
      if (Object.keys(validationErrors).length > 0) {
        setErrors(validationErrors);
        return;
      }
      // Clean up undefined values
      const cleanData: Record<string, unknown> = {};
      for (const field of inputFields) {
        const val = values[field.name];
        if (val !== undefined) {
          cleanData[field.name] = val;
        }
      }
      await onSubmit(cleanData);
    },
    [inputFields, values, onSubmit, t]
  );

  // A model/template with no input fields has no form to render. Show a clear
  // message instead of an empty card with non-functional buttons (the model
  // likely carries a direct definition meant for the visual editor).
  if (inputFields.length === 0) {
    return (
      <div className="py-8 text-center" role="status">
        <p className="text-sm text-muted-foreground">{t("templateForm.noInputFields")}</p>
      </div>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
      {/* Scenario description (left side on desktop, collapsible on mobile) */}
      {scenarioDescription && (
        <div className="lg:sticky lg:top-8 lg:self-start">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("templateForm.scenario")}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground whitespace-pre-wrap leading-relaxed">
                {scenarioDescription}
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Form (right side) */}
      <div className={scenarioDescription ? "" : "lg:col-span-2"}>
        <form onSubmit={handleSubmit} className="space-y-6">
          <div className="flex items-center gap-2 flex-wrap">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleLoadExample}
              disabled={isSubmitting}
            >
              {exampleLoaded ? t("templateForm.reloadExample") : t("templateForm.loadExample")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleClearAll}
              disabled={isSubmitting}
            >
              {t("templateForm.clearAll")}
            </Button>
          </div>

          {inputFields.map((field) => (
            <div key={field.name} className="space-y-2">
              <div className="flex items-center justify-between">
                <div />
                {(field.type === "array" || field.type === "object") && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="text-xs h-6"
                    onClick={() => handleClearSection(field.name, field)}
                    disabled={isSubmitting}
                  >
                    {t("templateForm.clear")}
                  </Button>
                )}
              </div>
              <FormFieldRenderer
                field={field}
                value={values[field.name]}
                onChange={(v) => updateField(field.name, v)}
                error={errors[field.name]}
                idPrefix={`df-${field.name}`}
              />
            </div>
          ))}

          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? t("templateForm.solving") : t("templateForm.solve")}
          </Button>
        </form>
      </div>
    </div>
  );
}
