/**
 * Captures the AI assistant (LLM) running a real conversation, for the landing
 * "AI Builder" section. Logs in, opens the assistant, sends a realistic problem,
 * waits for the streamed formulation, and screenshots the split-pane (chat +
 * formulation) in light and dark. Output: frontend/public/home/ai-assistant-{light,dark}.png
 *
 * Requires a working LLM (ANTHROPIC_API_KEY configured in platform_settings) and
 * an org with ai_builder_enabled.
 */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const BASE = process.env.SHOT_BASE_URL || "http://localhost:3001";
const EMAIL = process.env.SHOT_EMAIL || "shotbot@example.com";
const PASSWORD = process.env.SHOT_PASSWORD || "ShotBotCapture2026";
const OUT = path.resolve("public/home");

const PROMPT =
  "I run a small bakery. Each day I can bake at most 60 batches in total, " +
  "split between cakes and breads. A cake uses 3 units of oven time and earns " +
  "€12 profit; a bread uses 1 unit and earns €4. I have 100 units of oven time " +
  "per day. How many cakes and breads should I bake each day to maximize profit?";

async function run() {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  await context.addInitScript((key) => {
    try {
      localStorage.setItem(
        key,
        JSON.stringify({ essential: true, analytics: true, timestamp: new Date().toISOString() }),
      );
    } catch {
      /* ignore */
    }
  }, "jaot_cookie_consent");

  const login = await context.request.post(`${BASE}/api/v2/auth/login/email`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  if (!login.ok()) throw new Error(`login failed: HTTP ${login.status()}`);

  const page = await context.newPage();
  await page.goto(`${BASE}/builder/ai-assistant`, { waitUntil: "domcontentloaded" });
  await page.waitForURL(/\/builder\/.+\/chat/, { timeout: 40000 });

  const textarea = page.locator("textarea").first();
  await textarea.waitFor({ state: "visible", timeout: 40000 });
  await page.waitForTimeout(1200); // hydration + conversation init

  await textarea.click();
  await textarea.fill(PROMPT);
  if ((await textarea.inputValue()).trim().length < 10) {
    await textarea.pressSequentially(PROMPT, { delay: 8 });
  }
  await textarea.press("Enter");
  console.log("message sent, waiting for formulation...");

  // Formulation tabs (Visual/Text/Math) appear only once the model is ready.
  await page.waitForSelector('[role="tab"]', { timeout: 150000 });
  await page.waitForTimeout(3000); // let math/visual render + streaming settle
  await page.mouse.move(8, 8); // drop any hover tooltip
  await page.waitForTimeout(400);

  await page.screenshot({ path: path.join(OUT, "ai-assistant-light.png"), fullPage: false });

  await page.evaluate(() => {
    try {
      localStorage.setItem("jaot_theme", "dark");
    } catch {
      /* ignore */
    }
    document.documentElement.classList.add("dark");
    document.documentElement.style.colorScheme = "dark";
  });
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(OUT, "ai-assistant-dark.png"), fullPage: false });

  await browser.close();
  console.log("OK saved ai-assistant shots");
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
