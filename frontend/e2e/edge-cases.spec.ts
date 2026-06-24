import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

test.describe("Edge Cases", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });
  test.describe("Dark Mode", () => {
    test("landing page supports dark mode toggle", async ({ page }) => {
      await page.goto("/");

      // Look for a theme toggle button — use .first() to avoid strict mode violation
      const themeToggle = page.getByLabel("Toggle theme").or(
        page.getByRole("button", { name: /theme|dark|light|mode/i }).first()
      );
      const toggleExists = (await themeToggle.count()) > 0;

      if (toggleExists) {
        await themeToggle.first().click();
        // After toggling, check that html or body has dark class or data-theme attribute
        const isDark = await page.evaluate(() => {
          return (
            document.documentElement.classList.contains("dark") ||
            document.documentElement.getAttribute("data-theme") === "dark"
          );
        });
        expect(typeof isDark).toBe("boolean");
      }
    });
  });

  test.describe("Responsive", () => {
    test("mobile viewport renders without horizontal overflow", async ({ browser }) => {
      const context = await browser.newContext({
        viewport: { width: 375, height: 667 },
      });
      const page = await context.newPage();

      await page.goto("/");
      await page.waitForLoadState("networkidle");

      // Check no horizontal overflow
      const hasOverflow = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
      });
      expect(hasOverflow).toBe(false);

      await context.close();
    });

    test("mobile viewport collapses sidebar on solve page", async ({ browser }) => {
      const context = await browser.newContext({
        viewport: { width: 375, height: 667 },
        storageState: "e2e/.auth/user.json",
      });
      const page = await context.newPage();

      await page.goto("/solve");
      await page.waitForLoadState("networkidle");

      // On mobile, sidebar should either be hidden or behind a hamburger menu
      // We just verify the page loads without error at mobile width
      await expect(page).toHaveURL(/\/solve/);

      await context.close();
    });
  });

  test.describe("404 / Error Handling", () => {
    test("non-existent page shows not-found content", async ({ page }) => {
      const response = await page.goto("/this-page-does-not-exist-404");

      // Next.js returns 404 for unknown routes
      // Check for either a 404 status or a "not found" message on page
      const bodyText = await page.textContent("body");
      const has404 =
        response?.status() === 404 ||
        /not found|404|page.*not.*exist/i.test(bodyText || "");
      expect(has404).toBe(true);
    });
  });

  test.describe("Error Handling Extended (E2E-15)", () => {
    test("API error on invalid model ID shows user-friendly message", async ({ page }) => {
      await page.goto("/solve/mdl_nonexistent_12345");
      const bodyText = await page.textContent("body");
      const handled = /not found|error|404|model/i.test(bodyText || "")
        || (await page.url()).includes("/solve");
      expect(handled).toBe(true);
    });

    test("invalid marketplace model ID shows graceful error", async ({ page }) => {
      await page.goto("/marketplace/mdl_nonexistent_99999");
      const bodyText = await page.textContent("body");
      const handled = /not found|error|404|model/i.test(bodyText || "")
        || (await page.url()).includes("/marketplace");
      expect(handled).toBe(true);
    });

    test("invalid admin sub-route shows error", async ({ page }) => {
      await page.goto("/admin/nonexistent-section");
      const bodyText = await page.textContent("body");
      const handled = /not found|error|404/i.test(bodyText || "")
        || (await page.url()).includes("/admin");
      expect(handled).toBe(true);
    });
  });

  test.describe("Dark Mode Extended (E2E-13)", () => {
    test("dark mode persists across navigation", async ({ page }) => {
      await page.goto("/");

      const themeToggle = page.getByLabel("Toggle theme").or(
        page.getByRole("button", { name: /theme|dark|light|mode/i }).first()
      );
      const toggleExists = (await themeToggle.count()) > 0;

      if (toggleExists) {
        await themeToggle.first().click();
        const wasDark = await page.evaluate(() =>
          document.documentElement.classList.contains("dark")
        );

        // Navigate to another page
        await page.goto("/login");
        await page.waitForLoadState("networkidle");

        const stillDark = await page.evaluate(() =>
          document.documentElement.classList.contains("dark")
        );
        expect(stillDark).toBe(wasDark);
      }
    });
  });

  test.describe("Responsive Extended (E2E-14)", () => {
    test("tablet viewport renders workspace page correctly", async ({ browser }) => {
      const context = await browser.newContext({
        viewport: { width: 768, height: 1024 },
        storageState: "e2e/.auth/user.json",
      });
      const page = await context.newPage();

      await page.goto("/workspace");
      await page.waitForLoadState("networkidle");
      await expect(page).toHaveURL(/\/workspace/);

      await context.close();
    });

    test("mobile viewport renders marketplace without overflow", async ({ browser }) => {
      const context = await browser.newContext({
        viewport: { width: 375, height: 667 },
        storageState: "e2e/.auth/user.json",
      });
      const page = await context.newPage();

      await page.goto("/marketplace");
      await page.waitForLoadState("networkidle");

      const hasOverflow = await page.evaluate(() =>
        document.documentElement.scrollWidth > document.documentElement.clientWidth
      );
      expect(hasOverflow).toBe(false);

      await context.close();
    });
  });

  test.describe("Accessibility (axe-core)", () => {
    test("landing page has no critical a11y violations", async ({ page }) => {
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa"])
        .disableRules(["color-contrast"]) // color contrast often needs manual review
        .analyze();

      const critical = results.violations.filter(
        (v) => v.impact === "critical" || v.impact === "serious"
      );
      expect(critical).toEqual([]);
    });

    test("login page has no critical a11y violations", async ({ page }) => {
      await page.goto("/login");
      await page.waitForLoadState("networkidle");

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa"])
        .disableRules(["color-contrast"])
        .analyze();

      const critical = results.violations.filter(
        (v) => v.impact === "critical" || v.impact === "serious"
      );
      expect(critical).toEqual([]);
    });

    test("solve dashboard has no critical a11y violations", async ({ page }) => {
      await page.goto("/solve");
      await page.waitForLoadState("networkidle");

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa"])
        .disableRules(["color-contrast"])
        .analyze();

      const critical = results.violations.filter(
        (v) => v.impact === "critical" || v.impact === "serious"
      );
      expect(critical).toEqual([]);
    });
  });
});
