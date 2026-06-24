import { type Page, type Locator, expect } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class AdminPage {
  readonly page: Page;
  readonly heading: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading").first();
  }

  async goto(locale?: string) {
    await this.page.goto(localePath("/admin", locale));
  }

  async gotoUsers(locale?: string) {
    await this.page.goto(localePath("/admin/users", locale));
  }

  async gotoOrganizations(locale?: string) {
    await this.page.goto(localePath("/admin/organizations", locale));
  }

  async gotoModels(locale?: string) {
    await this.page.goto(localePath("/admin/models", locale));
  }

  async gotoExecutions(locale?: string) {
    await this.page.goto(localePath("/admin/executions", locale));
  }

  async gotoCredits(locale?: string) {
    await this.page.goto(localePath("/admin/credits", locale));
  }

  async gotoApiKeys(locale?: string) {
    await this.page.goto(localePath("/admin/api-keys", locale));
  }

  async gotoReviews(locale?: string) {
    await this.page.goto(localePath("/admin/reviews", locale));
  }

  async gotoSettings(locale?: string) {
    await this.page.goto(localePath("/admin/settings", locale));
  }

  async expectLoaded() {
    await expect(this.page).toHaveURL(/\/admin/);
  }

  async expectHeadingVisible() {
    await expect(this.heading).toBeVisible({ timeout: 15_000 });
  }
}
