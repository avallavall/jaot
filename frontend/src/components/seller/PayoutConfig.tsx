"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { WithdrawalSchedule } from "@/lib/api";

interface PayoutConfigProps {
  schedules: WithdrawalSchedule[];
  creditsEarned: number;
  onScheduleCreate: (data: {
    frequency: string;
    amount_type: string;
    amount_value?: number;
    min_threshold: number;
  }) => Promise<void>;
  onScheduleDelete: (id: string) => Promise<void>;
}

const FREQUENCY_OPTIONS = ["weekly", "biweekly", "monthly", "quarterly"] as const;
const AMOUNT_TYPE_OPTIONS = ["all", "percentage", "fixed"] as const;

export function PayoutConfig({
  schedules,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  creditsEarned,
  onScheduleCreate,
  onScheduleDelete,
}: PayoutConfigProps) {
  const t = useTranslations("seller.earnings");

  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    frequency: "monthly" as string,
    amount_type: "all" as string,
    amount_value: "",
    min_threshold: "100",
  });

  const handleCreate = async () => {
    setSaving(true);
    try {
      await onScheduleCreate({
        frequency: form.frequency,
        amount_type: form.amount_type,
        amount_value:
          form.amount_type !== "all" ? parseFloat(form.amount_value) : undefined,
        min_threshold: parseInt(form.min_threshold) || 100,
      });
      setShowForm(false);
      setForm({
        frequency: "monthly",
        amount_type: "all",
        amount_value: "",
        min_threshold: "100",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    await onScheduleDelete(id);
  };

  const activeSchedules = schedules.filter((s) => s.is_active);

  return (
    <div className="bg-card border rounded-lg p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">{t("payoutConfig")}</h3>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowForm(!showForm)}
        >
          {t("addSchedule")}
        </Button>
      </div>

      {showForm && (
        <div className="bg-muted/30 rounded-lg p-4 mb-4 space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label
                htmlFor="payout-frequency"
                className="block text-sm mb-1 font-medium"
              >
                {t("frequency")}
              </label>
              <select
                id="payout-frequency"
                value={form.frequency}
                onChange={(e) =>
                  setForm({ ...form, frequency: e.target.value })
                }
                className="w-full px-3 py-2 rounded-md border bg-background text-sm"
              >
                {FREQUENCY_OPTIONS.map((f) => (
                  <option key={f} value={f}>
                    {t(f)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="payout-amount-type"
                className="block text-sm mb-1 font-medium"
              >
                {t("amountType")}
              </label>
              <select
                id="payout-amount-type"
                value={form.amount_type}
                onChange={(e) =>
                  setForm({ ...form, amount_type: e.target.value })
                }
                className="w-full px-3 py-2 rounded-md border bg-background text-sm"
              >
                {AMOUNT_TYPE_OPTIONS.map((at) => (
                  <option key={at} value={at}>
                    {t(at)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {form.amount_type !== "all" && (
            <div>
              <label htmlFor="payout-amount-value" className="block text-sm mb-1 font-medium">
                {t("amountValue")}
              </label>
              <Input
                id="payout-amount-value"
                type="number"
                placeholder={
                  form.amount_type === "percentage" ? "50" : "500"
                }
                value={form.amount_value}
                onChange={(e) =>
                  setForm({ ...form, amount_value: e.target.value })
                }
              />
            </div>
          )}

          <div>
            <label htmlFor="payout-min-threshold" className="block text-sm mb-1 font-medium">
              {t("minThreshold")}
            </label>
            <Input
              id="payout-min-threshold"
              type="number"
              placeholder="100"
              value={form.min_threshold}
              onChange={(e) =>
                setForm({ ...form, min_threshold: e.target.value })
              }
            />
          </div>

          <div className="flex gap-2">
            <Button size="sm" onClick={handleCreate} disabled={saving}>
              {t("addSchedule")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowForm(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}

      {activeSchedules.length > 0 ? (
        <div className="space-y-2">
          {activeSchedules.map((schedule) => {
            const s = schedule as unknown as Record<string, unknown>;
            return (
              <div
                key={schedule.id}
                className="flex items-center justify-between p-3 bg-muted/30 rounded-lg"
              >
                <div>
                  <div className="font-medium capitalize">
                    {t(schedule.frequency as "weekly" | "biweekly" | "monthly" | "quarterly")}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    {s.amount_type === "all"
                      ? t("all")
                      : s.amount_type === "percentage"
                        ? `${s.amount_value}% - ${t("percentage")}`
                        : `${s.amount_value} - ${t("fixed")}`}
                    {" | "}
                    {t("minThreshold")}: {String(s.min_threshold ?? 100)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t("nextExecution")}:{" "}
                    {new Date(schedule.next_execution).toLocaleDateString()}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDelete(schedule.id)}
                  className="text-red-600 hover:text-red-700 hover:bg-red-50"
                >
                  {t("deleteSchedule")}
                </Button>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t("noSchedules")}</p>
      )}
    </div>
  );
}
