import { test, expect } from "@playwright/test";
import { LoginPage } from "./pages/login.page";

test.describe("Authentication", () => {
  test.describe("Login", () => {
    test("shows login form with email, password and submit button", async ({ browser }) => {
      // Explicitly clear storageState to override the project-level auth
      const context = await browser.newContext({ storageState: undefined });
      const page = await context.newPage();

      const loginPage = new LoginPage(page);
      await loginPage.goto();

      await expect(loginPage.title).toBeVisible();
      await expect(loginPage.emailInput).toBeVisible();
      await expect(loginPage.passwordInput).toBeVisible();
      await expect(loginPage.loginButton).toBeVisible();

      await context.close();
    });

    test("login with valid credentials redirects away from login", async ({ browser }) => {
      const context = await browser.newContext({ storageState: undefined });
      const page = await context.newPage();

      const loginPage = new LoginPage(page);
      await loginPage.goto();

      const email = process.env.E2E_EMAIL || "user@jaot.io";
      const password = process.env.E2E_PASSWORD || "DemoPass123!";
      await loginPage.login(email, password);
      await loginPage.expectRedirectAway();

      await context.close();
    });

    test("login with invalid credentials shows error message", async ({ browser }) => {
      const context = await browser.newContext({ storageState: undefined });
      const page = await context.newPage();

      const loginPage = new LoginPage(page);
      await loginPage.goto();

      await loginPage.login("invalid@example.com", "WrongPassword123!");
      await loginPage.expectError();

      await context.close();
    });
  });

  test.describe("Logout & Session (E2E-03)", () => {
    test("authenticated user can access dashboard then logout", async ({ page }) => {
      await page.goto("/solve");
      await expect(page).toHaveURL(/\/solve/);

      // Look for logout/sign-out button in navigation or user menu
      const userMenu = page
        .getByRole("button", { name: /user|account|profile|menu/i })
        .or(page.locator('[data-testid="user-menu"]'));
      await expect(userMenu.first()).toBeVisible({ timeout: 10_000 });

      await userMenu.first().click();
      const logoutButton = page.getByRole("menuitem", { name: /log\s?out|sign\s?out/i })
        .or(page.getByRole("button", { name: /log\s?out|sign\s?out/i }));
      await expect(logoutButton.first()).toBeVisible({ timeout: 5_000 });

      await logoutButton.first().click();
      // After logout, should redirect to login or landing
      await expect(page).toHaveURL(/\/(login)?$/, { timeout: 10_000 });
    });

    test("session persists across page navigation", async ({ page }) => {
      await page.goto("/solve");
      await expect(page).toHaveURL(/\/solve/);

      // Navigate to another authenticated page
      await page.goto("/workspace");
      await expect(page).toHaveURL(/\/workspace/);

      // Should still be authenticated (not redirected to login)
      await expect(page).not.toHaveURL(/\/login/);
    });
  });

  test.describe("Protected routes", () => {
    test("unauthenticated access to /solve redirects to login", async ({ browser }) => {
      // Explicitly clear storageState to override the project-level auth
      const context = await browser.newContext({ storageState: undefined });
      const page = await context.newPage();

      await page.goto("/solve");
      await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });

      await context.close();
    });

    test("unauthenticated access to /workspace redirects to login", async ({ browser }) => {
      const context = await browser.newContext({ storageState: undefined });
      const page = await context.newPage();

      await page.goto("/workspace");
      await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });

      await context.close();
    });

    test("unauthenticated access to /admin redirects to login", async ({ browser }) => {
      const context = await browser.newContext({ storageState: undefined });
      const page = await context.newPage();

      await page.goto("/admin");
      await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });

      await context.close();
    });
  });
});
