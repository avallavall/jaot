// Manual walkthrough for Phase 7 UI. Runs headed, slow, so the user can watch.
// node e2e/walkthrough.mjs
import { chromium } from "playwright";

const BASE = "http://localhost:3000";
const SLOW = 600; // per-action delay

const ADMIN = { email: "admin@jaot.io", password: "AdminPass123!", label: "ADMIN (is_admin=true → isOwner)" };
const USER = { email: "user@jaot.io", password: "DemoPass123!", label: "USER (member — not isOwner)" };

async function banner(page, text) {
  // Inject a sticky banner so the user knows what's happening.
  await page.evaluate((msg) => {
    let div = document.getElementById("__walkthrough_banner");
    if (!div) {
      div = document.createElement("div");
      div.id = "__walkthrough_banner";
      div.style.cssText =
        "position:fixed;top:0;left:0;right:0;z-index:999999;background:#111;color:#fff;padding:12px 16px;font:600 14px system-ui;box-shadow:0 2px 8px rgba(0,0,0,.3);text-align:center;letter-spacing:.5px;";
      document.body.appendChild(div);
    }
    div.textContent = msg;
  }, text);
}

async function pause(page, ms) {
  await page.waitForTimeout(ms);
}

async function login(page, creds) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await banner(page, `Logging in as ${creds.label}`);
  await pause(page, 1500);
  const emailInput = page.locator('input[type="email"], input[name="email"], input[placeholder*="@"]').first();
  const passInput = page.locator('input[type="password"], input[name="password"]').first();
  await emailInput.waitFor({ state: "visible", timeout: 30000 });
  await emailInput.fill(creds.email);
  await passInput.fill(creds.password);
  const submitBtn = page
    .locator('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
    .first();
  await submitBtn.waitFor({ state: "visible", timeout: 15000 });
  await submitBtn.click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 30000 });
}

async function logout(page) {
  await page.goto(`${BASE}/api/v2/auth/logout`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await page.context().clearCookies();
}

async function tour(page, creds) {
  await login(page, creds);

  // --- /settings/solvers --------------------------------------------------
  await page.goto(`${BASE}/en/settings/solvers`, { waitUntil: "networkidle" });
  await banner(
    page,
    `${creds.label} — /settings/solvers | SolverLicensesTable + Upload/Delete gating by isOwner`,
  );
  await pause(page, 4000);

  // Try the Configure / Upload dialog
  const configureBtn = page.getByRole("button", { name: /configure/i }).first();
  if ((await configureBtn.count()) > 0 && (await configureBtn.isEnabled())) {
    await banner(page, `${creds.label} — opening UploadLicenseDialog (no real .lic, just UI tour)`);
    await configureBtn.click().catch(() => {});
    await pause(page, 3500);
    // Close with Escape if a dialog is present
    await page.keyboard.press("Escape").catch(() => {});
    await pause(page, 800);
  } else {
    await banner(page, `${creds.label} — Configure is disabled (not isOwner) → banner explains why`);
    await pause(page, 3500);
  }

  // --- /solve --------------------------------------------------------------
  await page.goto(`${BASE}/en/solve`, { waitUntil: "networkidle" });
  await banner(
    page,
    `${creds.label} — /solve | SolverSelect with "Auto" default + AutoRouteBadge on result`,
  );
  await pause(page, 3500);

  // Try to open the SolverSelect dropdown to showcase "Auto" + others
  const select = page
    .getByRole("combobox")
    .or(page.locator('[data-slot="select-trigger"]'))
    .first();
  if ((await select.count()) > 0) {
    await select.click().catch(() => {});
    await banner(page, `${creds.label} — SolverSelect opened: Auto / SCIP / HiGHS / Hexaly`);
    await pause(page, 3500);
    await page.keyboard.press("Escape").catch(() => {});
    await pause(page, 600);
  }

  // --- Sidebar link check --------------------------------------------------
  const sidebar = page.locator("aside, nav");
  const solversLink = sidebar.getByRole("link", { name: /solver/i }).first();
  if ((await solversLink.count()) > 0) {
    await banner(page, `${creds.label} — Sidebar now includes "Solver licenses" link`);
    await pause(page, 2500);
  }

  await banner(page, `${creds.label} — done`);
  await pause(page, 1200);

  await logout(page);
}

(async () => {
  const browser = await chromium.launch({ headless: false, slowMo: SLOW });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  try {
    console.log("Starting Phase 7 walkthrough (admin → user).");
    await tour(page, ADMIN);
    await tour(page, USER);
    console.log("Walkthrough complete. Leaving browser open for 20 seconds.");
    await pause(page, 20000);
  } catch (err) {
    console.error("Walkthrough error:", err);
    await pause(page, 10000);
  } finally {
    await browser.close();
  }
})();
