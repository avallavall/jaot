import { type Page, type Locator, expect } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class BuilderPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly createButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading").first();
    this.createButton = page.getByRole("link", { name: /new|create/i }).or(
      page.getByRole("button", { name: /new|create/i })
    );
  }

  async goto(locale?: string) {
    await this.page.goto(localePath("/builder", locale));
  }

  async gotoTemplates(locale?: string) {
    await this.page.goto(localePath("/builder/templates", locale));
  }

  async expectLoaded() {
    await expect(this.page).toHaveURL(/\/builder/);
  }

  async expectHeadingVisible() {
    await expect(this.heading).toBeVisible();
  }
}
