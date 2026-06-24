"use client";

import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import { api, ApiError } from "@/lib/api";
import type { TriggerSchedule } from "@/lib/types";
import { formatNextRun } from "@/lib/cron-utils";
import { useWorkspacePermission } from "@/hooks/useWorkspacePermission";
import { ScheduleForm } from "./ScheduleForm";
import { ScheduleStatusBanner } from "./ScheduleStatusBanner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDialog } from "@/components/ui/dialog-custom";
import { Calendar } from "lucide-react";

interface ScheduleTabProps {
  triggerId: string;
}

export function ScheduleTab({ triggerId }: ScheduleTabProps) {
  const t = useTranslations("triggers.schedule");
  const locale = useLocale();
  const canEdit = useWorkspacePermission("editor");
  const dialog = useDialog();

  const [schedule, setSchedule] = useState<TriggerSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadSchedule = useCallback(async () => {
    setLoading(true);
    setNotFound(false);
    try {
      const data = await api.schedules.get(triggerId);
      setSchedule(data);
    } catch (err) {
      // 404 means no schedule exists -- that's a valid state
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        setSchedule(null);
      } else {
        toast.error(err instanceof Error ? err.message : t("loadError"));
      }
    } finally {
      setLoading(false);
    }
  }, [triggerId, t]);

  useEffect(() => {
    loadSchedule();
  }, [loadSchedule]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (notFound && !showForm) {
    return (
      <div className="text-center py-12 border-2 border-dashed rounded-lg">
        <Calendar className="w-10 h-10 mx-auto text-muted-foreground/40 mb-4" />
        <h3 className="text-lg font-semibold mb-2">{t("noSchedule")}</h3>
        <Button onClick={() => setShowForm(true)} disabled={!canEdit}>
          {t("setupSchedule")}
        </Button>
      </div>
    );
  }

  if (notFound && showForm) {
    return (
      <div className="space-y-6">
        <h3 className="text-lg font-semibold">{t("setupSchedule")}</h3>
        <ScheduleForm
          triggerId={triggerId}
          schedule={null}
          onSaved={(s) => {
            setSchedule(s);
            setNotFound(false);
            setShowForm(false);
          }}
          onCancel={() => setShowForm(false)}
          disabled={!canEdit}
        />
      </div>
    );
  }

  const handleToggle = async () => {
    if (!schedule) return;
    setToggling(true);
    try {
      const updated = await api.schedules.update(triggerId, {
        is_enabled: !schedule.is_enabled,
      });
      setSchedule(updated);
      toast.success(updated.is_enabled ? t("enabled") : t("disabled"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toggleError"));
    } finally {
      setToggling(false);
    }
  };

  const handleReEnable = async () => {
    setToggling(true);
    try {
      const updated = await api.schedules.update(triggerId, {
        is_enabled: true,
      });
      setSchedule(updated);
      toast.success(t("enabled"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toggleError"));
    } finally {
      setToggling(false);
    }
  };

  const handleDelete = () => {
    dialog.confirmCallback(
      t("deleteConfirm"),
      async () => {
        setDeleting(true);
        try {
          await api.schedules.delete(triggerId);
          setSchedule(null);
          setNotFound(true);
          setShowForm(false);
          toast.success(t("deleteSuccess"));
        } catch (err) {
          toast.error(err instanceof Error ? err.message : t("deleteError"));
        } finally {
          setDeleting(false);
        }
      },
      t("deleteSchedule")
    );
  };

  return (
    <div className="space-y-6">
      {schedule && (
        <ScheduleStatusBanner
          consecutiveFailures={schedule.consecutive_failures}
          isEnabled={schedule.is_enabled}
          onReEnable={handleReEnable}
          loading={toggling}
        />
      )}

      {schedule && (
        <div className="flex items-center justify-between p-4 border rounded-lg bg-card">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <Button
                variant="outline"
                size="sm"
                onClick={handleToggle}
                disabled={toggling || !canEdit}
              >
                {schedule.is_enabled
                  ? t("disableSchedule")
                  : t("enableSchedule")}
              </Button>
              <span
                className={`text-sm font-medium ${
                  schedule.is_enabled
                    ? "text-green-600 dark:text-green-400"
                    : "text-muted-foreground"
                }`}
              >
                {schedule.is_enabled ? t("enabled") : t("disabled")}
              </span>
            </div>
            {schedule.next_run_at && schedule.is_enabled && (
              <p className="text-sm text-muted-foreground mt-1">
                {t("nextRunIn", formatNextRun(schedule.next_run_at, locale))}
              </p>
            )}
            {schedule.last_run_at && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {t("lastRun")}:{" "}
                {formatNextRun(schedule.last_run_at, locale).absolute}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="border rounded-lg p-4 bg-card">
        <h3 className="text-sm font-semibold mb-4">{t("editSchedule")}</h3>
        <ScheduleForm
          triggerId={triggerId}
          schedule={schedule}
          onSaved={(s) => setSchedule(s)}
          disabled={!canEdit}
        />
      </div>

      {canEdit && (
        <div className="pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleDelete}
            disabled={deleting}
            className="text-destructive hover:text-destructive hover:bg-destructive/10"
          >
            {t("deleteSchedule")}
          </Button>
        </div>
      )}

      <dialog.DialogComponent />
    </div>
  );
}
