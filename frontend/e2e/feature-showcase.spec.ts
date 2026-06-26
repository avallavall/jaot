/**
 * Marketing showcase screenshots for the home page: the P1 solution explainer and
 * the P2 infeasibility explainer, each captured in BOTH light and dark themes.
 *
 * Cropped to the explainer panel itself (not full-page) for a clean hero image.
 * Output lands in frontend/public/showcase/ so the home page can <Image> them, and
 * full-page P2 shots also land in docs/screenshots/infeasibility/.
 *
 * The AI explanation requires a configured Anthropic key (platform or org BYOK). If
 * the stream never completes (no key / no credits), the AI shots are skipped, not
 * failed — the panel/IIS shots still capture.
 *
 * Auth: relies on admin.setup.ts → frontend/e2e/.auth/admin.json (admin@jaot.io).
 * Run against the prod Docker build: CI=1 BASE_URL=http://localhost:3002 npx playwright test feature-showcase --project=admin-setup --project=admin
 */
import { test, expect, type Page } from "@playwright/test";
import path from "path";

const SHOWCASE = path.resolve(__dirname, "../public/showcase");
const DOCS_SHOTS = path.resolve(__dirname, "../../docs/screenshots/infeasibility");
const ADMIN_AUTH = path.join(__dirname, ".auth/admin.json");
const API_BASE = process.env.BASE_URL || "http://localhost:3000";

// P1: a small LP with two binding constraints — exact shadow prices + reduced costs.
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

// P2: the factory model — a hard order minimum that exceeds machine capacity.
const INFEASIBLE_PROBLEM = {
  name: "Factory order (demo)",
  objective: { sense: "maximize", expression: "piezas_producidas" },
  variables: [{ name: "piezas_producidas", type: "continuous", lower_bound: 0 }],
  constraints: [
    { name: "pedido_minimo", expression: "piezas_producidas >= 500" },
    { name: "capacidad_maquina", expression: "piezas_producidas <= 300" },
    { name: "limite_material", expression: "2*piezas_producidas <= 2000" },
  ],
};

test.describe.configure({ mode: "serial" });
test.use({ storageState: ADMIN_AUTH });

const solved: Record<string, string> = {};

async function solve(
  request: import("@playwright/test").APIRequestContext,
  key: string,
  problem: object,
): Promise<string> {
  if (solved[key]) return solved[key];
  const res = await request.post(`${API_BASE}/api/v2/solve`, { data: problem });
  if (!res.ok()) throw new Error(`Solve ${key} failed: ${res.status()} ${await res.text()}`);
  const body = await res.json();
  const id = body.execution_id as string | undefined;
  if (!id) throw new Error(`Solve ${key} returned no execution_id: ${JSON.stringify(body)}`);
  solved[key] = id;
  return id;
}

async function setTheme(page: Page, theme: "light" | "dark") {
  // next-themes (attribute="class") reads the "theme" key from localStorage on load.
  // Also pre-seed cookie consent so the consent banner never overlaps the shot.
  await page.addInitScript((t) => {
    window.localStorage.setItem("theme", t);
    window.localStorage.setItem(
      "jaot_cookie_consent",
      JSON.stringify({ essential: true, analytics: false, timestamp: "2026-06-26T00:00:00.000Z" }),
    );
  }, theme);
  await page.emulateMedia({ colorScheme: theme });
}

async function dismissCookies(page: Page) {
  const accept = page.getByRole("button", { name: /accept all/i });
  if (await accept.isVisible().catch(() => false)) {
    await accept.click().catch(() => {});
    await accept.waitFor({ state: "hidden", timeout: 5000 }).catch(() => {});
  }
}

function panel(page: Page, headingRe: RegExp) {
  return page
    .locator("div.rounded-lg")
    .filter({ has: page.getByRole("heading", { name: headingRe }) })
    .first();
}

// ---- P1: solution explainer ----

for (const theme of ["light", "dark"] as const) {
  test(`P1 explainer — ${theme}`, async ({ browser, request }) => {
    test.setTimeout(90_000);
    const id = await solve(request, "p1", LP_PROBLEM);
    const context = await browser.newContext({ storageState: ADMIN_AUTH });
    const page = await context.newPage();
    await setTheme(page, theme);
    await page.goto(`/en/solve/executions/${id}`, { waitUntil: "domcontentloaded" });
    await dismissCookies(page);

    const explainBtn = page.getByRole("button", { name: /explain this solution/i });
    await expect(explainBtn).toBeVisible({ timeout: 20_000 });
    await explainBtn.click();

    const done = page.getByText(/Generated from your actual solution/i);
    const ok = await done.waitFor({ timeout: 60_000 }).then(() => true).catch(() => false);
    if (!ok) {
      await context.close();
      test.skip(true, "LLM not configured — P1 explanation not generated");
      return;
    }
    await panel(page, /explain this solution/i).screenshot({
      path: path.join(SHOWCASE, `p1-explainer-${theme}.png`),
    });
    await context.close();
  });
}

// ---- P2: infeasibility explainer ----

for (const theme of ["light", "dark"] as const) {
  test(`P2 infeasibility — ${theme}`, async ({ browser, request }) => {
    test.setTimeout(90_000);
    const id = await solve(request, "p2", INFEASIBLE_PROBLEM);
    const context = await browser.newContext({ storageState: ADMIN_AUTH });
    const page = await context.newPage();
    await setTheme(page, theme);
    await page.goto(`/en/solve/executions/${id}`, { waitUntil: "domcontentloaded" });
    await dismissCookies(page);

    const fixBtn = page.getByRole("button", { name: /explain why .* fix/i });
    await expect(fixBtn).toBeVisible({ timeout: 20_000 });
    await fixBtn.click();

    // The IIS chips render as soon as the analysis returns.
    await expect(page.getByText("These requirements conflict")).toBeVisible({ timeout: 30_000 });

    const done = page.getByText(/Generated from your model's actual conflicting constraints/i);
    const ok = await done.waitFor({ timeout: 60_000 }).then(() => true).catch(() => false);

    await panel(page, /why is this infeasible/i).screenshot({
      path: path.join(SHOWCASE, `p2-infeasibility-${theme}.png`),
    });
    // Full-page P2 shot for the docs (DoD), light theme only is enough there.
    if (theme === "light") {
      await page.screenshot({
        path: path.join(DOCS_SHOTS, "01-infeasibility-panel-desktop.png"),
        fullPage: true,
      });
    }
    if (!ok) test.info().annotations.push({ type: "note", description: "AI text not streamed" });
    await context.close();
  });
}
