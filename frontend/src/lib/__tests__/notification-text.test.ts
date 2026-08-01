import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { notificationText, type Translator } from "../notification-text";
import type { Notification } from "@/lib/types";

/**
 * The bell used to print the English title/message the server stored. It now
 * renders from `type` + `data`, and must fall back to the stored text whenever
 * it cannot — a system message, an unknown type, or a row written before the
 * payload carried what the sentence needs.
 */

const MESSAGES: Record<string, Record<string, string>> = {
  "execution_completed.title": "Ejecución completada",
  "execution_completed.message": "Tu optimización «{model}» ha terminado correctamente.",
  "execution_completed.messageWithObjective":
    "Tu optimización «{model}» ha terminado correctamente. Valor objetivo: {objective}",
  "execution_failed.title": "Ejecución fallida",
  "execution_failed.message": "Tu optimización «{model}» ha fallado: {error}",
  "model_activated.title": "Modelo adoptado",
  "model_activated.message": "Tu modelo «{model}» se ha añadido al estudio de otro equipo.",
  "new_review.title": "Nueva reseña",
  "new_review.message": "Tu modelo «{model}» ha recibido una reseña: {stars}",
} as unknown as Record<string, Record<string, string>>;

const t = Object.assign(
  (key: string, values?: Record<string, string | number>): string => {
    const raw = MESSAGES[key] as unknown as string;
    if (!raw) return key;
    return raw.replace(/\{(\w+)\}/g, (_, name) => String(values?.[name] ?? `{${name}}`));
  },
  { has: (key: string) => key in MESSAGES },
) as Translator;

function make(overrides: Partial<Notification>): Notification {
  return {
    id: "ntf_1",
    type: "execution_completed",
    title: "Execution Completed",
    message: "Your optimization 'Fleet' completed successfully.",
    is_read: false,
    created_at: "2026-08-01T09:00:00Z",
    ...overrides,
  } as Notification;
}

describe("notificationText", () => {
  it("writes a completed solve from its payload, objective included", () => {
    const out = notificationText(
      make({ data: { model_name: "Fleet", objective_value: 12.5 } }),
      t,
      "es",
    );
    expect(out.title).toBe("Ejecución completada");
    expect(out.message).toBe(
      "Tu optimización «Fleet» ha terminado correctamente. Valor objetivo: 12,5",
    );
  });

  it("omits the objective clause when the run has no objective value", () => {
    const out = notificationText(make({ data: { model_name: "Fleet" } }), t, "es");
    expect(out.message).toBe("Tu optimización «Fleet» ha terminado correctamente.");
  });

  it("formats the objective in the reader's notation", () => {
    const es = notificationText(make({ data: { model_name: "F", objective_value: 1234.5 } }), t, "es");
    const en = notificationText(make({ data: { model_name: "F", objective_value: 1234.5 } }), t, "en");
    expect(es.message).toContain("1234,5");
    expect(en.message).toContain("1,234.5");
  });

  it("renders a failure, a review and an adoption", () => {
    expect(
      notificationText(
        make({ type: "execution_failed", data: { model_name: "Fleet", error: "infeasible" } }),
        t,
        "es",
      ).message,
    ).toBe("Tu optimización «Fleet» ha fallado: infeasible");

    expect(
      notificationText(
        make({ type: "new_review", data: { model_name: "Fleet", rating: 4 } }),
        t,
        "es",
      ).message,
    ).toBe("Tu modelo «Fleet» ha recibido una reseña: ★★★★");

    expect(
      notificationText(make({ type: "model_activated", data: { model_name: "Fleet" } }), t, "es")
        .title,
    ).toBe("Modelo adoptado");
  });

  // CONTRACT-TEST: never show less than the server already said.
  it.each([
    ["no data at all", make({ data: undefined })],
    ["a payload missing the model name", make({ data: { objective_value: 1 } })],
    ["a failure with no error text", make({ type: "execution_failed", data: { model_name: "F" } })],
    ["a review with no rating", make({ type: "new_review", data: { model_name: "F" } })],
    ["an unknown type", make({ type: "solver_license_expiring" as unknown as Notification["type"] })],
    ["a free-form system message", make({ type: "system" })],
  ])("falls back to the stored text for %s", (_label, notification) => {
    const out = notificationText(notification, t, "es");
    expect(out.title).toBe(notification.title);
    expect(out.message).toBe(notification.message);
  });
});

describe("notification type translations", () => {
  const LOCALES = ["en", "es", "ca", "fr", "de"];
  const KEYS = [
    "execution_completed.title",
    "execution_completed.message",
    "execution_completed.messageWithObjective",
    "execution_failed.title",
    "execution_failed.message",
    "model_activated.title",
    "model_activated.message",
    "new_review.title",
    "new_review.message",
  ];

  it.each(LOCALES)("%s has text for every notification the renderer handles", (locale) => {
    const m = JSON.parse(
      readFileSync(join(process.cwd(), "messages", `${locale}.json`), "utf8"),
    );
    const types = m.common.notifications.types;
    const missing = KEYS.filter((key) => {
      const [group, leaf] = key.split(".");
      return typeof types?.[group]?.[leaf] !== "string";
    });
    expect(missing).toEqual([]);
  });
});
