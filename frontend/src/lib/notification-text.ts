/**
 * Localized text for a notification.
 *
 * The server stores an English `title`/`message` — that is the wire value API and
 * MCP clients read, and it is what a historic row carries. The interface renders
 * from the notification's `type` plus its `data` payload instead, so the bell and
 * its toast speak the reader's language. Anything the renderer cannot express —
 * an unknown type, a row whose payload predates this, a free-form system message
 * — falls back to the stored text rather than showing a key or an empty line.
 */

import type { Notification } from "@/lib/types";

export interface NotificationText {
  title: string;
  message: string;
}

/** Minimal shape of next-intl's translator, so this stays unit-testable. */
export interface Translator {
  (key: string, values?: Record<string, string | number>): string;
  has(key: string): boolean;
}

function text(data: Record<string, unknown> | undefined, key: string): string | null {
  const value = data?.[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function formatObjective(value: unknown, locale: string): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(value);
}

/**
 * Build the values a notification's message needs, or null when the payload
 * cannot supply them — in which case the caller keeps the stored English.
 */
function messageKeyAndValues(
  notification: Notification,
  locale: string,
): { key: string; values: Record<string, string | number> } | null {
  const data = notification.data;
  const modelName = text(data, "model_name");

  // Read as a plain string: historic rows carry types this union never listed,
  // and they must reach the fallback rather than fail to compile a case for them.
  switch (notification.type as string) {
    case "execution_completed": {
      if (!modelName) return null;
      const objective = formatObjective(data?.objective_value, locale);
      return objective === null
        ? { key: "execution_completed.message", values: { model: modelName } }
        : {
            key: "execution_completed.messageWithObjective",
            values: { model: modelName, objective },
          };
    }
    case "execution_failed": {
      const error = text(data, "error");
      if (!modelName || !error) return null;
      return { key: "execution_failed.message", values: { model: modelName, error } };
    }
    case "model_activated": {
      if (!modelName) return null;
      return { key: "model_activated.message", values: { model: modelName } };
    }
    case "new_review": {
      const rating = data?.rating;
      if (!modelName || typeof rating !== "number") return null;
      return {
        key: "new_review.message",
        // The stars are the rating drawn, not a translatable string.
        values: { model: modelName, stars: "★".repeat(Math.max(0, Math.round(rating))) },
      };
    }
    default:
      return null;
  }
}

/**
 * Resolve a notification to the title and message to display.
 *
 * @param t  Translator scoped to the `notifications.types` namespace.
 */
export function notificationText(
  notification: Notification,
  t: Translator,
  locale: string,
): NotificationText {
  const resolved = messageKeyAndValues(notification, locale);
  const titleKey = `${notification.type}.title`;

  if (!resolved || !t.has(titleKey) || !t.has(resolved.key)) {
    return { title: notification.title, message: notification.message };
  }

  return { title: t(titleKey), message: t(resolved.key, resolved.values) };
}
