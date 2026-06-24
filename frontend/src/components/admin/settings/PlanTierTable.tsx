"use client";

import { useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { PlanTiersResponse } from "@/lib/api";
import { useTranslations } from "next-intl";

const PLAN_KEYS = ["free", "starter", "pro", "business"] as const;

const NUMERIC_FIELDS = [
  "credits",
  "monthly_quota",
  "rate_limit_per_minute",
  "rate_limit_per_day",
  "max_solve_time_seconds",
  "max_variables",
  "max_daily_solves",
  "max_cron_schedules",
] as const;

const HEADER_MAP: Record<string, string> = {
  credits: "credits",
  monthly_quota: "monthlyQuota",
  rate_limit_per_minute: "rateLimitMin",
  rate_limit_per_day: "rateLimitDay",
  max_solve_time_seconds: "maxSolveTime",
  max_variables: "maxVariables",
  max_daily_solves: "maxDailySolves",
  max_cron_schedules: "maxCronSchedules",
};

const PLAN_LABEL_MAP: Record<string, string> = {
  free: "free",
  starter: "starter",
  pro: "pro",
  business: "business",
};

interface PlanTierTableProps {
  data: PlanTiersResponse | null;
  onRefresh: () => void;
}

export function PlanTierTable({ data, onRefresh }: PlanTierTableProps) {
  const t = useTranslations("admin.settings");
  const [dirtyValues, setDirtyValues] = useState<Record<string, Record<string, string>>>({});
  const [featureValues, setFeatureValues] = useState<Record<string, string>>({});
  const [featureErrors, setFeatureErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const plans = data?.plans ?? {};

  const getValue = (plan: string, field: string): string => {
    return dirtyValues[plan]?.[field] ?? plans[plan]?.[field] ?? "";
  };

  const getFeatureValue = (plan: string): string => {
    if (plan in featureValues) return featureValues[plan];
    return plans[plan]?.allowed_features ?? "[]";
  };

  const handleChange = (plan: string, field: string, value: string) => {
    setDirtyValues((prev) => ({
      ...prev,
      [plan]: { ...prev[plan], [field]: value },
    }));
    setMessage(null);
  };

  const handleFeatureChange = (plan: string, value: string) => {
    setFeatureValues((prev) => ({ ...prev, [plan]: value }));
    // Validate JSON
    try {
      JSON.parse(value);
      setFeatureErrors((prev) => {
        const next = { ...prev };
        delete next[plan];
        return next;
      });
    } catch {
      setFeatureErrors((prev) => ({ ...prev, [plan]: t("invalidJson") }));
    }
    setMessage(null);
  };

  const hasDirtyChanges = (): boolean => {
    return (
      Object.keys(dirtyValues).some((plan) => Object.keys(dirtyValues[plan]).length > 0) ||
      Object.keys(featureValues).length > 0
    );
  };

  const handleSave = async () => {
    if (!hasDirtyChanges()) {
      setMessage({ type: "error", text: t("noChanges") });
      return;
    }

    // Check for JSON validation errors
    if (Object.keys(featureErrors).length > 0) {
      setMessage({ type: "error", text: t("invalidJson") });
      return;
    }

    setSaving(true);
    setMessage(null);

    // Build the full plans payload
    const payload: Record<string, Record<string, string>> = {};
    for (const plan of PLAN_KEYS) {
      const planData: Record<string, string> = {};
      let hasPlanChanges = false;

      // Numeric fields
      for (const field of NUMERIC_FIELDS) {
        if (dirtyValues[plan]?.[field] !== undefined) {
          planData[field] = dirtyValues[plan][field];
          hasPlanChanges = true;
        }
      }

      // Allowed features
      if (plan in featureValues) {
        planData.allowed_features = featureValues[plan];
        hasPlanChanges = true;
      }

      if (hasPlanChanges) {
        payload[plan] = planData;
      }
    }

    try {
      await api.admin.updatePlanTiers(payload);
      setMessage({ type: "success", text: t("saved") });
      setDirtyValues({});
      setFeatureValues({});
      onRefresh();
    } catch {
      setMessage({ type: "error", text: t("validationError", { error: "Save failed" }) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-serif">{t("plans.title")}</h3>
        <p className="text-sm text-muted-foreground">{t("plans.description")}</p>
      </div>

      <div className="overflow-x-auto border border-border rounded-lg">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28">{t("plans.headers.plan")}</TableHead>
              {NUMERIC_FIELDS.map((field) => (
                <TableHead key={field} className="min-w-[100px]">
                  {t(`plans.headers.${HEADER_MAP[field]}`)}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {PLAN_KEYS.map((plan) => (
              <TableRow key={plan}>
                <TableCell className="font-medium capitalize">
                  {t(`plans.${PLAN_LABEL_MAP[plan]}`)}
                </TableCell>
                {NUMERIC_FIELDS.map((field) => (
                  <TableCell key={field} className="p-1">
                    <Input
                      type="number"
                      value={getValue(plan, field)}
                      onChange={(e) => handleChange(plan, field, e.target.value)}
                      disabled={saving}
                      className="h-8 text-sm"
                      min={0}
                    />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="space-y-4">
        <h4 className="text-sm font-medium">{t("plans.headers.allowedFeatures")}</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {PLAN_KEYS.map((plan) => (
            <div key={plan} className="space-y-1.5">
              <Label className="text-sm">
                {t("plans.allowedFeaturesLabel", { plan: t(`plans.${PLAN_LABEL_MAP[plan]}`) })}
              </Label>
              <Textarea
                value={getFeatureValue(plan)}
                onChange={(e) => handleFeatureChange(plan, e.target.value)}
                disabled={saving}
                rows={3}
                className="font-mono text-sm"
              />
              {featureErrors[plan] && (
                <p className="text-xs text-destructive">{featureErrors[plan]}</p>
              )}
              <p className="text-xs text-muted-foreground">{t("plans.allowedFeaturesHelp")}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Button onClick={handleSave} disabled={saving || !hasDirtyChanges()}>
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
    </div>
  );
}
