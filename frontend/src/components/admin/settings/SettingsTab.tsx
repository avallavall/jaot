"use client";

import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from "@/components/ui/accordion";
import { SettingField } from "./SettingField";
import { api } from "@/lib/api";
import type { RegistryEntry, SettingValue } from "@/lib/api";
import { useTranslations } from "next-intl";

/** Mapping of category -> setting key -> group name */
const SETTING_GROUPS: Record<string, Record<string, string>> = {
  llm: {
    LLM_DEFAULT_MODEL: "Models",
    LLM_ADVANCED_MODEL: "Models",
    LLM_MAX_TOKENS: "Limits",
    LLM_MAX_RETRIES: "Limits",
    LLM_MAX_OUTPUT_TOKENS_LIMIT: "Limits",
    LLM_RATE_LIMIT_PER_MINUTE: "Rate Limits",
    LLM_RATE_LIMIT_PER_DAY: "Rate Limits",
    LLM_CREDIT_COST_PER_MESSAGE: "Credits",
    LLM_CONVERSATION_TTL_HOURS: "Conversations",
  },
  email: {
    EMAIL_BACKEND: "General",
    EMAIL_FROM: "General",
    SMTP_HOST: "SMTP Server",
    SMTP_PORT: "SMTP Server",
    SMTP_USER: "SMTP Server",
    SMTP_PASSWORD: "SMTP Server",
    SMTP_TIMEOUT: "SMTP Server",
    SMTP_USE_TLS: "SMTP Server",
  },
  security: {
    REGISTRATION_ENABLED: "Registration",
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: "JWT Tokens",
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: "JWT Tokens",
    JWT_REFRESH_TOKEN_REMEMBER_DAYS: "JWT Tokens",
    API_KEY_DEFAULT_EXPIRY_DAYS: "API Keys",
    API_KEY_ACTIVE_BY_DEFAULT: "API Keys",
    RATE_LIMIT_WINDOW_SECONDS: "Rate Limits",
    RATE_LIMIT_DAILY_WINDOW_SECONDS: "Rate Limits",
  },
  marketplace: {
    marketplace_commission_rate: "Commission",
  },
};

/** Threshold: categories with this many settings or fewer render flat (no accordion) */
const ACCORDION_THRESHOLD = 4;

