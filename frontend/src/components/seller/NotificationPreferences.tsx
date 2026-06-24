"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { NotificationPreferenceEntry } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DollarSign, Wallet, Star, Clock } from "lucide-react";

const EVENT_TYPES = [
  { key: "sale", icon: DollarSign },
  { key: "payout", icon: Wallet },
  { key: "review", icon: Star },
  { key: "promotion_expiring", icon: Clock },
] as const;

const CHANNELS = ["in_app", "email"] as const;

export function NotificationPreferences() {
  const t = useTranslations("seller.notifications");
  const [preferences, setPreferences] = useState<NotificationPreferenceEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getNotificationPreferences()
      .then((res) => setPreferences(res.preferences))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const getEnabled = (eventType: string, channel: string): boolean => {
    const pref = preferences.find(
      (p) => p.event_type === eventType && p.channel === channel
    );
    return pref?.enabled ?? (channel === "in_app");
  };

  const handleToggle = async (eventType: string, channel: string) => {
    const current = getEnabled(eventType, channel);
    const newEnabled = !current;

    // Optimistic update
    setPreferences((prev) =>
      prev.map((p) =>
        p.event_type === eventType && p.channel === channel
          ? { ...p, enabled: newEnabled }
          : p
      )
    );

    try {
      const res = await api.updateNotificationPreference({
        event_type: eventType,
        channel,
        enabled: newEnabled,
      });
      setPreferences(res.preferences);
    } catch {
      // Revert on error
      setPreferences((prev) =>
        prev.map((p) =>
          p.event_type === eventType && p.channel === channel
            ? { ...p, enabled: current }
            : p
        )
      );
    }
  };

  const eventLabel = (key: string): string => {
    const map: Record<string, string> = {
      sale: t("eventNewSale"),
      payout: t("eventPayoutCompleted"),
      review: t("eventNewReview"),
      promotion_expiring: t("eventPromotionExpiring"),
    };
    return map[key] ?? key;
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-48" />
        </CardHeader>
        <CardContent className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-[1fr_80px_80px] gap-2 pb-2 border-b mb-2">
          <div />
          {CHANNELS.map((ch) => (
            <div
              key={ch}
              className="text-xs font-medium text-muted-foreground text-center"
            >
              {ch === "in_app" ? t("channelInApp") : t("channelEmail")}
            </div>
          ))}
        </div>

        {EVENT_TYPES.map(({ key, icon: Icon }) => (
          <div
            key={key}
            className="grid grid-cols-[1fr_80px_80px] gap-2 items-center py-2"
          >
            <div className="flex items-center gap-2">
              <Icon className="w-4 h-4 text-muted-foreground" />
              <span className="text-sm">{eventLabel(key)}</span>
            </div>
            {CHANNELS.map((ch) => {
              const enabled = getEnabled(key, ch);
              return (
                <div key={ch} className="flex justify-center">
                  <button
                    type="button"
                    role="switch"
                    aria-checked={enabled}
                    onClick={() => handleToggle(key, ch)}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                      enabled ? "bg-primary" : "bg-muted"
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
                        enabled ? "translate-x-4" : "translate-x-0.5"
                      }`}
                    />
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
