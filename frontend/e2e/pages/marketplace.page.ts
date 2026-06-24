import { type Page, type Locator, expect } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class MarketplacePage {
  readonly page: Page;
  readonly heading: Locator;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading").first();
    this.searchInput = page.getByRole("searchbox").or(
      page.getByPlaceholder(/search/i)
    );
  }

  async goto(locale?: string) {
    await this.page.goto(localePath("/marketplace", locale));
  }

  async expectLoaded() {
    await expect(this.page).toHaveURL(/\/marketplace/);
    await expect(this.heading).toBeVisible();
  }

  async search(query: string) {
    await this.searchInput.fill(query);
  }
}
