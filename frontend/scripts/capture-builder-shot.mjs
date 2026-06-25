/**
 * Captures a real screenshot of the visual model builder (XYFlow node editor)
 * for the landing-page hero, in both light and dark themes.
 *
 * It logs in, imports a representative optimization model via the builder's
 * "Import JSON" flow (no seeded catalog needed), fits the canvas, and screenshots
 * the `.react-flow` element. Output: frontend/public/home/builder-{light,dark}.png
 *
 * Usage (from frontend/):
 *   SHOT_BASE_URL=http://localhost:3001 \
 *   SHOT_EMAIL=shotbot@example.com SHOT_PASSWORD=ShotBotCapture2026 \
 *   node scripts/capture-builder-shot.mjs
 *
 * Requires the Playwright chromium browser (npx playwright install chromium).
 */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const BASE = process.env.SHOT_BASE_URL || "http://localhost:3001";
const EMAIL = process.env.SHOT_EMAIL || "shotbot@example.com";
const PASSWORD = process.env.SHOT_PASSWORD || "ShotBotCapture2026";
const OUT = path.resolve("public/home");

// A small but visually rich model: 5 variables (continuous/integer/binary →
// three badge colors), an objective, and 4 constraints → many colored nodes/edges.
const MODEL = {
  variables: [
    { name: "premium", type: "continuous", lower_bound: 0, upper_bound: 40 },
    { name: "standard", type: "continuous", lower_bound: 0, upper_bound: 30 },
    { name: "batches", type: "integer", lower_bound: 0, upper_bound: 20 },
    { name: "open_line_a", type: "binary" },
    { name: "open_line_b", type: "binary" },
  ],
  objective: {
    sense: "maximize",
    expression:
      "12*premium + 9*standard + 15*batches + 50*open_line_a + 30*open_line_b",
  },
  constraints: [
    { name: "capacity", expression: "premium + standard + batches <= 60" },
    { name: "labor", expression: "2*premium + standard <= 50" },
    { name: "setup_a", expression: "batches + 5*open_line_a <= 25" },
    { name: "demand", expression: "premium + standard + 4*open_line_b >= 20" },
  ],
};

async function run() {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
    deviceScaleFactor: 2,
  });

  // Pre-accept cookie consent so the banner never mounts over the canvas.
  await context.addInitScript((key) => {
    try {
      localStorage.setItem(
        key,
        JSON.stringify({
          essential: true,
          analytics: true,
          timestamp: new Date().toISOString(),
        }),
      );
    } catch {
      /* ignore */
    }
  }, "jaot_cookie_consent");
  // 1) Authenticate via the API so the session cookie lands in the context
  //    (avoids the flaky UI-form hydration race).
  const login = await context.request.post(`${BASE}/api/v2/auth/login/email`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  if (!login.ok()) {
    throw new Error(`login failed: HTTP ${login.status()}`);
  }

  const page = await context.newPage();

  // 2) Open the builder and import the model (client-side, no save needed).
  await page.goto(`${BASE}/builder`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="file"]', {
    state: "attached",
    timeout: 30000,
  });
  await page.setInputFiles('input[type="file"]', {
    name: "demo-model.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(MODEL)),
  });

  // 3) Wait for the canvas + nodes to render and the auto-layout to settle.
  await page.waitForURL(/\/builder\/new/, { timeout: 30000 });
  await page.waitForSelector(".react-flow__node", { timeout: 30000 });
  await page.waitForTimeout(1500); // let onboarding wizard / tour mount

  // Dismiss the onboarding wizard, guided tour, and cookie banner that cover
  // the canvas on first builder use. These are custom (not Escape-closeable),
  // so click their specific controls; each is best-effort.
  const tryClick = async (locator) => {
    try {
      await locator.first().click({ timeout: 1500 });
      return true;
    } catch {
      return false;
    }
  };
  await tryClick(page.getByText(/skip wizard/i)); // skill-level wizard
  await page.waitForTimeout(400);
  await tryClick(page.getByRole("button", { name: /accept all/i })); // cookies
  await page.waitForTimeout(300);
  await tryClick(page.getByRole("button", { name: /^skip$/i })); // guided tour
  await page.waitForTimeout(300);
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(200);
  }
  await page.waitForTimeout(600);

  // Fit the graph into view if the control is present (best-effort).
  const fit = await page.$(".react-flow__controls-fitview");
  if (fit) {
    await fit.click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(800);
  }

  const canvas = await page.$(".react-flow");
  if (!canvas) throw new Error("react-flow canvas not found");
  const box = await canvas.boundingBox();
  console.log("CANVAS_BOX " + JSON.stringify(box));
  const nodeCount = await page.locator(".react-flow__node").count();
  console.log("NODE_COUNT " + nodeCount);

  // 4) Light capture.
  await canvas.screenshot({ path: path.join(OUT, "builder-light.png") });

  // 5) Flip to dark (CSS variables recolor instantly — no React state needed for
  //    the static shot) and capture again.
  await page.evaluate(() => {
    try {
      localStorage.setItem("jaot_theme", "dark");
    } catch {
      /* ignore */
    }
    document.documentElement.classList.add("dark");
    document.documentElement.style.colorScheme = "dark";
  });
  await page.waitForTimeout(700);
  await canvas.screenshot({ path: path.join(OUT, "builder-dark.png") });

  await browser.close();
  console.log("OK saved to " + OUT);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
