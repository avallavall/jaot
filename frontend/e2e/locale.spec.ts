import { test, expect } from "@playwright/test";

test.describe("Non-English Locale Routes (es)", () => {
  test("Spanish landing page loads", async ({ page }) => {
    await page.goto("/es");
    await expect(page).toHaveTitle(/JAOT/i);
  });

  test("Spanish login page is reachable", async ({ page }) => {
    await page.goto("/es/login");
    await expect(page).toHaveURL(/\/es\/login/);
  });

  test("Spanish marketplace page renders", async ({ page }) => {
    await page.goto("/es/marketplace");
    await expect(page).toHaveURL(/\/es\/marketplace/);
    await expect(page).toHaveTitle(/JAOT/i);
  });
});
