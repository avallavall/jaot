/**
 * End-to-end demo of the solution explainer + sensitivity analysis (P1).
 *
 * Solves a small LP via the API (so sensitivity has exact shadow prices and
 * reduced costs), opens the execution result page, and screenshots:
 *   - the Results tab with the "Explain this solution" panel,
 *   - the Sensitivity tab (shadow prices + variable reduced costs),
 *   - a mobile view of the result page,
 *   - and, best-effort, the streamed AI explanation (only when the LLM is
 *     configured with credits — otherwise that step is skipped, not failed).
 *
 * Output lands in docs/screenshots/solution-explainer/.
 *
 * Auth: relies on admin.setup.ts having produced
 * frontend/e2e/.auth/admin.json (admin@jaot.io / AdminPass123!).
 */
import { test, expect, devices } from "@playwright/test";
import path from "path";

const SHOTS = path.resolve(__dirname, "../../docs/screenshots/solution-explainer");
const ADMIN_AUTH = path.join(__dirname, ".auth/admin.json");
const API_BASE = process.env.BASE_URL || "http://localhost:3000";

// A small LP with two binding constraints, so shadow prices and reduced costs
// are non-trivial and exact (no integer variables → not approximate).
const LP_PROBLEM = {
  name: "Workshop profit (demo)",
  objective: { sense: "maximize", expression: "3*chairs + 2*tables" },
  variables: [
    { name: "chairs", type: "continuous", lower_bound: 0 },
    { name: "tables", type: "continuous", lower_bound: 0 },
  ],
  constraints: [
    { name: "assembly", expression: "chairs + tables <= 4" },
    { name: "finishing", expression: "2*chairs + tables <= 5" },
  ],
};

test.describe.configure({ mode: "serial" });
test.use({ storageState: ADMIN_AUTH });

async function solveDemo(
  request: import("@playwright/test").APIRequestContext,
): Promise<string> {
  const res = await request.post(`${API_BASE}/api/v2/solve`, { data: LP_PROBLEM });
  if (!res.ok()) {
    throw new Error(`Demo solve failed: ${res.status()} ${await res.text()}`);
  }
  const body = await res.json();
  const executionId = body.execution_id as string | undefined;
  if (!executionId) {
    throw new Error(`Demo solve returned no execution_id: ${JSON.stringify(body)}`);
  }
  return executionId;
}

test("01 — Results tab with the Explain panel + sensitivity table", async ({ page, request }) => {
  const executionId = await solveDemo(request);
  await page.goto(`/en/solve/executions/${executionId}`);
  await page.waitForLoadState("networkidle");

  // The explain panel button should be present for a solved execution.
  await expect(page.getByRole("button", { name: /explain this solution/i })).toBeVisible({
    timeout: 15_000,
  });
  await page.screenshot({
    path: path.join(SHOTS, "01-results-explain-panel-desktop.png"),
    fullPage: true,
  });
});

test("02 — Sensitivity tab: shadow prices + variable reduced costs", async ({ page, request }) => {
  const executionId = await solveDemo(request);
  await page.goto(`/en/solve/executions/${executionId}`);
  await page.waitForLoadState("networkidle");

  await page.getByRole("tab", { name: /sensitivity/i }).click();
  // Wait for the constraint sensitivity details to render.
  await expect(page.getByText(/Constraint Sensitivity Details|Shadow Prices/i).first()).toBeVisible({
    timeout: 15_000,
  });
  await page.screenshot({
    path: path.join(SHOTS, "02-sensitivity-tab-desktop.png"),
    fullPage: true,
  });
});

test("03 — AI explanation (best-effort, skipped when LLM unavailable)", async ({ page, request }) => {
  const executionId = await solveDemo(request);
  await page.goto(`/en/solve/executions/${executionId}`);
  await page.waitForLoadState("networkidle");

  await page.getByRole("button", { name: /explain this solution/i }).click();

  // Wait for streamed text OR an error/regenerate state. If the model is not
  // configured (no credits / no key), don't fail the suite — just skip the shot.
  const grounded = page.getByText(/Generated from your actual solution/i);
  try {
    await grounded.waitFor({ timeout: 30_000 });
  } catch {
    test.skip(true, "LLM not configured in this environment — explanation not generated");
    return;
  }
  await page.screenshot({
    path: path.join(SHOTS, "03-ai-explanation-desktop.png"),
    fullPage: true,
  });
});

test("04 — Mobile result page", async ({ browser, request }) => {
  const executionId = await solveDemo(request);
  const context = await browser.newContext({
    ...devices["iPhone 14"],
    storageState: ADMIN_AUTH,
  });
  const page = await context.newPage();
  await page.goto(`/en/solve/executions/${executionId}`);
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("button", { name: /explain this solution/i })).toBeVisible({
    timeout: 15_000,
  });
  await page.screenshot({
    path: path.join(SHOTS, "04-results-explain-panel-mobile.png"),
    fullPage: true,
  });
  await context.close();
});
