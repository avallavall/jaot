"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import type { OverrideField } from "@/lib/types";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Trash2, Plus, ArrowRight } from "lucide-react";

const FIELD_TYPES = ["string", "number", "integer", "boolean", "array", "object"] as const;

interface OverrideSchemaEditorProps {
  value: OverrideField[];
  onChange: (fields: OverrideField[]) => void;
}

export function OverrideSchemaEditor({ value, onChange }: OverrideSchemaEditorProps) {
  const t = useTranslations("triggers.overrides");
  const [jsonText, setJsonText] = useState(() => JSON.stringify(value, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("form");

  const handleTabChange = (tab: string) => {
    if (tab === "json" && activeTab !== "json") {
      // Sync canonical state to JSON text
      setJsonText(JSON.stringify(value, null, 2));
      setJsonError(null);
    }
    setActiveTab(tab);
  };

  // Form mode: add a new empty field
  const addField = () => {
    const newField: OverrideField = {
      name: "",
      type: "string",
      model_field_path: "",
      required: false,
    };
    onChange([...value, newField]);
  };

  // Form mode: remove a field by index
  const removeField = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  // Form mode: update a specific field property
  const updateField = (index: number, patch: Partial<OverrideField>) => {
    onChange(value.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  };

  // JSON mode: parse and sync on blur
  const handleJsonBlur = () => {
    try {
      const parsed = JSON.parse(jsonText);
      if (!Array.isArray(parsed)) {
        setJsonError(t("jsonArrayError"));
        return;
      }
      setJsonError(null);
      onChange(parsed as OverrideField[]);
    } catch {
      setJsonError(t("jsonSyntaxError"));
    }
  };

  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="bg-muted/50 px-4 py-2 border-b">
        <p className="text-sm font-medium">{t("title")}</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {t("description")}
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={handleTabChange} className="p-4">
        <TabsList className="mb-4">
          <TabsTrigger value="form">{t("formTab")}</TabsTrigger>
          <TabsTrigger value="json">{t("jsonTab")}</TabsTrigger>
          <TabsTrigger value="visual">{t("visualTab")}</TabsTrigger>
        </TabsList>

        <TabsContent value="form">
          <div className="space-y-3">
            {value.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">
                {t("noParameters")}
              </p>
            )}
            {value.map((field, index) => (
              <div key={index} className="border rounded-lg p-3 space-y-2 bg-background">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">{t("parameter", { index: index + 1 })}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => removeField(index)}
                    className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">{t("nameLabel")}</Label>
                    <Input
                      value={field.name}
                      onChange={(e) => updateField(index, { name: e.target.value })}
                      placeholder={t("namePlaceholder")}
                      className="h-8 text-sm"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">{t("typeLabel")}</Label>
                    <Select
                      value={field.type}
                      onValueChange={(v) => updateField(index, { type: v as OverrideField["type"] })}
                    >
                      <SelectTrigger className="h-8 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {FIELD_TYPES.map((ft) => (
                          <SelectItem key={ft} value={ft}>{ft}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1 col-span-2">
                    <Label className="text-xs">{t("fieldPathLabel")}</Label>
                    <Input
                      value={field.model_field_path}
                      onChange={(e) => updateField(index, { model_field_path: e.target.value })}
                      placeholder={t("fieldPathPlaceholder")}
                      className="h-8 text-sm"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">{t("defaultLabel")}</Label>
                    <Input
                      value={field.default !== undefined ? String(field.default) : ""}
                      onChange={(e) => updateField(index, { default: e.target.value || undefined })}
                      placeholder={t("defaultPlaceholder")}
                      className="h-8 text-sm"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">{t("descriptionLabel")}</Label>
                    <Input
                      value={field.description ?? ""}
                      onChange={(e) => updateField(index, { description: e.target.value || undefined })}
                      placeholder={t("descriptionPlaceholder")}
                      className="h-8 text-sm"
                    />
                  </div>
                  <div className="flex items-center gap-2 col-span-2">
                    <input
                      type="checkbox"
                      id={`required-${index}`}
                      checked={field.required ?? false}
                      onChange={(e) => updateField(index, { required: e.target.checked })}
                      className="h-4 w-4"
                    />
                    <Label htmlFor={`required-${index}`} className="text-xs cursor-pointer">
                      {t("requiredField")}
                    </Label>
                  </div>
                </div>
              </div>
            ))}
            <Button type="button" variant="outline" size="sm" onClick={addField} className="w-full">
              <Plus className="w-4 h-4 mr-2" />
              {t("addParameter")}
            </Button>
          </div>
        </TabsContent>

        <TabsContent value="json">
          <div className="space-y-2">
            <Textarea
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              onBlur={handleJsonBlur}
              rows={12}
              className="font-mono text-sm"
              placeholder='[{"name": "capacity", "type": "number", "model_field_path": "variables.capacity.upper_bound"}]'
            />
            {jsonError && (
              <p className="text-sm text-destructive">{jsonError}</p>
            )}
            <p className="text-xs text-muted-foreground">
              {t("jsonHelp")}
            </p>
          </div>
        </TabsContent>

        <TabsContent value="visual">
          {value.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              {t("noParametersVisual")}
            </p>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground mb-3">
                {t("visualHelp")}
              </p>
              {value.map((field, index) => (
                <div key={index} className="flex items-center gap-3 p-3 border rounded-lg bg-muted/30 text-sm">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{field.name || t("unnamed")}</div>
                    <div className="text-xs text-muted-foreground">
                      {field.type}{field.required ? " \u00b7 required" : ""}
                      {field.description ? ` \u00b7 ${field.description}` : ""}
                    </div>
                  </div>
                  <ArrowRight className="w-4 h-4 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-xs truncate text-primary">
                      {field.model_field_path || t("noPath")}
                    </div>
                    {field.default !== undefined && (
                      <div className="text-xs text-muted-foreground">
                        {t("defaultValue", { value: String(field.default) })}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
