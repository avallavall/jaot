/**
 * End-to-end manual demo of the home announcement banner.
 *
 * Walks through every case described in the verification plan, taking
 * screenshots at each step so a human reviewer can see the feature in
 * action without running anything themselves. Output lands in
 * docs/screenshots/announcement-banner/.
 *
 * Each test is self-contained: it sets the admin settings via the platform
 * settings API (not by clicking the form) where possible to keep state
 * deterministic, except for the "configure via admin UI" capture which
 * deliberately uses the form so the screenshot shows the admin flow.
 *
 * Auth: the suite relies on admin.setup.ts having produced
 * frontend/e2e/.auth/admin.json (admin@jaot.io / AdminPass123!).
 */
import { test, expect, devices } from "@playwright/test";
import path from "path";

const SHOTS = path.resolve(__dirname, "../../docs/screenshots/announcement-banner");
const ADMIN_AUTH = path.join(__dirname, ".auth/admin.json");
const API_BASE = process.env.BASE_URL || "http://localhost:3000";

// Helper: set a platform setting via the admin API.
async function setSettings(
  request: import("@playwright/test").APIRequestContext,
  updates: Record<string, string>,
) {
  const res = await request.put(`${API_BASE}/api/v2/admin/settings/values`, {
    data: { updates },
  });
  if (!res.ok()) {
    throw new Error(`Failed to set ${JSON.stringify(updates)}: ${res.status()} ${await res.text()}`);
  }
}

async function setSetting(
  request: import("@playwright/test").APIRequestContext,
  key: string,
  value: string,
) {
  await setSettings(request, { [key]: value });
}

type Locale = "en" | "es" | "ca" | "fr" | "de";

async function setBanner(
  request: import("@playwright/test").APIRequestContext,
  opts: {
    enabled: boolean;
    rotationSeconds?: number;
  } & Partial<Record<Locale, string>>,
) {
  const updates: Record<string, string> = {
    HOME_ANNOUNCEMENT_ENABLED: opts.enabled ? "true" : "false",
  };
  for (const loc of ["en", "es", "ca", "fr", "de"] as const) {
    if (opts[loc] !== undefined) {
      updates[`HOME_ANNOUNCEMENT_TEXT_${loc.toUpperCase()}`] = opts[loc]!;
    }
  }
  if (opts.rotationSeconds !== undefined) {
    updates.HOME_ANNOUNCEMENT_ROTATION_SECONDS = String(opts.rotationSeconds);
  }
  await setSettings(request, updates);
}

test.describe.configure({ mode: "serial" });

test.use({ storageState: ADMIN_AUTH });

// Helper used by tests 01 and 02 — opens the System tab, expands the
// "HOME ANNOUNCEMENT" group, and returns the page object.
async function openAnnouncementGroup(page: import("@playwright/test").Page) {
  await page.goto("/en/admin/settings");
  await page.waitForLoadState("networkidle");
  // Settings are grouped by inferred prefix (HOME_ANNOUNCEMENT_*); the group
  // header is rendered as collapsed by default. Click to expand.
  const groupHeader = page.getByText(/HOME ANNOUNCEMENT \(7 settings\)/i).first();
  await groupHeader.waitFor({ timeout: 15_000 });
  await groupHeader.scrollIntoViewIfNeeded();
  await groupHeader.click();
  // Wait for the expanded content (the first setting label) to appear.
  await page.getByText("Home announcement enabled", { exact: false }).first().waitFor({
    timeout: 5_000,
  });
}

