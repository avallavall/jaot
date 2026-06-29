import { test, expect, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Studio critical-path E2E — the real end-to-end journey that the unit tests could
 * NOT catch (vitest mocks the API and never renders the callback→re-render cycle).
 * This is the regression guard for the live bugs the owner found on 2026-06-29:
 *   - BUG A: Solve hung forever on "waiting for first solution" (re-render reset loop).
 *   - BUG B: "My Models" always empty (the list page was a placeholder).
 *   - BUG C: model name not editable / not persisted.
 * Plus the UX-honesty contract (no dead "coming soon" tiles).
 *
 * The model is seeded through the app's authenticated API as a hand-built canvas
 * (the store hydrates the canonical model from `serialize(draft_canvas_json)`, so the
 * canvas — not model_json — is the source of truth on load). This avoids flaky
 * ReactFlow drag-drop while still exercising the full create→solve→list→rename flow.
 */

const NAV = 20_000;

/**
 * A trivial, always-feasible LP: minimize x s.t. x >= 8, x <= 10, x in [0, 23] → x* = 8.
 * Built in the exact node/edge shape `deserializeFromOptimizationProblem` produces, so
 * the store's `serialize(canvas)` hydration yields this model.
 */
const SEED_CANVAS = {
  nodes: [
    {
      id: "var-x",
      type: "variable",
      position: { x: 0, y: 0 },
      data: { name: "x", type: "continuous", lower_bound: 0, upper_bound: 23 },
    },
    {
      id: "objective-1",
      type: "objective",
      position: { x: 0, y: 160 },
      deletable: false,
      data: { sense: "minimize", formula: "" },
    },
    {
      id: "constraint-0",
      type: "constraint",
      position: { x: 280, y: 0 },
      data: { name: "c1", operator: ">=", rhs: 8, formula: "x >= 8" },
    },
    {
      id: "constraint-1",
      type: "constraint",
      position: { x: 280, y: 160 },
      data: { name: "c2", operator: "<=", rhs: 10, formula: "x <= 10" },
    },
  ],
  edges: [
    { id: "edge-obj-x", source: "var-x", target: "objective-1", type: "coefficient", data: { coefficient: 1 } },
    { id: "edge-c0-x", source: "var-x", target: "constraint-0", type: "coefficient", data: { coefficient: 1 } },
    { id: "edge-c1-x", source: "var-x", target: "constraint-1", type: "coefficient", data: { coefficient: 1 } },
  ],
};

const SEED_MODEL = {
  name: "E2E Critical Path",
  variables: [{ name: "x", type: "continuous", lower_bound: 0, upper_bound: 23 }],
  objective: { sense: "minimize", expression: "x" },
  constraints: [
    { name: "c1", expression: "x >= 8" },
    { name: "c2", expression: "x <= 10" },
  ],
};

/** Create a fresh blank ModelProject from the launcher; returns its `mp_…` id. */
async function createBlankProject(page: Page): Promise<string> {
  await page.goto("/studio/new");
  const blank = page.getByTestId("launcher-tile-blank");
  await expect(blank).toBeVisible({ timeout: NAV });
  await blank.click();
  await page.waitForURL(/\/studio\/(mp_[A-Za-z0-9]+)\/build/, { timeout: NAV });
  const match = page.url().match(/\/studio\/(mp_[A-Za-z0-9]+)\//);
  if (!match) throw new Error(`No project id in URL: ${page.url()}`);
  return match[1];
}

/** Seed the project's draft with a solvable model via the authenticated API. */
async function seedDraft(page: Page, projectId: string): Promise<void> {
  const getResp = await page.request.get(`/api/v2/projects/${projectId}`);
  await expect(getResp, `getProject failed: ${getResp.status()}`).toBeOK();
  const project = await getResp.json();
  const lock = project.draft_lock_version ?? 0;

  const put = await page.request.put(`/api/v2/projects/${projectId}/draft`, {
    headers: { "If-Match": String(lock) },
    data: { model_json: SEED_MODEL, canvas_json: SEED_CANVAS },
  });
  await expect(put, `seed draft failed: ${put.status()}`).toBeOK();
}

test.describe("Studio — critical path (guards live bugs A/B/C)", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test("create → seed → solve completes → My Models lists it → rename persists", async ({ page }) => {
    // Create: a blank project is created from the launcher and opens the Build tab.
    const projectId = await createBlankProject(page);

    // Seed a solvable model into the draft (reliable, API-driven), then reload so the
    // store hydrates the canonical model from the seeded canvas.
    await seedDraft(page, projectId);
    await page.goto(`/studio/${projectId}/build`);

    // BUG C — rename the model and assert it PERSISTS across a reload.
    const nameInput = page.getByTestId("studio-name-input");
    await expect(nameInput).toBeVisible({ timeout: NAV });
    await nameInput.fill("E2E Renamed Model");
    const [renameResp] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes(`/projects/${projectId}`) &&
          r.request().method() === "PATCH",
        { timeout: NAV },
      ),
      nameInput.blur(),
    ]);
    expect(renameResp.ok()).toBeTruthy();
    await page.reload();
    await expect(page.getByTestId("studio-name-input")).toHaveValue("E2E Renamed Model", {
      timeout: NAV,
    });

    // BUG A — the solve must COMPLETE, not hang on "waiting for first solution".
    await page.goto(`/studio/${projectId}/solve`);
    const solveBtn = page.getByTestId("studio-solve-run");
    await expect(solveBtn).toBeEnabled({ timeout: NAV });
    await solveBtn.click();
    // The "view results" button only renders after `onComplete` fired → completion proof.
    await expect(page.getByTestId("studio-solve-done")).toBeVisible({ timeout: 40_000 });

    // BUG B — the project now appears in "My Models" (not the empty state).
    await page.goto("/studio");
    const card = page
      .getByTestId("studio-project-card")
      .filter({ hasText: "E2E Renamed Model" });
    await expect(card).toBeVisible({ timeout: NAV });
    await expect(card).toHaveAttribute("href", new RegExp(projectId));
  });

  test("launcher offers honest controls — 'Soon' tiles are disabled, not dead buttons", async ({
    page,
  }) => {
    await page.goto("/studio/new");
    // The two implemented starting points are real, enabled buttons.
    await expect(page.getByTestId("launcher-tile-blank")).toBeEnabled();
    await expect(page.getByTestId("launcher-tile-visual")).toBeEnabled();
    // The not-yet-built tiles are visibly disabled (rendered as aria-disabled cards),
    // never clickable controls that toast "coming soon".
    for (const key of ["ai", "editor", "import", "template", "marketplace"]) {
      const tile = page.getByTestId(`launcher-tile-${key}`);
      await expect(tile).toBeVisible();
      await expect(tile).toHaveAttribute("aria-disabled", "true");
    }
  });
});
