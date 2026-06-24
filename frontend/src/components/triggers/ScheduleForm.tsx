"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import { api } from "@/lib/api";
import type { TriggerSchedule } from "@/lib/types";
import {
  buildCronExpression,
  parseCronExpression,
  getBrowserTimezone,
} from "@/lib/cron-utils";
import { DayOfWeekPicker } from "./DayOfWeekPicker";
import { TimezoneSelect } from "./TimezoneSelect";
import { NextRunsPreview } from "./NextRunsPreview";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface ScheduleFormProps {
  triggerId: string;
  schedule: TriggerSchedule | null;
  onSaved: (schedule: TriggerSchedule) => void;
  onCancel?: () => void;
  disabled?: boolean;
}

const HOURS = Array.from({ length: 24 }, (_, i) => i);

export function ScheduleForm({
  triggerId,
  schedule,
  onSaved,
  onCancel,
  disabled,
}: ScheduleFormProps) {
  const t = useTranslations("triggers.schedule");
  const locale = useLocale();

  // Parse initial values from existing schedule
  const initial = schedule
    ? parseCronExpression(schedule.cron_expression)
    : { days: [] as string[], hour: 9 };

  const [selectedDays, setSelectedDays] = useState<string[]>(initial.days);
  const [hour, setHour] = useState<number>(initial.hour);
  const [timezone, setTimezone] = useState<string>(
    schedule?.timezone ?? getBrowserTimezone()
  );
  const [nextRuns, setNextRuns] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [showDaysError, setShowDaysError] = useState(false);

  // Debounced validation
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const validateSchedule = useCallback(
    async (days: string[], h: number, tz: string) => {
      if (days.length === 0) {
        setNextRuns([]);
        return;
      }
      try {
        const cron = buildCronExpression(days, h);
        const result = await api.schedules.validate({
          cron_expression: cron,
          timezone: tz,
        });
        if (result.valid) {
          setNextRuns(result.next_runs);
        }
      } catch (err) {
        console.warn('Failed to validate schedule:', err);
      }
    },
    []
  );

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      validateSchedule(selectedDays, hour, timezone);
    }, 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [selectedDays, hour, timezone, validateSchedule]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedDays.length === 0) {
      setShowDaysError(true);
      return;
    }
    setShowDaysError(false);
    setSaving(true);
    try {
      const cron = buildCronExpression(selectedDays, hour);
      let result: TriggerSchedule;
      if (schedule) {
        result = await api.schedules.update(triggerId, {
          cron_expression: cron,
          timezone,
        });
        toast.success(t("updateSuccess"));
      } else {
        result = await api.schedules.create(triggerId, {
          cron_expression: cron,
          timezone,
        });
        toast.success(t("createSuccess"));
      }
      onSaved(result);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  };

  const handleDaysChange = (days: string[]) => {
    setSelectedDays(days);
    if (days.length > 0) setShowDaysError(false);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-2">
        <label className="text-sm font-medium">{t("daysLabel")}</label>
        <DayOfWeekPicker
          selected={selectedDays}
          onChange={handleDaysChange}
          locale={locale}
          disabled={disabled}
        />
        {showDaysError && (
          <p className="text-sm text-destructive">{t("daysRequired")}</p>
        )}
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">{t("timeLabel")}</label>
        <Select
          value={String(hour)}
          onValueChange={(v) => setHour(Number(v))}
          disabled={disabled}
        >
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {HOURS.map((h) => (
              <SelectItem key={h} value={String(h)}>
                {String(h).padStart(2, "0")}:00
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">{t("timezoneLabel")}</label>
        <TimezoneSelect
          value={timezone}
          onChange={setTimezone}
          disabled={disabled}
        />
      </div>

      {nextRuns.length > 0 && (
        <NextRunsPreview nextRuns={nextRuns} locale={locale} />
      )}

      <div className="flex items-center gap-3 pt-2">
        <Button type="submit" disabled={saving || disabled}>
          {saving ? t("saving") : t("save")}
        </Button>
        {onCancel && (
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={saving}
          >
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
