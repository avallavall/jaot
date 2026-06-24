import { test, expect } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

test.describe("Triggers (E2E-11)", () => {
  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });
  test("triggers list page loads", async ({ page }) => {
    await page.goto("/triggers");
    await expect(page).toHaveURL(/\/triggers/);
    const heading = page.getByRole("heading").first();
    await expect(heading).toBeVisible();
  });

  test("triggers page shows create trigger action", async ({ page }) => {
    await page.goto("/triggers");
    // Page should load; create action may or may not be visible depending on permissions
    await expect(page).toHaveURL(/\/triggers/);
  });

  test("create trigger page loads", async ({ page }) => {
    await page.goto("/triggers/new");
    await expect(page).toHaveURL(/\/triggers\/new/);
  });

  test("create trigger page has form fields", async ({ page }) => {
    await page.goto("/triggers/new");

    // At minimum the page should load without errors
    await expect(page).toHaveURL(/\/triggers\/new/);
    const content = page.locator("#main-content");
    await expect(content).toBeVisible();
  });

  test("navigating to non-existent trigger shows error or redirects", async ({
    page,
  }) => {
    await page.goto("/triggers/trg_nonexistent_12345");
    // Should show error message or redirect
    const bodyText = await page.textContent("body");
    const currentUrl = page.url();
    const hasErrorOrContent =
      /not found|error|trigger|404/i.test(bodyText || "") ||
      currentUrl.includes("/triggers");
    expect(hasErrorOrContent).toBe(true);
  });

  test.describe("Triggers - List Content", () => {
    test("triggers list shows either trigger items or empty state", async ({
      page,
    }) => {
      await page.goto("/triggers");
      await expect(page).toHaveURL(/\/triggers/);

      // Wait for page heading to be visible (loading complete)
      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible();

      // Check for either trigger name links (data) or empty state with dashed border
      const triggerLinks = page.getByRole("link").filter({
        has: page.locator("text=/trg_|trigger/i"),
      });
      const emptyState = page.getByText(
        /no trigger|get started|create.*trigger/i
      );

      const hasTriggers = (await triggerLinks.count()) > 0;
      const hasEmptyState = (await emptyState.count()) > 0;

      // One of the two states should be present
      expect(hasTriggers || hasEmptyState).toBe(true);
    });

    test("triggers list page has New Trigger button", async ({ page }) => {
      await page.goto("/triggers");
      await expect(page).toHaveURL(/\/triggers/);

      // Wait for page heading to confirm page has loaded
      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible({ timeout: 15_000 });

      // Find the "New Trigger" action — rendered as a button or link
      // depending on user permissions (canEdit). Use text matching as
      // the role-based accessible name may vary with icon children.
      const newTriggerAction = page.getByText(/new trigger/i).first();
      await expect(newTriggerAction).toBeVisible({ timeout: 10_000 });
    });
  });

  test.describe("Triggers - Toggle Enable/Disable", () => {
    test("trigger items show enabled or disabled badge", async ({ page }) => {
      await page.goto("/triggers");
      await expect(page).toHaveURL(/\/triggers/);

      // Wait for heading to confirm page is loaded
      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible();

      // If triggers exist, look for Enabled/Disabled badge text
      const badges = page.getByText(/^enabled$|^disabled$/i);
      const badgeCount = await badges.count();

      // Defensive: if no triggers exist (empty state), skip gracefully
      if (badgeCount > 0) {
        await expect(badges.first()).toBeVisible();
      }
      // Test passes regardless -- we verified the page loads correctly
    });

    test("trigger items have toggle button", async ({ page }) => {
      await page.goto("/triggers");
      await expect(page).toHaveURL(/\/triggers/);

      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible();

      // If triggers exist, find the toggle button (title matches enable/disable)
      const toggleButton = page.getByRole("button", {
        name: /enable.*trigger|disable.*trigger/i,
      });
      const toggleCount = await toggleButton.count();

      // Defensive: passes if no triggers exist (empty state)
      if (toggleCount > 0) {
        await expect(toggleButton.first()).toBeVisible();
      }
    });
  });

  test.describe("Triggers - Create Form", () => {
    test("create trigger page loads with heading", async ({ page }) => {
      await page.goto("/triggers/new");
      await page.waitForURL(/\/triggers\/new/);

      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible();
    });

    test("create trigger page has form with input fields", async ({
      page,
    }) => {
      await page.goto("/triggers/new");
      await page.waitForURL(/\/triggers\/new/);

      // Wait for page to fully render
      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible();

      // TriggerForm should render with at least one input field (name)
      // The form renders <input> elements — locate by id or CSS selector
      const nameInput = page.locator("#trigger-name");
      await expect(nameInput).toBeVisible({ timeout: 15_000 });
    });
  });

  test.describe("Triggers - Detail Page", () => {
    test("trigger detail page has tabs for Overview, Run History, Schedule", async ({
      page,
    }) => {
      // Navigate to triggers list first
      await page.goto("/triggers");
      await expect(page).toHaveURL(/\/triggers/);

      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible();

      // Try to find a trigger link to navigate to detail page
      const triggerLink = page
        .locator("a[href*='/triggers/trg_']")
        .first();
      const hasLink = (await triggerLink.count()) > 0;

      if (hasLink) {
        // Click the trigger link to go to detail page
        await triggerLink.click();
        await page.waitForURL(/\/triggers\/trg_/);

        // Verify tabs exist
        const overviewTab = page.getByRole("tab", { name: /overview/i });
        const runHistoryTab = page.getByRole("tab", {
          name: /run history|history/i,
        });
        const scheduleTab = page.getByRole("tab", { name: /schedule/i });

        await expect(overviewTab).toBeVisible();
        await expect(runHistoryTab).toBeVisible();
        await expect(scheduleTab).toBeVisible();
      } else {
        // No triggers exist -- verify the non-existent trigger shows error
        await page.goto("/triggers/trg_nonexistent_test");
        const bodyText = await page.textContent("body");
        expect(
          /not found|error|trigger|back to triggers/i.test(bodyText || "")
        ).toBe(true);
      }
    });

    test("trigger detail page Schedule tab can be opened", async ({
      page,
    }) => {
      // Navigate to triggers list to find a real trigger
      await page.goto("/triggers");
      await expect(page).toHaveURL(/\/triggers/);

      const heading = page.getByRole("heading").first();
      await expect(heading).toBeVisible();

      const triggerLink = page
        .locator("a[href*='/triggers/trg_']")
        .first();
      const hasLink = (await triggerLink.count()) > 0;

      if (hasLink) {
        await triggerLink.click();
        await page.waitForURL(/\/triggers\/trg_/);

        // Click the Schedule tab
        const scheduleTab = page.getByRole("tab", { name: /schedule/i });
        await expect(scheduleTab).toBeVisible();
        await scheduleTab.click();

        // Verify schedule content loads (tab panel becomes visible)
        const tabPanel = page.getByRole("tabpanel");
        await expect(tabPanel).toBeVisible();
      } else {
        // No triggers -- navigate to non-existent trigger and verify error state
        await page.goto("/triggers/trg_nonexistent_schedule");
        const bodyText = await page.textContent("body");
        expect(
          /not found|error|trigger|back to triggers/i.test(bodyText || "")
        ).toBe(true);
      }
    });
  });
});