function getGroupName(category: string, key: string): string {
  // Check explicit mapping first
  const categoryMap = SETTING_GROUPS[category];
  if (categoryMap && categoryMap[key]) {
    return categoryMap[key];
  }

  // Marketplace: featured_placement_* -> "Featured Placements"
  if (category === "marketplace" && key.startsWith("featured_placement_")) {
    return "Featured Placements";
  }

  // Fallback: derive group from key prefix (first segment before _)
  const parts = key.split("_");
  if (parts.length >= 2) {
    return parts.slice(0, 2).join(" ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return key;
}

interface GroupedSettings {
  name: string;
  entries: RegistryEntry[];
}

function groupEntries(category: string, entries: RegistryEntry[]): GroupedSettings[] {
  const groupMap = new Map<string, RegistryEntry[]>();

  for (const entry of entries) {
    const group = getGroupName(category, entry.key);
    if (!groupMap.has(group)) {
      groupMap.set(group, []);
    }
    groupMap.get(group)!.push(entry);
  }

  // Preserve insertion order (which follows the original entries order)
  return Array.from(groupMap.entries()).map(([name, groupEntries]) => ({
    name,
    entries: groupEntries,
  }));
}

interface SettingsTabProps {
  category: string;
  categoryLabel: string;
  entries: RegistryEntry[];
  values: Record<string, SettingValue>;
  onRefresh: () => void;
  searchQuery?: string;
}

export function SettingsTab({
  category,
  categoryLabel,
  entries,
  values,
  onRefresh,
  searchQuery,
}: SettingsTabProps) {
  const t = useTranslations("admin.settings");
  const [dirtyValues, setDirtyValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Filter entries for this category, excluding secrets
  const categoryEntries = entries.filter((e) => e.category === category);
  const visibleEntries = categoryEntries.filter((e) => !e.is_secret);

  // Apply search filter if provided
  const filteredEntries = useMemo(() => {
    if (!searchQuery || searchQuery.trim() === "") return visibleEntries;
    const q = searchQuery.toLowerCase();
    return visibleEntries.filter(
      (e) =>
        e.label.toLowerCase().includes(q) || e.description.toLowerCase().includes(q)
    );
  }, [visibleEntries, searchQuery]);

  // Group entries for accordion display
  const groups = useMemo(
    () => groupEntries(category, filteredEntries),
    [category, filteredEntries]
  );

  const useAccordion = !searchQuery && filteredEntries.length > ACCORDION_THRESHOLD;

  const handleChange = (key: string, value: string) => {
    setDirtyValues((prev) => ({ ...prev, [key]: value }));
    // Clear field error on edit
    setFieldErrors((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setMessage(null);
  };

  const handleReset = async (key: string) => {
    try {
      await api.admin.resetSetting(key);
      // Clear from dirty values
      setDirtyValues((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      onRefresh();
    } catch {
      setMessage({
        type: "error",
        text: t("validationError", { error: "Reset failed" }),
      });
    }
  };

  const handleSave = async () => {
    if (Object.keys(dirtyValues).length === 0) {
      setMessage({ type: "error", text: t("noChanges") });
      return;
    }
    setSaving(true);
    setMessage(null);
    setFieldErrors({});
    try {
      const result = await api.admin.updateSettings(dirtyValues);
      if (Object.keys(result.errors).length > 0) {
        setFieldErrors(result.errors);
        setMessage({
          type: "error",
          text: t("validationError", {
            error: Object.values(result.errors).join(", "),
          }),
        });
      } else {
        setMessage({ type: "success", text: t("saved") });
        setDirtyValues({});
        onRefresh();
      }
    } catch {
      setMessage({
        type: "error",
        text: t("validationError", { error: "Save failed" }),
      });
    } finally {
      setSaving(false);
    }
  };

  const getCurrentValue = (key: string): string => {
    if (key in dirtyValues) return dirtyValues[key];
    return values[key]?.value ?? "";
  };

  const renderSettingField = (entry: RegistryEntry) => (
    <div key={entry.key}>
      <SettingField
        entry={entry}
        value={getCurrentValue(entry.key)}
        envDefault={values[entry.key]?.env_default ?? null}
        isModified={
          entry.key in dirtyValues
            ? dirtyValues[entry.key] !== (values[entry.key]?.value ?? "")
            : (values[entry.key]?.is_modified ?? false)
        }
        lastChangedBy={values[entry.key]?.last_changed_by ?? null}
        lastChangedAt={values[entry.key]?.last_changed_at ?? null}
        onChange={handleChange}
        onReset={handleReset}
        disabled={saving}
      />
      {fieldErrors[entry.key] && (
        <p className="text-xs text-destructive mt-1">{fieldErrors[entry.key]}</p>
      )}
    </div>
  );

  if (filteredEntries.length === 0) return null;

  return (
    <Card className="border-border">
      <CardHeader>
        <CardTitle className="text-lg font-serif">{categoryLabel}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {useAccordion ? (
          <Accordion
            type="multiple"
            defaultValue={groups.length > 0 ? [groups[0].name] : []}
          >
            {groups.map((group) => (
              <AccordionItem key={group.name} value={group.name}>
                <AccordionTrigger>
                  <span>
                    {group.name}{" "}
                    <span className="text-muted-foreground font-normal">
                      ({t("settingsCount", { count: group.entries.length })})
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-1">
                    {group.entries.map(renderSettingField)}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        ) : (
          filteredEntries.map(renderSettingField)
        )}

        <div className="flex items-center gap-4 pt-4">
          <Button
            onClick={handleSave}
            disabled={saving || Object.keys(dirtyValues).length === 0}
          >
            {saving ? t("saving") : t("saveChanges")}
          </Button>
          {message && (
            <p
              className={`text-sm ${
                message.type === "success" ? "text-green-600" : "text-destructive"
              }`}
            >
              {message.text}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
