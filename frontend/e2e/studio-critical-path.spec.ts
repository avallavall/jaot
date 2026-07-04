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
    // Let the workspace finish loading + hydrating the store before interacting, so the
    // rename doesn't race a late hydrate (dev first-load is slow to recompile).
    await page.waitForLoadState("networkidle");

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

  test("launcher — every starting point is a real, enabled control (no dead 'Soon' tiles)", async ({
    page,
  }) => {
    await page.goto("/studio/new");
    // Every tile is now implemented (P4b made 'ai' real — the last placeholder).
    for (const key of ["blank", "visual", "editor", "ai", "import", "template", "marketplace"]) {
      await expect(page.getByTestId(`launcher-tile-${key}`)).toBeEnabled();
    }
  });

  // P3: the Editor (text) lens edits the model as JSON. A valid edit reflects on the
  // canonical model; a malformed edit shows an error and BLOCKS solve (so the user never
  // acts on a model they believe they just changed). The canvas keeps the last-good model.
  test("editor lens — shows the model as JSON; invalid JSON blocks solve, valid unblocks (P3)", async ({
    page,
  }) => {
    const projectId = await createBlankProject(page);
    await seedDraft(page, projectId);

    // `?lens=editor` opens straight into the text editor (the launcher 'editor' tile path).
    await page.goto(`/studio/${projectId}/build?lens=editor`);
    const textarea = page.getByTestId("studio-editor-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    // It is seeded with the SEEDED model serialized as JSON. Match a value unique to
    // the seed (not just `"variables"`, which the pre-hydrate empty model also has):
    // typing before the project load lands would race the late hydrate, which
    // legitimately resets the editor state — a user sees their model before editing.
    await expect(textarea).toHaveValue(/"upper_bound": 23/, { timeout: NAV });

    const headerSolve = page.getByTestId("studio-header-solve");
    await expect(headerSolve).toBeEnabled();

    // Malformed JSON → inline error + solve blocked (header button disabled).
    await textarea.fill("{ this is not json");
    await expect(page.getByTestId("studio-editor-error")).toBeVisible({ timeout: NAV });
    await expect(headerSolve).toBeDisabled();

    // The block SURVIVES leaving the lens (client-side tab nav): the Solve tab's run
    // button is blocked too — switching tabs must not silently solve the last-good
    // model the user believes they just changed (the old unmount cleared the flag).
    await page.getByTestId("studio-tab-solve").click();
    await expect(page.getByTestId("studio-solve-run")).toBeDisabled();
    // Coming back re-shows the retained un-applied text with its error.
    await page.getByTestId("studio-tab-build").click();
    await page.getByTestId("studio-sublens-editor").click();
    await expect(page.getByTestId("studio-editor-textarea")).toHaveValue(
      "{ this is not json",
      { timeout: NAV },
    );
    await expect(page.getByTestId("studio-editor-error")).toBeVisible();
    await expect(headerSolve).toBeDisabled();

    // Fixing the JSON (a valid model shape) clears the error and re-enables solve.
    await textarea.fill(JSON.stringify(SEED_MODEL, null, 2));
    await expect(page.getByTestId("studio-editor-error")).toHaveCount(0, { timeout: NAV });
    await expect(headerSolve).toBeEnabled({ timeout: NAV });
  });

  // P4: the header "Explain" button jumps to the Analyze lens, which hosts the grounded
  // "Explain this model" card (the actual LLM streaming is verified out-of-band, since it
  // needs an LLM key the CI DB lacks; here we assert the wiring + card render).
  test("explain — header button opens Analyze with the Explain-model card (P4)", async ({
    page,
  }) => {
    const projectId = await createBlankProject(page);
    await seedDraft(page, projectId);
    await page.goto(`/studio/${projectId}/build`);

    await page.getByTestId("studio-header-explain").click();
    await page.waitForURL(new RegExp(`/studio/${projectId}/analyze`), { timeout: NAV });

    const card = page.getByTestId("studio-explain-model");
    await expect(card).toBeVisible({ timeout: NAV });
    await expect(page.getByTestId("studio-explain-model-run")).toBeVisible();
  });

  // P2 centralization: the 'template' tile → gallery → "Use" SEEDS a ModelProject and
  // opens the workspace (replacing the old solve-once-and-lose-it template flow).
  test("template gallery — 'Use' seeds a ModelProject and opens the workspace (P2)", async ({
    page,
  }) => {
    await page.goto("/studio/new");
    await page.getByTestId("launcher-tile-template").click();
    await page.waitForURL(/\/studio\/templates$/, { timeout: NAV });

    // The gallery is a LIST page: normal document scroll (the workspace shell's
    // overflow-hidden used to swallow it — live bug 2026-07-04) so the 100+
    // cards below the fold are reachable.
    const firstUse = page.locator('[data-testid^="use-template-"]').first();
    await expect(firstUse).toBeVisible({ timeout: NAV });
    expect(await page.locator('[data-testid^="use-template-"]').count()).toBeGreaterThan(20);
    const scrollable = await page.evaluate(() => {
      window.scrollTo(0, document.body.scrollHeight);
      return window.scrollY > 0;
    });
    expect(scrollable).toBeTruthy();
    await page.evaluate(() => window.scrollTo(0, 0));

    // Search narrows on the text the user SEES and clears back to the full grid.
    const firstTitle = (await page.locator("h3").first().innerText()).trim();
    const search = page.getByTestId("studio-templates-search");
    await search.fill("zzz-no-such-template");
    await expect(page.getByTestId("studio-templates-no-matches")).toBeVisible({ timeout: NAV });
    await search.fill(firstTitle);
    await expect(page.locator("h3").filter({ hasText: firstTitle }).first()).toBeVisible({
      timeout: NAV,
    });
    await search.fill("");
    await expect(firstUse).toBeVisible({ timeout: NAV });
    await firstUse.click();

    // Seeding creates a first-class ModelProject and drops into the Build tab.
    await page.waitForURL(/\/studio\/(mp_[A-Za-z0-9]+)\/build/, { timeout: NAV });
    // The workspace mounted with the seeded model (the name input is always present).
    await expect(page.getByTestId("studio-name-input")).toBeVisible({ timeout: NAV });
  });

  // P2 centralization: a marketplace model's "Use in studio" SEEDS a ModelProject too.
  // Uses an OFFICIAL model (materializes from its example input; community models may not).
  test("marketplace 'Use in studio' seeds a ModelProject (P2)", async ({ page }) => {
    await page.goto("/marketplace/official_assortment_planning");
    const useBtn = page.getByTestId("marketplace-use-in-studio");
    await expect(useBtn).toBeVisible({ timeout: NAV });
    await useBtn.click();
    await page.waitForURL(/\/studio\/(mp_[A-Za-z0-9]+)\/build/, { timeout: NAV });
    await expect(page.getByTestId("studio-name-input")).toBeVisible({ timeout: NAV });
  });

  // Task #16 (L1 durable AI conversation): the Assistant session is LIFTED to the
  // workspace provider, so switching tab/sub-lens no longer tears it down. CI-safe
  // proof (no LLM needed): opening the Assistant bootstraps the conversation ONCE;
  // navigating to Solve and back (client-side) does NOT re-bootstrap — the old
  // lens-owned effect re-ran the find-or-create on every remount.
  test("assistant session is lifted to the provider — bootstraps once across tab switches (§16)", async ({
    page,
  }) => {
    const projectId = await createBlankProject(page);
    await seedDraft(page, projectId);

    // Count conversation list calls (the find step of find-or-create). Lifted → exactly 1.
    let convLists = 0;
    page.on("request", (req) => {
      if (
        req.method() === "GET" &&
        req.url().includes("/api/v2/llm/conversations") &&
        req.url().includes("model_project_id")
      ) {
        convLists += 1;
      }
    });

    // Open the Assistant sub-lens (full load) → the session bootstraps once.
    await page.goto(`/studio/${projectId}/build?lens=assistant`);
    await expect(page.getByTestId("studio-assistant")).toBeVisible({ timeout: NAV });

    // Leave to Solve and back — all CLIENT-SIDE (the layout/provider must persist).
    await page.getByTestId("studio-tab-solve").click();
    await expect(page.getByTestId("studio-solve-run")).toBeVisible({ timeout: NAV });
    await page.getByTestId("studio-tab-build").click();
    await page.getByTestId("studio-sublens-assistant").click();
    await expect(page.getByTestId("studio-assistant")).toBeVisible({ timeout: NAV });

    // The conversation was fetched ONCE for the whole workspace lifetime, not on each
    // Assistant mount — proof the session survives in the provider above the tabs.
    expect(convLists).toBe(1);
  });

  // Fix-wave (2026-06-30): a studio async solve must land in the GLOBAL history as
  // COMPLETED (not a 'pending' zombie — the worker now writes the row back on success),
  // labelled with the model NAME + a studio origin badge (not the generic "visual builder").
  test("studio solve shows COMPLETED with the model name + studio origin in global history", async ({
    page,
  }) => {
    const projectId = await createBlankProject(page);
    await seedDraft(page, projectId);
    // Name it via the API (reliable) so the history row is findable by name; the UI
    // rename path is exercised by the critical-path test, not here.
    const named = await page.request.patch(`/api/v2/projects/${projectId}`, {
      data: { name: "History Probe Model" },
    });
    await expect(named, `rename failed: ${named.status()}`).toBeOK();

    await page.goto(`/studio/${projectId}/solve`);
    const solveBtn = page.getByTestId("studio-solve-run");
    await expect(solveBtn).toBeEnabled({ timeout: NAV });
    await solveBtn.click();
    await expect(page.getByTestId("studio-solve-done")).toBeVisible({ timeout: 40_000 });

    await page.goto("/solve/executions");
    const row = page.locator("tbody tr").filter({ hasText: "History Probe Model" }).first();
    await expect(row).toBeVisible({ timeout: NAV });
    // #A — terminal row written by the worker on success, not a 'pending' zombie.
    await expect(row).not.toContainText(/pendiente|pending/i);
    // #B — tagged as a studio model, not the generic "Editor visual".
    await expect(row).toContainText(/estudio|studio/i);
  });
});
