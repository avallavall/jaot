"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import type { RegistryEntry } from "@/lib/api";
import { useTranslations } from "next-intl";

export interface SettingFieldProps {
  entry: RegistryEntry;
  value: string;
  envDefault: string | null;
  isModified: boolean;
  lastChangedBy: string | null;
  lastChangedAt: string | null;
  onChange: (key: string, value: string) => void;
  onReset: (key: string) => void;
  disabled?: boolean;
}

export function SettingField({
  entry,
  value,
  isModified,
  lastChangedBy,
  lastChangedAt,
  onChange,
  onReset,
  disabled = false,
}: SettingFieldProps) {
  const t = useTranslations("admin.settings");

  const renderInput = () => {
    // Secret entries: masked read-only
    if (entry.is_secret) {
      return (
        <Input
          value="****"
          disabled
          className="max-w-xs font-mono"
        />
      );
    }

    // Read-only entries
    if (entry.is_readonly) {
      return (
        <Input
          value={value}
          disabled
          className="max-w-xs"
        />
      );
    }

    switch (entry.setting_type) {
      case "bool":
        return (
          <Switch
            checked={value === "true"}
            onCheckedChange={(checked) =>
              onChange(entry.key, checked ? "true" : "false")
            }
            disabled={disabled}
          />
        );

      case "int":
      case "float":
        return (
          <div className="flex items-center gap-2 max-w-xs">
            <Input
              type="number"
              value={value}
              min={entry.min_value ?? undefined}
              max={entry.max_value ?? undefined}
              step={entry.setting_type === "float" ? "0.01" : "1"}
              onChange={(e) => onChange(entry.key, e.target.value)}
              disabled={disabled}
            />
            {entry.unit && (
              <span className="text-sm text-muted-foreground whitespace-nowrap">
                {entry.unit}
              </span>
            )}
          </div>
        );

      case "json":
        return (
          <Textarea
            value={value}
            onChange={(e) => onChange(entry.key, e.target.value)}
            disabled={disabled}
            rows={3}
            className="max-w-md font-mono text-sm"
          />
        );

      case "str":
      default:
        return (
          <Input
            type="text"
            value={value}
            onChange={(e) => onChange(entry.key, e.target.value)}
            disabled={disabled}
            className="max-w-md"
          />
        );
    }
  };

  return (
    <div className="space-y-1.5 py-3 border-b border-border last:border-0">
      <div className="flex items-center gap-2">
        <Label className="text-sm font-medium">
          {isModified && (
            <span className="inline-block w-2 h-2 rounded-full bg-primary mr-1.5" />
          )}
          {entry.label}
        </Label>
        {isModified && !entry.is_readonly && !entry.is_secret && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-1.5 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => onReset(entry.key)}
            title={t("resetToDefault")}
          >
            &#x21ba;
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">{entry.description}</p>
      <div className="pt-1">{renderInput()}</div>
      {lastChangedBy && lastChangedAt && (
        <p className="text-xs text-muted-foreground/70 italic">
          {t("lastChanged", {
            date: new Intl.DateTimeFormat(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            }).format(new Date(lastChangedAt)),
            user: lastChangedBy,
          })}
        </p>
      )}
    </div>
  );
}