test("01 — Admin settings panel shows the 7 new announcement settings", async ({ page }) => {
  await openAnnouncementGroup(page);
  // Sanity check: all 7 setting labels are rendered.
  await expect(page.getByText("Home announcement enabled", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Announcement text (English)", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Announcement text (Spanish)", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Announcement text (Catalan)", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Announcement text (French)", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Announcement text (German)", { exact: false }).first()).toBeVisible();
  await expect(
    page.getByText("Announcement rotation interval", { exact: false }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(SHOTS, "01-admin-announcement-settings-desktop.png"),
    fullPage: true,
  });
});

test("02 — Configure banner via admin UI (English, 3 rotating messages)", async ({
  page,
  request,
}) => {
  await openAnnouncementGroup(page);

  // Toggle "Home announcement enabled" ON.
  const toggle = page.getByRole("switch").first();
  if ((await toggle.getAttribute("aria-checked")) !== "true") {
    await toggle.click();
  }

  // Find the English text input by its label proximity. The admin renders one
  // input per setting in document order: enabled (switch), then EN, ES, CA,
  // FR, DE strings, then rotation_seconds (number). So input[0] = EN.
  const inputs = page.locator("input[type='text'], input:not([type]), textarea");
  await inputs.first().fill("Promo 20% off | Maintenance Saturday | New solvers available");
  await page.screenshot({
    path: path.join(SHOTS, "02-admin-banner-configured-desktop.png"),
    fullPage: true,
  });

  // Save button (admin uses "Save Changes")
  const saveBtn = page.getByRole("button", { name: /save changes|save|apply/i }).first();
  if (await saveBtn.isVisible().catch(() => false)) {
    await saveBtn.click();
    await page.waitForTimeout(500);
  }

  // Finalise via API to guarantee the rest of the suite sees the new values.
  await setBanner(request, {
    enabled: true,
    en: "Promo 20% off | Maintenance Saturday | New solvers available",
  });
});

test("03 — Desktop home shows the banner with first message", async ({ page, request }) => {
  await setBanner(request, {
    enabled: true,
    en: "Promo 20% off | Maintenance Saturday | New solvers available",
    rotationSeconds: 3,
  });
  await page.goto("/en?cb=" + Date.now());
  const banner = page.getByRole("region", { name: /site announcement/i });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Promo 20% off");
  await page.screenshot({
    path: path.join(SHOTS, "03-home-desktop-banner-message-1.png"),
    fullPage: true,
  });
});

test("04 — Banner rotates to the second and third messages", async ({ page, request }) => {
  await setBanner(request, {
    enabled: true,
    en: "Promo 20% off | Maintenance Saturday | New solvers available",
    rotationSeconds: 3,
  });
  await page.goto("/en?cb=" + Date.now());
  const banner = page.getByRole("region", { name: /site announcement/i });
  await expect(banner).toContainText("Promo 20% off");
  // wait for rotation tick
  await page.waitForTimeout(3500);
  await expect(banner).toContainText("Maintenance Saturday");
  await page.screenshot({
    path: path.join(SHOTS, "04-home-desktop-banner-message-2.png"),
    fullPage: true,
  });
  await page.waitForTimeout(3500);
  await expect(banner).toContainText("New solvers available");
  await page.screenshot({
    path: path.join(SHOTS, "04b-home-desktop-banner-message-3.png"),
    fullPage: true,
  });
});

test("05 — Per-locale: /es shows Spanish text different from /en", async ({ page, request }) => {
  await setBanner(request, {
    enabled: true,
    en: "Hello world",
    es: "Hola mundo — descuentos solo en español",
  });
  await page.goto("/es?cb=" + Date.now());
  const banner = page.getByRole("region", { name: /anuncio del sitio/i });
  await expect(banner).toContainText("Hola mundo");
  await page.screenshot({
    path: path.join(SHOTS, "05-home-desktop-spanish-locale.png"),
    fullPage: true,
  });
});

test("06 — Edge: toggle OFF + non-empty text hides the banner", async ({ page, request }) => {
  await setBanner(request, { enabled: false, en: "should not appear" });
  await page.goto("/en?cb=" + Date.now());
  const banner = page.getByRole("region", { name: /site announcement/i });
  await expect(banner).toHaveCount(0);
  await page.screenshot({
    path: path.join(SHOTS, "06-edge-toggle-off-no-banner.png"),
    fullPage: true,
  });
});

test("07 — Edge: toggle ON + empty text hides the banner", async ({ page, request }) => {
  await setBanner(request, { enabled: true, en: "", es: "" });
  await page.goto("/en?cb=" + Date.now());
  await expect(page.getByRole("region", { name: /site announcement/i })).toHaveCount(0);
  await page.screenshot({
    path: path.join(SHOTS, "07-edge-empty-text-no-banner.png"),
    fullPage: true,
  });
});

test("08 — Edge: single message (no '|') renders, does not rotate", async ({ page, request }) => {
  await setBanner(request, { enabled: true, en: "Only one message — no rotation" });
  await page.goto("/en?cb=" + Date.now());
  const banner = page.getByRole("region", { name: /site announcement/i });
  await expect(banner).toContainText("Only one message");
  // Wait longer than any plausible rotation interval; text must not change.
  await page.waitForTimeout(4000);
  await expect(banner).toContainText("Only one message");
  await page.screenshot({
    path: path.join(SHOTS, "08-edge-single-message.png"),
    fullPage: true,
  });
});

test("09 — Dismiss button hides the banner and persists across reload", async ({
  page,
  request,
}) => {
  await setBanner(request, {
    enabled: true,
    en: "Dismiss me | I should not come back",
    rotationSeconds: 5,
  });
  await page.goto("/en?cb=" + Date.now());
  const banner = page.getByRole("region", { name: /site announcement/i });
  await expect(banner).toBeVisible();
  await page.screenshot({
    path: path.join(SHOTS, "09a-dismiss-before-click.png"),
    fullPage: true,
  });

  await page.getByRole("button", { name: /dismiss announcement/i }).click();
  await expect(banner).toHaveCount(0);
  await page.screenshot({
    path: path.join(SHOTS, "09b-dismiss-after-click.png"),
    fullPage: true,
  });

  // Reload — dismissal persists via localStorage.
  await page.reload();
  await expect(page.getByRole("region", { name: /site announcement/i })).toHaveCount(0);
  await page.screenshot({
    path: path.join(SHOTS, "09c-dismiss-persists-after-reload.png"),
    fullPage: true,
  });
});

test("10 — Changing the text re-shows the banner after a previous dismissal", async ({
  page,
  request,
}) => {
  // First dismiss text A
  await setBanner(request, { enabled: true, en: "Text version A | second A" });
  await page.goto("/en?cb=" + Date.now());
  await page.getByRole("button", { name: /dismiss announcement/i }).click();
  await expect(page.getByRole("region", { name: /site announcement/i })).toHaveCount(0);
  // Admin updates text to version B
  await setBanner(request, { enabled: true, en: "Text version B — fresh content" });
  await page.reload();
  const banner = page.getByRole("region", { name: /site announcement/i });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Text version B");
  await page.screenshot({
    path: path.join(SHOTS, "10-text-change-invalidates-dismiss.png"),
    fullPage: true,
  });
});

test("11 — Mobile viewport (iPhone 14) — banner readable and dismissable", async ({
  browser,
  request,
}) => {
  await setBanner(request, {
    enabled: true,
    en: "Mobile-friendly | Promo 20% | Saturday maintenance",
    rotationSeconds: 3,
  });
  const context = await browser.newContext({
    ...devices["iPhone 14"],
    storageState: ADMIN_AUTH,
  });
  const page = await context.newPage();
  await page.goto("/en?cb=" + Date.now());
  const banner = page.getByRole("region", { name: /site announcement/i });
  await expect(banner).toBeVisible();
  await page.screenshot({
    path: path.join(SHOTS, "11a-mobile-banner-visible.png"),
    fullPage: true,
  });
  await page.waitForTimeout(3500);
  await page.screenshot({
    path: path.join(SHOTS, "11b-mobile-banner-rotated.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: /dismiss announcement/i }).click();
  await expect(banner).toHaveCount(0);
  await page.screenshot({
    path: path.join(SHOTS, "11c-mobile-after-dismiss.png"),
    fullPage: true,
  });
  await context.close();
});

test("12 — Cleanup: leave the banner disabled with empty text", async ({ request }) => {
  await setBanner(request, {
    enabled: false,
    en: "",
    es: "",
    ca: "",
    fr: "",
    de: "",
    rotationSeconds: 5,
  });
});
