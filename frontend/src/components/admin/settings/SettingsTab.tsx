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
    LLM_THINKING_EFFORT: "Models",
    LLM_MAX_TOKENS: "Limits",
    LLM_MAX_RETRIES: "Limits",
    LLM_MAX_OUTPUT_TOKENS_LIMIT: "Limits",
    LLM_MONTHLY_BUDGET_EUR: "Cost",
    LLM_MODEL_PRICING_EUR_PER_MTOK: "Cost",
    LLM_RATE_LIMIT_PER_MINUTE: "Rate Limits",
    LLM_RATE_LIMIT_PER_DAY: "Rate Limits",
    LLM_CONVERSATION_TTL_HOURS: "Conversations",
  },
  email: {
    EMAIL_BACKEND: "General",
    EMAIL_FROM: "General",
    CONTACT_RECIPIENT: "General",
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
    JWT_ALGORITHM: "JWT Tokens",
  },
  // Without these the prefix fallback below produces "Instance Rate",
  // "Instance Max", "Home Announcement" — the key's spelling, not a heading.
  limits: {
    instance_rate_limit_per_minute: "Rate Limits",
    instance_rate_limit_per_day: "Rate Limits",
    instance_max_variables: "Capacity",
    instance_max_solve_time_seconds: "Capacity",
    instance_max_daily_solves: "Capacity",
    instance_max_cron_schedules: "Scheduling",
    instance_min_cron_interval_minutes: "Scheduling",
    instance_allowed_features: "Features",
  },
  system: {
    MAINTENANCE_MODE: "Maintenance",
    SOLVE_MAINTENANCE_MODE: "Maintenance",
    JAOT_DSL: "Feature Flags",
    HOME_ANNOUNCEMENT_ENABLED: "Announcement Banner",
    HOME_ANNOUNCEMENT_ROTATION_SECONDS: "Announcement Banner",
    HOME_ANNOUNCEMENT_TEXT_EN: "Announcement Banner",
    HOME_ANNOUNCEMENT_TEXT_ES: "Announcement Banner",
    HOME_ANNOUNCEMENT_TEXT_CA: "Announcement Banner",
    HOME_ANNOUNCEMENT_TEXT_FR: "Announcement Banner",
    HOME_ANNOUNCEMENT_TEXT_DE: "Announcement Banner",
    STORAGE_ACCOUNT_ID: "Object Storage",
    STORAGE_BUCKET: "Object Storage",
    STORAGE_CDN_URL: "Object Storage",
    DISCOURSE_URL: "Community",
  },
  solver: {
    SOLVER_DEFAULT_TIMEOUT: "Solving",
    SOLVER_POOL_SIZE: "Solving",
    hexaly_default_time_limit_seconds: "Solving",
    dsl_max_grounded_elements: "Solving",
    EXECUTION_REAPER_PENDING_MAX_SECONDS: "Stuck Executions",
    EXECUTION_REAPER_RUNNING_MAX_SECONDS: "Stuck Executions",
    SENSITIVITY_MAX_RESOLVES: "What-if Analysis",
    SENSITIVITY_TOP_CONSTRAINTS: "What-if Analysis",
    SENSITIVITY_TOP_DECISIONS: "What-if Analysis",
    SENSITIVITY_PER_SOLVE_MULTIPLIER: "What-if Analysis",
    SENSITIVITY_PER_SOLVE_CAP_SECONDS: "What-if Analysis",
    SENSITIVITY_TOTAL_BUDGET_SECONDS: "What-if Analysis",
    IIS_MAX_CONSTRAINTS: "Infeasibility",
    IIS_TIME_BUDGET_SECONDS: "Infeasibility",
  },
  rag: {
    RAG_ENABLED: "Retrieval",
    RAG_TOP_K: "Retrieval",
    RAG_MIN_SCORE: "Retrieval",
    RAG_MAX_TOKENS: "Retrieval",
    RAG_RERANKER_ENABLED: "Reranking",
    RAG_RERANKER_MODEL: "Reranking",
  },
  identifiers: {
    ID_PREFIX_ORGANIZATION: "ID Prefixes",
    ID_PREFIX_USER: "ID Prefixes",
    API_KEY_DEFAULT_NAME: "API Keys",
    API_KEY_DEFAULT_PREFIX: "API Keys",
    API_KEY_TEST_PREFIX: "API Keys",
  },
};

/** Threshold: categories with this many settings or fewer render flat (no accordion) */
const ACCORDION_THRESHOLD = 4;

function getGroupName(entry: RegistryEntry): string {
  // Check explicit mapping first — keyed by the entry's OWN category, since a
  // tab may render several of them.
  const categoryMap = SETTING_GROUPS[entry.category];
  if (categoryMap && categoryMap[entry.key]) {
    return categoryMap[entry.key];
  }

  // Fallback: derive group from key prefix (first segment before _)
  const parts = entry.key.split("_");
  if (parts.length >= 2) {
    return parts.slice(0, 2).join(" ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
  return entry.key;
}

interface GroupedSettings {
  name: string;
  entries: RegistryEntry[];
}

function groupEntries(entries: RegistryEntry[]): GroupedSettings[] {
  const groupMap = new Map<string, RegistryEntry[]>();

  for (const entry of entries) {
    const group = getGroupName(entry);
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
  /** Backend categories this tab renders, in order. */
  categories: readonly string[];
  categoryLabel: string;
  entries: RegistryEntry[];
  values: Record<string, SettingValue>;
  onRefresh: () => void;
  searchQuery?: string;
  /** Shown above the fields when the whole group deserves a caution note. */
  warning?: string;
}

export function SettingsTab({
  categories,
  categoryLabel,
  entries,
  values,
  onRefresh,
  searchQuery,
  warning,
}: SettingsTabProps) {
  const t = useTranslations("admin.settings");
  const [dirtyValues, setDirtyValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Entries for this tab's categories, in the order the tab declares them.
  // Secrets are excluded here: they have their own tab and a masked editor.
  const visibleEntries = useMemo(
    () =>
      categories.flatMap((category) =>
        entries.filter((e) => e.category === category && !e.is_secret)
      ),
    [entries, categories]
  );

  // Apply search filter if provided
  const filteredEntries = useMemo(() => {
    if (!searchQuery || searchQuery.trim() === "") return visibleEntries;
    const q = searchQuery.toLowerCase();
    return visibleEntries.filter(
      (e) =>
        e.label.toLowerCase().includes(q) ||
        e.description.toLowerCase().includes(q) ||
        e.key.toLowerCase().includes(q)
    );
  }, [visibleEntries, searchQuery]);

  // Group entries for accordion display
  const groups = useMemo(() => groupEntries(filteredEntries), [filteredEntries]);

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
        {warning && (
          <p className="text-sm text-muted-foreground border-l-2 border-[var(--health-warning,theme(colors.amber.500))] pl-3 py-1 mb-3">
            {warning}
          </p>
        )}
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
