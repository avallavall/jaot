import { type Page, type Locator, expect } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class SolvePage {
  readonly page: Page;
  readonly sidebar: Locator;
  readonly heading: Locator;

  constructor(page: Page) {
    this.page = page;
    // Nested pages also render a breadcrumb <nav> — pin the sidebar by name.
    this.sidebar = page.getByRole("navigation", { name: "Main navigation" });
    this.heading = page.getByRole("heading").first();
  }

  // P1.5 fusion: the legacy /solve dashboard redirects to /studio — specs that
  // need the model list should target the studio directly.
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

  async navigateViaSidebar(linkText: RegExp) {
    await this.sidebar.getByRole("link", { name: linkText }).click();
  }
}
