import { spawnSync } from "node:child_process";
import { describe, it, expect } from "vitest";

/**
 * Catches MISSING_MESSAGE bugs at test time instead of letting raw next-intl
 * keys leak into production toasts (e.g. `builder.aiAssistant.solveFailed`
 * appearing verbatim because the locale JSON was missing the entry).
 *
 * The check delegates to scripts/check-i18n-keys.mjs which scans every
 * `useTranslations(ns)` + `t("key")` invocation in src/ and verifies the
 * resolved dot-path exists in all 5 locale JSONs (en, es, ca, fr, de).
 */
describe("i18n coverage", () => {
  it("every t() key resolves in every locale JSON", () => {
    const result = spawnSync("node", ["scripts/check-i18n-keys.mjs"], {
      encoding: "utf8",
    });

    if (result.status !== 0) {
      // Surface the script's grouped output so the failing keys are visible
      // in the test report instead of just an exit code.
      throw new Error(
        `i18n coverage failed (exit ${result.status}):\n${result.stdout}${result.stderr}`,
      );
    }

    expect(result.status).toBe(0);
  });
});
