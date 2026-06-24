/**
 * Admin setup: authenticates as admin and saves storageState for admin test projects.
 *
 * Uses admin email/password authentication.
 * Configure via E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD env vars, or defaults to dev seed admin.
 */
import { test as setup, expect } from "@playwright/test";
import path from "path";

const adminAuthFile = path.join(__dirname, ".auth/admin.json");

setup("authenticate as admin", async ({ page }) => {
  const email = process.env.E2E_ADMIN_EMAIL || "admin@jaot.io";
  const password = process.env.E2E_ADMIN_PASSWORD || "AdminPass123!";

  await page.goto("/login");

  // Fill email/password login form
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(password);
  await page
    .getByRole("button", { name: /log\s*in|sign\s*in|submit/i })
    .click();

  // Wait for redirect away from login page (indicates successful auth)
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });

  // Dismiss the WelcomeWizard so its overlay does not block E2E clicks.
  const baseURL = page.url().replace(/\/[^/]*$/, "");
  try {
    const resp = await page.request.patch(`${baseURL}/api/v2/guidance`, {
      data: { wizard_dismissed: true },
    });
    if (!resp.ok()) {
      console.warn(`[admin-setup] Could not dismiss wizard: ${resp.status()}`);
    }
  } catch {
    // Non-critical: endpoint may not exist yet
  }

  // Save signed-in state
  await page.context().storageState({ path: adminAuthFile });
});
