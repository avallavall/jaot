import { test, expect, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Does the real studio form solve the card it renders?
 *
 * `tests/test_template_form_contract.py` proves that the payload the form
 * WOULD submit builds the model the card describes. It does that by reading
 * `input_fields` and filtering `example_input` in Python. It cannot prove that
 * the form actually renders those fields, that the API accepts what the form
 * sends, or that the solver comes back optimal.
 *
 * These templates each had `input_fields` changed. Before that change the
 * studio dropped part of the example on submit and four of them failed
 * outright while four returned a different answer and still said OPTIMAL. This
 * spec drives the real page for each one: load the example, press Solve, and
 * require an OPTIMAL result with no console error and no 5xx.
 */

const NAV_TIMEOUT = 20_000;
const SOLVE_TIMEOUT = 60_000;

/** Cards whose form fields changed, one per kind of change. */
const TEMPLATES = [
  // a top-level key the form had no field for, so it was dropped on submit
  "property_portfolio",
  "mine_production_scheduling",
  "wastewater_treatment_allocation",
  // the form asked for fields under names the example does not use
  "drug_distribution",
  "inventory_optimization",
  "emission_reduction_planning",
  // rows carried a column the form did not declare
  "warehouse_slotting",
  "public_facility_location",
  // a generator written from scratch for this card
  "train_timetabling",
  "tournament_scheduling",
  "job_shop_scheduling",
] as const;

async function openTemplate(page: Page, templateId: string) {
  const problems: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") problems.push(`console: ${msg.text().slice(0, 200)}`);
  });
  page.on("pageerror", (err) => problems.push(`pageerror: ${String(err).slice(0, 200)}`));
  page.on("response", (res) => {
    if (res.status() >= 500) problems.push(`${res.status()} ${res.url()}`);
  });

  await page.goto(`/builder/templates/official_${templateId}`);
  const form = page.locator("form");
  await expect(form, `${templateId}: the form never rendered`).toBeVisible({
    timeout: NAV_TIMEOUT,
  });
  return { form, problems };
}

test.describe("Template form solves in the browser", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "jaot_cookie_consent",
        JSON.stringify({ essential: true, analytics: false, timestamp: new Date().toISOString() }),
      );
    });
  });

  for (const templateId of TEMPLATES) {
    test(`${templateId}: load example and solve returns optimal`, async ({ page }) => {
      const { form, problems } = await openTemplate(page, templateId);

      await form.getByRole("button", { name: /load example/i }).click();
      await expect(
        form.getByRole("button", { name: /reload example/i }),
        `${templateId}: the example did not load`,
      ).toBeVisible({ timeout: 10_000 });

      // A required field the example does not fill blocks the submit, which is
      // the failure the form contract exists to prevent. Say so plainly.
      // Match role=alert, not .text-destructive: the required-field asterisk and
      // the remove-row button carry that class too.
      await form.getByRole("button", { name: /^solve/i }).click();
      const validationErrors = form.locator("[role='alert']");
      if (await validationErrors.first().isVisible().catch(() => false)) {
        const messages = await validationErrors.allTextContents();
        throw new Error(
          `${templateId}: the form rejected its own example: ${messages.join(" | ")}`,
        );
      }

      const drawer = page.locator('[role="dialog"][aria-modal="true"]');
      await expect(drawer, `${templateId}: no results drawer`).toBeVisible({
        timeout: SOLVE_TIMEOUT,
      });

      const optimal = drawer.locator("span").filter({ hasText: /^\s*OPTIMAL\s*$/i });
      await expect(optimal.first(), `${templateId}: the solve was not optimal`).toBeVisible({
        timeout: 10_000,
      });

      // An objective the card can show means the model had one worth reporting.
      const objective = drawer.locator(".tabular-nums.font-bold").first();
      await expect(objective, `${templateId}: no objective value shown`).toBeVisible();
      expect(
        (await objective.textContent())?.trim(),
        `${templateId}: the objective is not a number`,
      ).toMatch(/[\d.]/);

      expect(problems, `${templateId} hit browser or server errors`).toEqual([]);
    });
  }
});

/**
 * Does the marketplace show the card's new words, in the reader's language?
 *
 * `tests/test_template_translations.py` proves the locale files carry the text.
 * It cannot prove the page reads them: `useTemplateTranslation` falls back to
 * the English the API served whenever a key is missing, silently, which is how
 * one card ran untranslated in all five locales without anything failing.
 *
 * The assertion runs against `document.body.innerText`, not the HTML source.
 * next-intl embeds the whole message dictionary in the page, so a `grep` over
 * the source finds text from every namespace whether it is displayed or not.
 */
// The detail page renders the long `description`, so these phrases come from it.
const MARKETPLACE_COPY: Array<{ id: string; en: string; es: string }> = [
  {
    id: "tournament_scheduling",
    en: "which of the two clubs hosts it",
    es: "decide cuál de los dos clubes lo acoge",
  },
  {
    id: "train_timetabling",
    en: "Chooses a departure minute for every train",
    es: "Elige un minuto de salida para cada tren",
  },
  {
    id: "job_shop_scheduling",
    en: "Each order is a chain of operations",
    es: "Cada pedido es una cadena de operaciones",
  },
  {
    id: "dye_batch_scheduling",
    en: "the cost is how long it sits waiting for a machine",
    es: "el coste es el tiempo que un trabajo pasa esperando máquina",
  },
  {
    id: "fleet_dispatch_mining",
    en: "The model sets a rate on every shovel-to-tip route",
    es: "El modelo fija un caudal en cada ruta de pala",
  },
];

test.describe("Marketplace shows the card's own words", () => {
  for (const { id, en, es } of MARKETPLACE_COPY) {
    test(`${id}: reads in English and Spanish`, async ({ page }) => {
      for (const [locale, expected] of [
        ["en", en],
        ["es", es],
      ] as const) {
        await page.goto(`/${locale}/marketplace/official_${id}`);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
          timeout: NAV_TIMEOUT,
        });
        const shown = await page.evaluate(() => document.body.innerText);
        expect(
          shown,
          `${id} in ${locale}: the page does not show "${expected}"`,
        ).toContain(expected);
      }
    });
  }
});
