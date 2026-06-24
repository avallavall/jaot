import { type Page, type Locator, expect } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class LoginPage {
  readonly page: Page;
  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly loginButton: Locator;
  readonly errorMessage: Locator;
  readonly title: Locator;

  constructor(page: Page) {
    this.page = page;
    this.emailInput = page.getByLabel(/email/i);
    this.passwordInput = page.getByLabel(/password/i);
    this.loginButton = page.getByRole("button", { name: /log\s*in|sign\s*in|submit/i });
    this.errorMessage = page.getByText(/failed|invalid|error|unauthorized|incorrect|\[object/i)
      .or(page.locator(".text-destructive, .bg-destructive\\/10"));
    this.title = page.getByText("JAOT", { exact: true }).first();
  }

  async goto(locale?: string) {
    await this.page.goto(localePath("/login", locale));
  }

  async login(email: string, password: string) {
    await this.emailInput.fill(email);
    await this.passwordInput.fill(password);
    await this.loginButton.click();
  }

  async expectError(message?: string) {
    if (message) {
      await expect(this.page.getByText(new RegExp(message, "i"))).toBeVisible();
    } else {
      await expect(this.errorMessage).toBeVisible({ timeout: 10_000 });
    }
  }

  async expectRedirectAway() {
    await expect(this.page).not.toHaveURL(/\/login/, { timeout: 10_000 });
  }
}
