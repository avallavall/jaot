import { type Page, type Locator, expect } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class WorkspacePage {
  readonly page: Page;
  readonly heading: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading").first();
  }

  async goto(locale?: string) {
    await this.page.goto(localePath("/workspace", locale));
  }

  async gotoCredits(locale?: string) {
    await this.page.goto(localePath("/workspace/credits", locale));
  }

  async gotoApiKeys(locale?: string) {
    await this.page.goto(localePath("/workspace/api-keys", locale));
  }

  async gotoTeam(locale?: string) {
    await this.page.goto(localePath("/workspace/team", locale));
  }

  async gotoUsage(locale?: string) {
    await this.page.goto(localePath("/workspace/usage", locale));
  }

  async gotoProfile(locale?: string) {
    await this.page.goto(localePath("/workspace/my-profile", locale));
  }

  async gotoAudit(locale?: string) {
    await this.page.goto(localePath("/workspace/audit", locale));
  }

  async gotoWorkspaces(locale?: string) {
    await this.page.goto(localePath("/workspace/workspaces", locale));
  }

  async expectLoaded() {
    await expect(this.page).toHaveURL(/\/workspace/);
  }

  async expectHeadingVisible() {
    await expect(this.heading).toBeVisible({ timeout: 15_000 });
  }
}
