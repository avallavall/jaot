"use client";

import { useState, useEffect, useRef } from "react";
import { Bell, CheckCheck } from "lucide-react";
import { toast } from "sonner";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { notificationText } from "@/lib/notification-text";
import type { Notification } from "@/lib/types";
import { useDateFormat } from "@/hooks/useDateFormat";

export function NotificationBell() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const pollInterval = useRef<NodeJS.Timeout | null>(null);
  const prevUnreadCountRef = useRef<number | null>(null);
  const t = useTranslations("common");
  const { day } = useDateFormat();
  // The notification body itself is written from `type` + `data`, not from the
  // English title/message the server stored — see lib/notification-text.
  const tType = useTranslations("common.notifications.types");
  const locale = useLocale();
  // Session state comes from the auth context, not from a `jaot_api_key` in
  // localStorage: the web app authenticates with HttpOnly cookies, so that key
  // is absent for every browser login and these guards returned early every
  // time — the bell stayed empty and silent no matter what the API held.
  const { isAuthenticated } = useAuth();

  const fetchNotifications = async () => {
    if (!isAuthenticated) return;

    try {
      const data = await api.getNotifications({ limit: 10 });
      setNotifications(data.items);
      setUnreadCount(data.unread_count);
    } catch (err) {
      console.warn('Failed to fetch notifications:', err);
    }
  };

  const markAsRead = async (notificationId: string) => {
    if (!isAuthenticated) return;

    try {
      await api.markAsRead(notificationId);

      setNotifications((prev) =>
        prev.map((n) =>
          n.id === notificationId ? { ...n, is_read: true } : n
        )
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch (err) {
      console.warn('Failed to mark notification as read:', err);
    }
  };

  const markAllAsRead = async () => {
    if (!isAuthenticated) return;

    setIsLoading(true);
    try {
      await api.markAllAsRead();

      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch (err) {
      console.warn('Failed to mark all notifications as read:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleNotificationClick = (notification: Notification) => {
    if (!notification.is_read) {
      markAsRead(notification.id);
    }
    const notifExt = notification as unknown as Record<string, unknown>;
    if (notifExt.link) {
      window.location.href = notifExt.link as string;
    }
  };

  const getNotificationIcon = (type: string) => {
    switch (type) {
      case "execution_completed":
        return "✅";
      case "execution_failed":
        return "❌";
      default:
        return "📬";
    }
  };

  const formatTimeAgo = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return t("notifications.justNow");
    if (diffMins < 60) return t("notifications.minutesAgo", { count: diffMins });
    if (diffHours < 24) return t("notifications.hoursAgo", { count: diffHours });
    if (diffDays < 7) return t("notifications.daysAgo", { count: diffDays });
    return day(date);
  };

  useEffect(() => {
    // Keyed on the session: the context resolves it asynchronously, so mounting
    // before it lands must not leave the bell permanently unfetched.
    if (!isAuthenticated) return;

    // Poll with full notification content so toast can read latest notification
    fetchNotifications();
    pollInterval.current = setInterval(fetchNotifications, 30000);

    return () => {
      if (pollInterval.current) {
        clearInterval(pollInterval.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated]);

  useEffect(() => {
    if (isOpen) {
      fetchNotifications();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Fire toast when unread count increases
  useEffect(() => {
    if (prevUnreadCountRef.current !== null && unreadCount > prevUnreadCountRef.current) {
      const latest = notifications.find((n) => !n.is_read);
      if (latest) {
        const { title, message } = notificationText(latest, tType, locale);
        const show = latest.type === "execution_failed" ? toast.error : toast.success;
        show(title, {
          description: message,
          action: { label: t("view"), onClick: () => setIsOpen(true) },
        });
      }
    }
    prevUnreadCountRef.current = unreadCount;
  }, [unreadCount, notifications, t, tType, locale]);

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={t("notifications.title")}
        >
          <Bell className="h-5 w-5" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-red-500 text-white text-xs flex items-center justify-center font-medium">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="flex items-center justify-between p-3 border-b">
          <h3 className="font-semibold">{t("notifications.title")}</h3>
          {unreadCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={markAllAsRead}
              disabled={isLoading}
              className="text-xs"
            >
              <CheckCheck className="h-4 w-4 mr-1" />
              {t("notifications.markAllRead")}
            </Button>
          )}
        </div>

        <div className="max-h-96 overflow-y-auto">
          {notifications.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <Bell className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>{t("notifications.noNotifications")}</p>
            </div>
          ) : (
            <div className="divide-y">
              {notifications.map((notification) => {
                const { title, message } = notificationText(notification, tType, locale);
                return (
                <button
                  key={notification.id}
                  onClick={() => handleNotificationClick(notification)}
                  className={cn(
                    "w-full text-left p-3 hover:bg-muted/50 transition-colors",
                    !notification.is_read && "bg-muted/30"
                  )}
                >
                  <div className="flex gap-3">
                    <span className="text-lg flex-shrink-0">
                      {getNotificationIcon(notification.type)}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <p
                          className={cn(
                            "text-sm truncate",
                            !notification.is_read && "font-medium"
                          )}
                        >
                          {title}
                        </p>
                        {!notification.is_read && (
                          <span className="h-2 w-2 rounded-full bg-blue-500 flex-shrink-0 mt-1.5" />
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
                        {message}
                      </p>
                      <p className="text-xs text-muted-foreground/60 mt-1">
                        {formatTimeAgo(notification.created_at)}
                      </p>
                    </div>
                  </div>
                </button>
                );
              })}
            </div>
          )}
        </div>

        {/* No "view all" footer: there is no notifications page to send anyone to.
            The link pointed at /workspace/notifications, which has never existed —
            invisible until now only because the list it sat under was always empty.
            This panel shows the latest ten; add the footer back with the page. */}
      </PopoverContent>
    </Popover>
  );
}
