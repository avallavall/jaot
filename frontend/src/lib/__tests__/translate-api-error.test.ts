import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ApiError } from "../api";
import { translateApiError, type ErrorTranslator } from "../errors";

/**
 * Four authentication screens printed the API's English `detail` under otherwise
 * translated pages. The server now names its failures; the screen renders the
 * name, and falls back to the caller's translated message when it cannot.
 */

const MESSAGES: Record<string, string> = {
  "auth.invalid_credentials": "Ese correo y esa contraseña no corresponden a ninguna cuenta.",
  "auth.account_locked": "Bloqueada. Inténtalo en {minutes} minutos.",
};

const t = Object.assign(
  (key: string, values?: Record<string, string | number>): string =>
    (MESSAGES[key] ?? key).replace(/\{(\w+)\}/g, (_, n) => String(values?.[n] ?? `{${n}}`)),
  { has: (key: string) => key in MESSAGES },
) as ErrorTranslator;

describe("translateApiError", () => {
  it("renders the code the server sent", () => {
    const error = new ApiError(401, "Invalid email or password", "Invalid email or password", "auth.invalid_credentials");
    expect(translateApiError(error, t, "generic")).toBe(MESSAGES["auth.invalid_credentials"]);
  });

  it("passes the error's params into the message", () => {
    const error = new ApiError(
      423,
      "Account temporarily locked. Try again in 7 minutes.",
      "Account temporarily locked. Try again in 7 minutes.",
      "auth.account_locked",
      { minutes: 7 },
    );
    expect(translateApiError(error, t, "generic")).toBe("Bloqueada. Inténtalo en 7 minutos.");
  });

  // CONTRACT-TEST: the English `detail` never reaches a translated screen.
  it.each([
    ["an error with no code", new ApiError(500, "Boom", "Boom")],
    ["a code we have no text for", new ApiError(400, "Boom", "Boom", "auth.brand_new_case")],
    ["a plain Error", new Error("Kaboom")],
    ["something that is not an error", "just a string"],
  ])("falls back to the translated message for %s", (_label, error) => {
    expect(translateApiError(error, t, "mensaje genérico")).toBe("mensaje genérico");
  });
});

describe("error code translations", () => {
  const LOCALES = ["en", "es", "ca", "fr", "de"];
  // Mirrors the codes raised in app/api/v2/auth.py and
  // app/api/v2/routes/workspaces/invites.py.
  const CODES = [
    ["auth", "account_locked"],
    ["auth", "invalid_credentials"],
    ["auth", "verification_link_expired"],
    ["auth", "verification_link_invalid"],
    ["auth", "reset_link_invalid"],
    ["invite", "not_found"],
    ["invite", "revoked"],
    ["invite", "expired"],
    ["invite", "already_accepted"],
  ];

  it.each(LOCALES)("%s has text for every code the API raises", (locale) => {
    const m = JSON.parse(readFileSync(join(process.cwd(), "messages", `${locale}.json`), "utf8"));
    const missing = CODES.filter(([group, leaf]) => typeof m.errors?.codes?.[group]?.[leaf] !== "string");
    expect(missing).toEqual([]);
  });
});
