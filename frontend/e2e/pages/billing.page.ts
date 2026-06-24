import { type Page, type Locator, expect } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class BillingPage {
  readonly page: Page;
  readonly heading: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByText(/billing/i).first();
  }

  async goto(locale?: string) {
    const path = localePath("/billing", locale);
    // Retry navigation if the page returns a server error (Next.js 16 compilation race)
    for (let attempt = 0; attempt < 5; attempt++) {
      await this.page.goto(path);
      await this.page.waitForLoadState("domcontentloaded");
      const bodyText = await this.page.textContent("body");
      if (bodyText && !bodyText.includes("Internal Server Error")) break;
      // Wait longer on each retry to let compilation settle
      if (attempt < 4) {
        await this.page.waitForTimeout(2000 * (attempt + 1));
      }
    }
  }

  async expectLoaded() {
    await expect(this.page).toHaveURL(/\/billing/);
  }

  async expectHeadingVisible() {
    await expect(this.heading).toBeVisible({ timeout: 15_000 });
  }
}
