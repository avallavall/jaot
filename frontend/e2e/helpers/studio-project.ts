import { expect, type Page } from "@playwright/test";

/**
 * Shared studio-project fixtures for E2E specs: create a blank ModelProject from
 * the launcher and seed its draft with a trivially solvable LP through the
 * authenticated API. API-driven seeding avoids flaky ReactFlow drag-drop while
 * still exercising the real create→hydrate flow (the store hydrates the canonical
 * model from `serialize(draft_canvas_json)`, so the canvas is the load-time
 * source of truth and must be seeded alongside `model_json`).
 */

const NAV = 20_000;

/**
 * A trivial, always-feasible LP: minimize x s.t. x >= 8, x <= 10, x in [0, 23] → x* = 8.
 * Built in the exact node/edge shape `deserializeFromOptimizationProblem` produces, so
 * the store's `serialize(canvas)` hydration yields this model.
 */
export const SEED_CANVAS = {
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

export const SEED_MODEL = {
  name: "E2E Critical Path",
  variables: [{ name: "x", type: "continuous", lower_bound: 0, upper_bound: 23 }],
  objective: { sense: "minimize", expression: "x" },
  constraints: [
    { name: "c1", expression: "x >= 8" },
    { name: "c2", expression: "x <= 10" },
  ],
};

/** Create a fresh blank ModelProject from the launcher; returns its `mp_…` id. */
export async function createBlankProject(page: Page): Promise<string> {
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
export async function seedDraft(page: Page, projectId: string): Promise<void> {
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
