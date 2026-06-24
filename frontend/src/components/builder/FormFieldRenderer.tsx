"use client";

// FormFieldRenderer -- Renders a single form field based on
// the input_fields schema from plugin templates

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTranslations } from "next-intl";

export interface FieldSchema {
  name: string;
  label?: string;
  type: "string" | "number" | "integer" | "boolean" | "array" | "object";
  description?: string;
  required?: boolean;
  minimum?: number;
  maximum?: number;
  default?: unknown;
  enum?: string[];
  items?: {
    type: string;
    properties?: Record<string, FieldSchema>;
  };
}

interface FormFieldRendererProps {
  field: FieldSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  error?: string;
  /** Unique prefix for field IDs */
  idPrefix?: string;
}

function fieldId(prefix: string | undefined, name: string): string {
  return prefix ? `${prefix}-${name}` : name;
}

function humanLabel(field: FieldSchema): string {
  return field.label ?? field.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function FormFieldRenderer({
  field,
  value,
  onChange,
  error,
  idPrefix,
}: FormFieldRendererProps) {
  const t = useTranslations("builder");
  const id = fieldId(idPrefix, field.name);
  const label = humanLabel(field);

  if (field.type === "string" && field.enum && field.enum.length > 0) {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={id}>
          {label}
          {field.required && <span className="text-destructive ml-0.5">*</span>}
        </Label>
        {field.description && (
          <p className="text-xs text-muted-foreground">{field.description}</p>
        )}
        <Select
          value={typeof value === "string" ? value : ""}
          onValueChange={(v) => onChange(v)}
        >
          <SelectTrigger id={id} aria-describedby={error ? `${id}-error` : undefined}>
            <SelectValue placeholder={`Select ${label.toLowerCase()}`} />
          </SelectTrigger>
          <SelectContent>
            {field.enum.map((opt) => (
              <SelectItem key={opt} value={opt}>
                {opt.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {error && (
          <p id={`${id}-error`} className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  if (field.type === "string") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={id}>
          {label}
          {field.required && <span className="text-destructive ml-0.5">*</span>}
        </Label>
        {field.description && (
          <p className="text-xs text-muted-foreground">{field.description}</p>
        )}
        <Input
          id={id}
          type="text"
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={error ? `${id}-error` : undefined}
          aria-invalid={!!error}
        />
        {error && (
          <p id={`${id}-error`} className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  if (field.type === "number" || field.type === "integer") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={id}>
          {label}
          {field.required && <span className="text-destructive ml-0.5">*</span>}
        </Label>
        {field.description && (
          <p className="text-xs text-muted-foreground">{field.description}</p>
        )}
        <Input
          id={id}
          type="number"
          step={field.type === "integer" ? "1" : "any"}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          value={value === undefined || value === null || value === "" ? "" : String(value)}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange(undefined);
              return;
            }
            const num = field.type === "integer" ? parseInt(raw, 10) : parseFloat(raw);
            onChange(isNaN(num) ? undefined : num);
          }}
          aria-describedby={error ? `${id}-error` : undefined}
          aria-invalid={!!error}
        />
        {error && (
          <p id={`${id}-error`} className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  if (field.type === "boolean") {
    return (
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <input
            id={id}
            type="checkbox"
            checked={!!value}
            onChange={(e) => onChange(e.target.checked)}
            className="h-4 w-4 rounded border-input text-primary focus:ring-ring"
            aria-describedby={error ? `${id}-error` : field.description ? `${id}-desc` : undefined}
            aria-invalid={!!error}
          />
          <Label htmlFor={id} className="mb-0">
            {label}
            {field.required && <span className="text-destructive ml-0.5">*</span>}
          </Label>
        </div>
        {field.description && (
          <p id={`${id}-desc`} className="text-xs text-muted-foreground ml-6">
            {field.description}
          </p>
        )}
        {error && (
          <p id={`${id}-error`} className="text-xs text-destructive ml-6" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  if (field.type === "array" && field.items?.type === "object" && field.items.properties) {
    const rows = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
    const props = field.items.properties;
    const propKeys = Object.keys(props);

    function makeEmptyRow(): Record<string, unknown> {
      const row: Record<string, unknown> = {};
      for (const [key, schema] of Object.entries(props)) {
        if (schema.default !== undefined) {
          row[key] = schema.default;
        } else if (schema.type === "number" || schema.type === "integer") {
          row[key] = 0;
        } else if (schema.type === "boolean") {
          row[key] = false;
        } else {
          row[key] = "";
        }
      }
      return row;
    }

    function updateRow(index: number, key: string, val: unknown) {
      const updated = [...rows];
      updated[index] = { ...updated[index], [key]: val };
      onChange(updated);
    }

    function addRow() {
      onChange([...rows, makeEmptyRow()]);
    }

    function removeRow(index: number) {
      onChange(rows.filter((_, i) => i !== index));
    }

    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>
            {label}
            {field.required && <span className="text-destructive ml-0.5">*</span>}
          </Label>
          <Button type="button" variant="outline" size="sm" onClick={addRow}>
            {t("templateForm.addRow")}
          </Button>
        </div>
        {field.description && (
          <p className="text-xs text-muted-foreground">{field.description}</p>
        )}
        {rows.length > 0 && (
          <div className="space-y-2">
            <div
              className="grid gap-2 text-xs font-medium text-muted-foreground"
              style={{ gridTemplateColumns: `repeat(${propKeys.length}, 1fr) 2rem` }}
            >
              {propKeys.map((key) => (
                <span key={key}>
                  {props[key].label ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </span>
              ))}
              <span />
            </div>
            {rows.map((row, rowIndex) => (
              <div
                key={rowIndex}
                className="grid gap-2 items-center"
                style={{ gridTemplateColumns: `repeat(${propKeys.length}, 1fr) 2rem` }}
              >
                {propKeys.map((key) => {
                  const propSchema = props[key];
                  if (propSchema.type === "number" || propSchema.type === "integer") {
                    return (
                      <Input
                        key={key}
                        type="number"
                        step={propSchema.type === "integer" ? "1" : "any"}
                        value={row[key] === undefined || row[key] === null ? "" : String(row[key])}
                        onChange={(e) => {
                          const raw = e.target.value;
                          if (raw === "") { updateRow(rowIndex, key, undefined); return; }
                          const num = propSchema.type === "integer" ? parseInt(raw, 10) : parseFloat(raw);
                          updateRow(rowIndex, key, isNaN(num) ? undefined : num);
                        }}
                      />
                    );
                  }
                  if (propSchema.type === "boolean") {
                    return (
                      <input
                        key={key}
                        type="checkbox"
                        checked={!!row[key]}
                        onChange={(e) => updateRow(rowIndex, key, e.target.checked)}
                        className="h-4 w-4 rounded border-input"
                      />
                    );
                  }
                  // Default: string input (serialize objects/arrays as JSON)
                  const cellValue = row[key];
                  const displayValue =
                    cellValue == null ? "" :
                    typeof cellValue === "string" ? cellValue :
                    typeof cellValue === "object" ? JSON.stringify(cellValue) :
                    String(cellValue);
                  return (
                    <Input
                      key={key}
                      type="text"
                      value={displayValue}
                      onChange={(e) => {
                        const raw = e.target.value;
                        // Try to parse back as JSON for object/array fields
                        try {
                          const parsed = JSON.parse(raw);
                          if (typeof parsed === "object") {
                            updateRow(rowIndex, key, parsed);
                            return;
                          }
                        } catch {
                          // Not valid JSON — store as string
                        }
                        updateRow(rowIndex, key, raw);
                      }}
                    />
                  );
                })}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => removeRow(rowIndex)}
                  className="h-8 w-8 p-0 text-destructive"
                >
                  x
                </Button>
              </div>
            ))}
          </div>
        )}
        {rows.length === 0 && (
          <p className="text-sm text-muted-foreground italic py-2">
            {t("templateForm.noRows")}
          </p>
        )}
        {error && (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  if (field.type === "array") {
    const items = Array.isArray(value) ? (value as unknown[]) : [];
    const itemType = field.items?.type ?? "string";

    function addItem() {
      const empty = itemType === "number" || itemType === "integer" ? 0 : "";
      onChange([...items, empty]);
    }

    function updateItem(index: number, val: unknown) {
      const updated = [...items];
      updated[index] = val;
      onChange(updated);
    }

    function removeItem(index: number) {
      onChange(items.filter((_, i) => i !== index));
    }

    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>
            {label}
            {field.required && <span className="text-destructive ml-0.5">*</span>}
          </Label>
          <Button type="button" variant="outline" size="sm" onClick={addItem}>
            {t("templateForm.addItem")}
          </Button>
        </div>
        {field.description && (
          <p className="text-xs text-muted-foreground">{field.description}</p>
        )}
        {items.map((item, i) => (
          <div key={i} className="flex gap-2 items-center">
            <Input
              type={itemType === "number" || itemType === "integer" ? "number" : "text"}
              step={itemType === "integer" ? "1" : "any"}
              value={item === undefined || item === null ? "" : String(item)}
              onChange={(e) => {
                if (itemType === "number" || itemType === "integer") {
                  const raw = e.target.value;
                  if (raw === "") { updateItem(i, undefined); return; }
                  const num = itemType === "integer" ? parseInt(raw, 10) : parseFloat(raw);
                  updateItem(i, isNaN(num) ? undefined : num);
                } else {
                  updateItem(i, e.target.value);
                }
              }}
              className="flex-1"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => removeItem(i)}
              className="h-8 w-8 p-0 text-destructive"
            >
              x
            </Button>
          </div>
        ))}
        {items.length === 0 && (
          <p className="text-sm text-muted-foreground italic py-2">
            {t("templateForm.noItems")}
          </p>
        )}
        {error && (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  if (field.type === "object" && field.items?.properties) {
    const obj = (typeof value === "object" && value !== null ? value : {}) as Record<string, unknown>;
    const props = field.items.properties;

    function updateField(key: string, val: unknown) {
      onChange({ ...obj, [key]: val });
    }

    return (
      <div className="space-y-3 border rounded-md p-4">
        <Label>
          {label}
          {field.required && <span className="text-destructive ml-0.5">*</span>}
        </Label>
        {field.description && (
          <p className="text-xs text-muted-foreground">{field.description}</p>
        )}
        {Object.entries(props).map(([key, propSchema]) => (
          <FormFieldRenderer
            key={key}
            field={{ ...propSchema, name: key }}
            value={obj[key]}
            onChange={(v) => updateField(key, v)}
            idPrefix={`${id}-${key}`}
          />
        ))}
        {error && (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label}
        {field.required && <span className="text-destructive ml-0.5">*</span>}
      </Label>
      {field.description && (
        <p className="text-xs text-muted-foreground">{field.description}</p>
      )}
      <textarea
        id={id}
        className="w-full h-24 font-mono text-sm rounded-md border border-input bg-background px-3 py-2 resize-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        value={typeof value === "string" ? value : JSON.stringify(value ?? "", null, 2)}
        onChange={(e) => {
          try {
            onChange(JSON.parse(e.target.value));
          } catch {
            onChange(e.target.value);
          }
        }}
        aria-describedby={error ? `${id}-error` : undefined}
        aria-invalid={!!error}
      />
      {error && (
        <p id={`${id}-error`} className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
