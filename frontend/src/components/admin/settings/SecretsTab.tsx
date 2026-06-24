"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import type { RegistryEntry, SettingValue } from "@/lib/api";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Pencil } from "lucide-react";

interface SecretsTabProps {
  entries: RegistryEntry[];
  values: Record<string, SettingValue>;
}

export function SecretsTab({ entries, values }: SecretsTabProps) {
  const t = useTranslations("admin.settings");

  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [localValues, setLocalValues] = useState(values);

  useEffect(() => {
    setLocalValues(values);
  }, [values]);

  const secretEntries = entries.filter((e) => e.is_secret);

  if (secretEntries.length === 0) return null;

  const grouped: Record<string, RegistryEntry[]> = {};
  for (const entry of secretEntries) {
    if (!grouped[entry.category]) grouped[entry.category] = [];
    grouped[entry.category].push(entry);
  }

  const getStatus = (key: string): { configured: boolean; source: string } => {
    const val = localValues[key];
    if (!val) return { configured: false, source: "none" };
    const source = val.source ?? "none";
    const configured = val.value === "****" || source === "db" || source === "env";
    return { configured, source };
  };

  const handleEdit = (key: string) => {
    setEditingKey(key);
    setEditValue("");
  };

  const handleSave = async () => {
    if (!editingKey || !editValue.trim()) return;

    setIsSaving(true);
    try {
      await api.admin.updateSettings({ [editingKey]: editValue.trim() });
      setLocalValues({
        ...localValues,
        [editingKey]: {
          ...localValues[editingKey],
          value: "****",
          source: "db",
        },
      });
      toast.success(t("secrets.updated"));
      setEditingKey(null);
      setEditValue("");
    } catch {
      toast.error(t("secrets.updateFailed"));
    } finally {
      setIsSaving(false);
    }
  };

  const editingEntry = editingKey
    ? secretEntries.find((e) => e.key === editingKey)
    : null;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-serif">{t("secrets.title")}</h3>
        <p className="text-sm text-muted-foreground">{t("secrets.description")}</p>
      </div>

      {Object.entries(grouped).map(([category, secrets]) => (
        <Card key={category} className="border-border">
          <CardHeader>
            <CardTitle className="text-base font-medium capitalize">{category}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {secrets.map((entry) => {
              const { configured, source } = getStatus(entry.key);
              return (
                <div
                  key={entry.key}
                  className="flex items-center justify-between py-2 border-b border-border last:border-0"
                >
                  <div>
                    <p className="font-medium text-sm">{entry.label}</p>
                    <p className="text-xs text-muted-foreground">{entry.description}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={configured ? "default" : "secondary"}
                      className={
                        configured
                          ? "bg-[var(--health-valid)] hover:bg-[var(--health-valid)]/90 text-white"
                          : ""
                      }
                    >
                      {configured
                        ? source === "env"
                          ? t("configuredEnv")
                          : t("configured")
                        : t("notConfigured")}
                    </Badge>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => handleEdit(entry.key)}
                      aria-label={t("secrets.edit")}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      ))}

      <Dialog open={editingKey !== null} onOpenChange={(open) => { if (!open) setEditingKey(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editingEntry?.label}</DialogTitle>
            <DialogDescription>{editingEntry?.description}</DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Input
              type="password"
              placeholder={t("secrets.enterValue")}
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingKey(null)}>
              {t("secrets.cancel")}
            </Button>
            <Button onClick={handleSave} disabled={isSaving || !editValue.trim()}>
              {isSaving ? t("secrets.saving") : t("secrets.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
