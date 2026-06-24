/**
 * Global setup: authenticates once and saves storageState for all test projects.
 *
 * Uses email/password authentication (v2.0 login flow).
 * Configure via E2E_EMAIL / E2E_PASSWORD env vars, or defaults to dev seed user.
 */
import { test as setup, expect } from "@playwright/test";
import path from "path";
import fs from "fs";

const authFile = path.join(__dirname, ".auth/user.json");

/**
 * Dismiss the WelcomeWizard via the guidance API so its overlay
 * does not block pointer events during E2E tests.
 */
async function dismissWizard(
  page: import("@playwright/test").Page,
): Promise<void> {
  const baseURL =
    process.env.BASE_URL || "http://localhost:3000";
  try {
    const resp = await page.request.patch(`${baseURL}/api/v2/guidance`, {
      data: { wizard_dismissed: true },
    });
    if (!resp.ok()) {
      console.warn(`[setup] Could not dismiss wizard: ${resp.status()}`);
    }
  } catch {
    // Non-critical: endpoint may not exist yet
  }
}

setup("authenticate", async ({ page }) => {
  // If auth file exists and cookies are still valid, verify they work before reusing.
  // This prevents stale cookies after a DB reseed from causing 401s in all tests.
  if (fs.existsSync(authFile)) {
    try {
      const state = JSON.parse(fs.readFileSync(authFile, "utf-8"));
      const now = Date.now() / 1000;
      const accessCookie = state.cookies?.find(
        (c: { name: string; expires: number }) =>
          c.name === "jaot_access_token" && c.expires > now,
      );
      if (accessCookie) {
        await page.context().addCookies(state.cookies);
        // Verify the cookie is actually valid against the current DB
        const baseURL = process.env.BASE_URL || "http://localhost:3000";
        try {
          const resp = await page.request.get(`${baseURL}/api/v2/auth/me`);
          if (resp.ok()) {
            await dismissWizard(page);
            return;
          }
        } catch {
          // API unreachable or cookie invalid — fall through to re-auth
        }
      }
    } catch {
      // Corrupted file, re-authenticate
    }
  }

  const email = process.env.E2E_EMAIL || "user@jaot.io";
  const password = process.env.E2E_PASSWORD || "DemoPass123!";

  // Retry login page navigation in case the dev server is still compiling
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");
    const bodyText = await page.textContent("body");
    if (bodyText && !bodyText.includes("Internal Server Error")) break;
    if (attempt < 4) {
      await page.waitForTimeout(2000 * (attempt + 1));
    }
  }

  // Authenticate via API first to get session cookie, then load the page.
  // This avoids issues with cookie consent banners blocking the login form.
  const baseURL = process.env.BASE_URL || "http://localhost:3000";
  const loginResp = await page.request.post(`${baseURL}/api/v2/auth/login/email`, {
    data: { email, password },
  });

  if (loginResp.ok()) {
    // API login sets HttpOnly cookies on the response — load any page to activate them
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");
  } else {
    // Fallback: try browser-based login
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    // Dismiss cookie consent banner if present
    const cookieBtn = page.locator("button").filter({ hasText: /accept all/i }).first();
    if (await cookieBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await cookieBtn.click({ force: true });
      await page.waitForTimeout(500);
    }

    await page.locator("#email").fill(email);
    await page.locator("#password").fill(password);
    await page.locator("button").filter({ hasText: /log in/i }).click();
    await expect(page).not.toHaveURL(/\/login/, { timeout: 10_000 });
  }

  // Dismiss WelcomeWizard overlay so it does not block E2E clicks
  await dismissWizard(page);

  // Save signed-in state
  await page.context().storageState({ path: authFile });
});
