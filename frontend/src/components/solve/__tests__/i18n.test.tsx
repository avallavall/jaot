/**
 * Vitest unit tests for SolverSelect i18n label rendering.
 *
 * Replaces frontend/e2e/phase5-i18n.spec.ts (demoted — tests component-level
 * rendering, not a real integration boundary). See plan 11-05 (P11-REFACTOR-07).
 *
 * Verifies that the "selectLabel" rendered by <SolverSelect> matches the
 * locale-specific translation for each of the 5 supported locales.
 *
 * Uses NextIntlClientProvider with real message files so assertions are honest —
 * the global next-intl mock in setup.tsx is bypassed via vi.unmock.
 */
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, it, expect, vi } from "vitest";
import { SolverSelect } from "../SolverSelect";

// Bypass the global vi.mock("next-intl") in setup.tsx so NextIntlClientProvider
// uses the real implementation with actual locale messages.
vi.unmock("next-intl");

// Import real locale message files
import enMessages from "../../../../messages/en.json";
import esMessages from "../../../../messages/es.json";
import caMessages from "../../../../messages/ca.json";
import frMessages from "../../../../messages/fr.json";
import deMessages from "../../../../messages/de.json";

type LocaleMessages = Record<string, unknown>;

interface LocaleCase {
  locale: string;
  messages: LocaleMessages;
  expectedLabel: string;
}

const LOCALE_CASES: LocaleCase[] = [
  { locale: "en", messages: enMessages as LocaleMessages, expectedLabel: "Solver" },
  { locale: "es", messages: esMessages as LocaleMessages, expectedLabel: "Solver" },
  { locale: "ca", messages: caMessages as LocaleMessages, expectedLabel: "Solver" },
  { locale: "fr", messages: frMessages as LocaleMessages, expectedLabel: "Solveur" },
  { locale: "de", messages: deMessages as LocaleMessages, expectedLabel: "Solver" },
];

describe("SolverSelect — i18n label localization (P11-REFACTOR-07)", () => {
  for (const { locale, messages, expectedLabel } of LOCALE_CASES) {
    it(`selectLabel is localized correctly in ${locale}`, () => {
      render(
        <NextIntlClientProvider locale={locale} messages={messages}>
          <SolverSelect
            solverName="auto"
            onSolverChange={vi.fn()}
            loading={false}
            availableSolvers={[]}
          />
        </NextIntlClientProvider>,
      );

      // The SolverSelect renders <Label> with tSolvers("selectLabel").
      // We assert the translated label text is visible in the rendered output.
      const label = screen.getByText(expectedLabel);
      expect(label).toBeInTheDocument();
    });
  }

  it("covers all 5 supported locales", () => {
    expect(LOCALE_CASES).toHaveLength(5);
    const locales = LOCALE_CASES.map((c) => c.locale);
    expect(locales).toEqual(["en", "es", "ca", "fr", "de"]);
  });
});
