import { type Page, type Locator, expect } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class SolvePage {
  readonly page: Page;
  readonly sidebar: Locator;
  readonly heading: Locator;

  constructor(page: Page) {
    this.page = page;
    this.sidebar = page.getByRole("navigation");
    this.heading = page.getByRole("heading").first();
  }

  async goto(locale?: string) {
    await this.page.goto(localePath("/solve", locale));
  }

  async gotoMarketplace(locale?: string) {
    await this.page.goto(localePath("/marketplace", locale));
  }

  async gotoExecutions(locale?: string) {
    await this.page.goto(localePath("/solve/executions", locale));
  }

  async gotoFavorites(locale?: string) {
    await this.page.goto(localePath("/solve/favorites", locale));
  }

  async gotoMultiObjective(locale?: string) {
    await this.page.goto(localePath("/solve/multi-objective", locale));
  }

  async expectLoaded() {
    await expect(this.page).toHaveURL(/\/solve/);
  }

  async expectHeadingVisible() {
    await expect(this.heading).toBeVisible();
  }

  async navigateViaSidebar(linkText: RegExp) {
    await this.sidebar.getByRole("link", { name: linkText }).click();
  }
}
