import { type Page, type Locator } from "@playwright/test";
import { localePath } from "../helpers/locale";

export class TriggersPage {
  readonly page: Page;
  readonly scheduleTab: Locator;
  readonly runHistoryTab: Locator;
  readonly setupScheduleButton: Locator;
  readonly enableToggle: Locator;
  readonly disableToggle: Locator;
  readonly saveButton: Locator;
  readonly runHistoryTable: Locator;
  readonly runHistoryRows: Locator;

  constructor(page: Page) {
    this.page = page;
    this.scheduleTab = page.getByRole("tab", { name: /schedule/i });
    this.runHistoryTab = page.getByRole("tab", { name: /run history|history/i });
    this.setupScheduleButton = page.getByRole("button", {
      name: /set up schedule|setup schedule/i,
    });
    this.enableToggle = page.getByRole("button", {
      name: /enable schedule/i,
    });
    this.disableToggle = page.getByRole("button", {
      name: /disable schedule/i,
    });
    this.saveButton = page.getByRole("button", { name: /save schedule/i });
    this.runHistoryTable = page.locator("table");
    this.runHistoryRows = page.locator("table tbody tr");
  }

  async goto(triggerId: string, locale?: string) {
    await this.page.goto(localePath(`/triggers/${triggerId}`, locale));
  }

  async openScheduleTab() {
    await this.scheduleTab.click();
    // Wait for schedule content to load. Use waitForFunction to check
    // that at least one schedule-specific element is in the DOM.
    await this.page.waitForFunction(
      () => {
        const body = document.body.textContent || "";
        return (
          /schedule enabled|schedule paused|no schedule configured|set up schedule/i.test(
            body
          )
        );
      },
      { timeout: 10_000 }
    );
  }

  async openRunHistoryTab() {
    await this.runHistoryTab.click();
    // Wait for table or "No runs" text to be visible
    await this.page.waitForFunction(
      () => {
        const body = document.body.textContent || "";
        const hasTable = document.querySelector("table tbody tr") !== null;
        return hasTable || /no runs yet/i.test(body);
      },
      { timeout: 10_000 }
    );
  }

  async expectScheduleLoaded() {
    await this.page.waitForFunction(
      () => {
        const body = document.body.textContent || "";
        return (
          /schedule enabled|schedule paused|no schedule configured|set up schedule/i.test(
            body
          )
        );
      },
      { timeout: 10_000 }
    );
  }

  async expectRunHistoryLoaded() {
    await this.page.waitForFunction(
      () => {
        const body = document.body.textContent || "";
        const hasTable = document.querySelector("table tbody tr") !== null;
        return hasTable || /no runs yet/i.test(body);
      },
      { timeout: 10_000 }
    );
  }
}
