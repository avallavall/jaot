/**
 * Platform-integration E2E: execution provenance + standard-format I/O.
 *
 * Drives the real prod stack (login via storageState) to verify and capture:
 *  - the executions history showing coloured origin badges + back-to-origin links
 *  - the visual builder importing a standard MPS file onto the canvas
 *  - the visual builder's "Export model" dropdown (MPS/LP/CIP/JSON)
 *
 * Screenshots go to SHOT_DIR (a scratchpad path outside the repo) so they are
 * never committed.
 */
import { test, expect } from "@playwright/test";
import path from "path";
import fs from "fs";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

const SHOT_DIR = process.env.SHOT_DIR || path.join(__dirname, "__shots__");
fs.mkdirSync(SHOT_DIR, { recursive: true });
const shot = (name: string): string => path.join(SHOT_DIR, name);

const BASE = process.env.BASE_URL || "http://localhost:3000";
const MPS_FIXTURE = path.join(__dirname, "..", "..", "tests", "fixtures", "simple.mps");

const TINY_PROBLEM = {
  name: "e2e_provenance",
  variables: [{ name: "x", type: "continuous", lower_bound: 0, upper_bound: 5 }],
  objective: { sense: "maximize", expression: "x" },
  constraints: [],
};

test.describe("Platform integration — provenance + standard I/O", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("history shows origin badges and back-to-origin links", async ({ page }) => {
    // Seed executions with varied provenance through the authenticated API so the
    // history has something with non-"manual" origins to render.
    for (const qs of [
      "origin=visual_builder&source_kind=builder_document&source_id=bld_e2e_demo",
      "origin=ai_builder&source_kind=builder_document&source_id=bld_e2e_demo",
      "origin=import&source_kind=imported_file",
    ]) {
      const res = await page.request.post(`${BASE}/api/v2/solve?${qs}`, { data: TINY_PROBLEM });
      expect(res.ok(), `seed solve failed: ${res.status()}`).toBeTruthy();
    }

    await page.goto("/solve/executions");
    // At least one rich-origin badge must be visible IN THE TABLE (scope away
    // from the filter <select>, whose <option>s carry the same text).
    const table = page.locator("table");
    await expect(
      table.getByText(/Visual builder|AI builder|Import/).first()
    ).toBeVisible({ timeout: 20_000 });
    // The back-to-origin link for ad-hoc rows.
    await expect(page.getByRole("link", { name: /Open origin/i }).first()).toBeVisible();
    await page.screenshot({ path: shot("01-history-origin-badges.png"), fullPage: true });
  });

  test("visual builder imports MPS and exports a model", async ({ page }) => {
    await page.goto("/builder/new");
    await page.waitForLoadState("domcontentloaded");

    // Import a standard MPS file (hidden input accepts .mps now).
    await page.locator('input[type="file"]').setInputFiles(MPS_FIXTURE);

    // Canvas should populate with React Flow nodes from the imported model.
    await expect(page.locator(".react-flow__node").first()).toBeVisible({ timeout: 25_000 });
    await page.screenshot({ path: shot("02-builder-imported-mps.png"), fullPage: true });

    // Open the "Export model" dropdown and confirm the standard formats.
    await page.getByRole("button", { name: /Download Model/i }).click();
    await expect(page.getByRole("menuitem", { name: /MPS/i })).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: shot("03-builder-export-dropdown.png") });
  });
});
