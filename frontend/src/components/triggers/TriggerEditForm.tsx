"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import { translateApiError } from "@/lib/errors";
import type { OverrideField, SolveTrigger } from "@/lib/types";
import { useSolvers } from "@/hooks/useSolvers";
import { solverDisplayName } from "@/lib/solver-display";
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
import { Loader2 } from "lucide-react";
import { defaultToText, parseDefault } from "./override-defaults";

/** Radix Select cannot hold an empty value, so "the model's own solver" gets a name. */
const MODEL_SOLVER = "__model__";

interface TriggerEditFormProps {
  trigger: SolveTrigger;
  workspaceId?: string;
  onSaved: (updated: SolveTrigger) => void;
  onCancel: () => void;
}

/**
 * Edit a trigger's name, its solver and the defaults of its override fields.
 *
 * The pinned model and version are not here: the server does not let them
 * change, because a trigger is a promise to run that exact version. The fields
 * of the override schema are not added or removed here either. Only their
 * defaults, which is what a fire with an empty body uses.
 */
export function TriggerEditForm({ trigger, workspaceId, onSaved, onCancel }: TriggerEditFormProps) {
  const t = useTranslations("triggers.detail");
  const tError = useTranslations("errors.codes");
  const tAuto = useTranslations("solvers.auto");
  const { availableSolvers, solversLoading } = useSolvers();

  const fields: OverrideField[] = trigger.override_schema ?? [];
  const [name, setName] = useState(trigger.name);
  const [solver, setSolver] = useState(trigger.solver_name ?? MODEL_SOLVER);
  const [defaults, setDefaults] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, defaultToText(f.default)])),
  );
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // The saved solver stays selectable even if this server no longer lists it.
  const solverNames = Array.from(
    new Set([
      "auto",
      ...availableSolvers.filter((s) => s.available).map((s) => s.name),
      ...(trigger.solver_name ? [trigger.solver_name] : []),
    ]),
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = t("nameRequired");
    const schema = fields.map((field) => {
      const parsed = parseDefault(field.type, defaults[field.name] ?? "");
      if (!parsed.ok) {
        found[field.name] = t("invalidDefault", { type: field.type });
        return field;
      }
      return { ...field, default: parsed.value };
    });
    setProblems(found);
    if (Object.keys(found).length > 0) return;

    setSaving(true);
    try {
      const updated = await api.triggers.update(
        trigger.id,
        {
          name: name.trim(),
          solver_name: solver === MODEL_SOLVER ? null : solver,
          // An open schema (null) has no fields to give defaults to.
          ...(trigger.override_schema ? { override_schema: schema } : {}),
        },
        workspaceId,
      );
      toast.success(t("saved"));
      onSaved(updated);
    } catch (err) {
      toast.error(translateApiError(err, tError, t("saveError")));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="border rounded-lg overflow-hidden mb-6"
      data-testid="trigger-edit-form"
    >
      <div className="bg-muted/50 px-4 py-3 border-b">
        <h2 className="font-semibold text-sm">{t("editTitle")}</h2>
      </div>
      <div className="p-4 space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="trigger-edit-name">{t("nameLabel")}</Label>
          <Input
            id="trigger-edit-name"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={Boolean(problems.name)}
          />
          {problems.name && <p className="text-xs text-destructive">{problems.name}</p>}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="trigger-edit-solver">{t("solverLabel")}</Label>
          <Select value={solver} onValueChange={setSolver} disabled={solversLoading && !availableSolvers.length}>
            <SelectTrigger id="trigger-edit-solver">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={MODEL_SOLVER}>{t("solverFromModel")}</SelectItem>
              {solverNames.map((s) => (
                <SelectItem key={s} value={s}>
                  {s === "auto" ? tAuto("label") : solverDisplayName(s)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">{t("solverHelp")}</p>
        </div>

        {fields.length > 0 && (
          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-medium">{t("defaultsTitle")}</h3>
              <p className="text-xs text-muted-foreground">{t("defaultsHelp")}</p>
            </div>
            {fields.map((field) => {
              const id = `trigger-edit-default-${field.name}`;
              return (
                <div key={field.name} className="space-y-1.5">
                  <Label htmlFor={id}>
                    {field.name}{" "}
                    <span className="text-xs text-muted-foreground font-normal">
                      ({field.type} → <code>{field.model_field_path}</code>)
                    </span>
                  </Label>
                  <Input
                    id={id}
                    value={defaults[field.name] ?? ""}
                    onChange={(e) =>
                      setDefaults((prev) => ({ ...prev, [field.name]: e.target.value }))
                    }
                    aria-invalid={Boolean(problems[field.name])}
                    className="font-mono text-sm"
                  />
                  {problems[field.name] && (
                    <p className="text-xs text-destructive">{problems[field.name]}</p>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onCancel} disabled={saving}>
            {t("cancel")}
          </Button>
          <Button type="submit" size="sm" disabled={saving}>
            {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
            {saving ? t("saving") : t("save")}
          </Button>
        </div>
      </div>
    </form>
  );
}
