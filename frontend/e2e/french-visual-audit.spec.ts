/**
 * French Locale Visual Audit
 *
 * Navigates all demo-critical pages in French (verbose language) to:
 * 1. Capture fullPage screenshots for visual review
 * 2. Detect text overflow / truncation issues
 * 3. Log console errors + network failures
 *
 * Run: npx playwright test french-visual-audit.spec.ts --project=public --workers=1 --timeout=600000
 */
import { test, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";

const SCREENSHOT_BASE = path.resolve(__dirname, "../screenshots/french-audit");
const AUDIT_LOG_PATH = path.resolve(
  __dirname,
  "../screenshots/french-audit/audit-log.json"
);

const ADMIN_EMAIL = "admin@jaot.io";
const ADMIN_PASSWORD = "AdminPass123!";
const LOCALE = "fr";

interface AuditEntry {
  url: string;
  group: string;
  pageName: string;
  screenshotPath: string;
  consoleErrors: string[];
  networkFailures: string[];
  timestamp: string;
  fallbackScreenshot: boolean;
  note?: string;
}

function ensureDir(dir: string) {
  fs.mkdirSync(dir, { recursive: true });
}

function readAuditLog(): AuditEntry[] {
  try {
    if (fs.existsSync(AUDIT_LOG_PATH)) {
      return JSON.parse(fs.readFileSync(AUDIT_LOG_PATH, "utf-8"));
    }
  } catch {
    // corrupted file, start fresh
  }
  return [];
}

function appendToAuditLog(entry: AuditEntry) {
  ensureDir(path.dirname(AUDIT_LOG_PATH));
  const log = readAuditLog();
  log.push(entry);
  fs.writeFileSync(AUDIT_LOG_PATH, JSON.stringify(log, null, 2), "utf-8");
}

function setupPageListeners(page: Page) {
  const consoleErrors: string[] = [];
  const networkFailures: string[] = [];

  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });

  page.on("requestfailed", (request) => {
    networkFailures.push(
      `${request.method()} ${request.url()} - ${request.failure()?.errorText ?? "unknown"}`
    );
  });

  return { consoleErrors, networkFailures };
}

/** Prefix path with French locale */
function frPath(pagePath: string): string {
  return `/${LOCALE}${pagePath === "/" ? "" : pagePath}`;
}

async function auditPage(
  page: Page,
  pagePath: string,
  group: string,
  pageName: string,
  fileName: string,
  note?: string
) {
  const url = frPath(pagePath);
  const screenshotDir = path.join(SCREENSHOT_BASE, group);
  ensureDir(screenshotDir);
  const screenshotPath = path.join(screenshotDir, fileName);

  const { consoleErrors, networkFailures } = setupPageListeners(page);

  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  } catch {
    consoleErrors.push(`[audit] page.goto timeout for ${url}`);
  }

  // Wait for hydration and lazy loads
  await page.waitForTimeout(2000);

  let fallbackScreenshot = false;
  try {
    await page.screenshot({
      path: screenshotPath,
      fullPage: true,
      timeout: 15000,
    });
  } catch {
    try {
      await page.screenshot({
        path: screenshotPath,
        fullPage: false,
        timeout: 10000,
      });
      fallbackScreenshot = true;
    } catch {
      consoleErrors.push(`[audit] screenshot failed entirely for ${url}`);
    }
  }

  const entry: AuditEntry = {
    url,
    group,
    pageName,
    screenshotPath: path.relative(SCREENSHOT_BASE, screenshotPath),
    consoleErrors: [...consoleErrors],
    networkFailures: [...networkFailures],
    timestamp: new Date().toISOString(),
    fallbackScreenshot,
  };
  if (note) entry.note = note;

  appendToAuditLog(entry);

  page.removeAllListeners("console");
  page.removeAllListeners("requestfailed");
}

async function extractLinks(page: Page, hrefPattern: RegExp): Promise<string[]> {
  const links = await page.locator("a[href]").all();
  const hrefs: string[] = [];
  for (const link of links) {
    const href = await link.getAttribute("href");
    if (href && hrefPattern.test(href)) {
      hrefs.push(href);
    }
  }
  return hrefs;
}

async function extractFirstId(
  page: Page,
  listPath: string,
  linkPattern: RegExp
): Promise<string | null> {
  try {
    await page.goto(frPath(listPath), {
      waitUntil: "networkidle",
      timeout: 20000,
    });
    await page.waitForTimeout(2000);
    const links = await extractLinks(page, linkPattern);
    if (links.length > 0) {
      const match = links[0].match(linkPattern);
      if (match && match[1]) return match[1];
    }
  } catch {
    // Silent failure
  }
  return null;
}

async function loginAsAdmin(page: Page, attempt = 1): Promise<void> {
  const MAX_ATTEMPTS = 3;

  try {
    await page.goto(frPath("/login"), {
      waitUntil: "domcontentloaded",
      timeout: 20000,
    });
  } catch {
    await page.goto(frPath("/login"), { timeout: 30000 });
  }
  await page.waitForTimeout(2000);

  const currentUrl = page.url();
  if (!currentUrl.includes("/login")) {
    return;
  }

  try {
    await page.locator("#email").waitFor({ state: "visible", timeout: 15000 });
  } catch {
    if (attempt < MAX_ATTEMPTS) {
      await page.reload({ waitUntil: "domcontentloaded", timeout: 15000 });
      await page.waitForTimeout(3000);
      return loginAsAdmin(page, attempt + 1);
    }
    throw new Error(
      `Login failed after ${MAX_ATTEMPTS} attempts: #email input never became visible`
    );
  }

  await page.locator("#email").fill(ADMIN_EMAIL);
  await page.locator("#password").fill(ADMIN_PASSWORD);
  await page.locator('button[type="submit"]').click();

  try {
    await page.waitForURL((url) => !url.pathname.includes("/login"), {
      timeout: 15000,
    });
  } catch {
    try {
      await page.locator('button[type="submit"]').click();
      await page.waitForURL((url) => !url.pathname.includes("/login"), {
        timeout: 10000,
      });
    } catch {
      if (attempt < MAX_ATTEMPTS) {
        return loginAsAdmin(page, attempt + 1);
      }
      throw new Error(
        `Login redirect failed after ${MAX_ATTEMPTS} attempts`
      );
    }
  }
  await page.waitForTimeout(1000);
}

// Override: no storage state, handle auth inline, 1920x1080 desktop
test.use({
  storageState: undefined,
  viewport: { width: 1920, height: 1080 },
  locale: "fr-FR",
});

test.describe.configure({ mode: "serial" });
test.setTimeout(600000);

test.beforeAll(() => {
  ensureDir(path.dirname(AUDIT_LOG_PATH));
  if (fs.existsSync(AUDIT_LOG_PATH)) {
    fs.unlinkSync(AUDIT_LOG_PATH);
  }
});

/* ------------------------------------------------------------------ */
/* Group 1: Public pages in French                                     */
/* ------------------------------------------------------------------ */

test("Group 1: Public pages (FR)", async ({ page }) => {
  await auditPage(page, "/", "public", "Landing", "01-landing.png");
  await auditPage(page, "/pricing", "public", "Pricing", "02-pricing.png");
  await auditPage(
    page,
    "/docs/getting-started",
    "public",
    "Docs",
    "03-docs.png"
  );
  await auditPage(
    page,
    "/marketplace",
    "public",
    "Marketplace",
    "04-marketplace.png"
  );

  const marketplaceModelId = await extractFirstId(
    page,
    "/marketplace",
    /\/marketplace\/([a-f0-9-]+)/
  );
  if (marketplaceModelId) {
    await auditPage(
      page,
      `/marketplace/${marketplaceModelId}`,
      "public",
      "Model Detail",
      "05-model-detail.png"
    );
  }

  await auditPage(
    page,
    "/for-sellers",
    "public",
    "For Sellers",
    "06-for-sellers.png"
  );
  await auditPage(page, "/terms", "public", "Terms", "07-terms.png");
  await auditPage(page, "/privacy", "public", "Privacy", "08-privacy.png");
  await auditPage(page, "/licenses", "public", "Licenses", "09-licenses.png");
});

/* ------------------------------------------------------------------ */
/* Group 2: Auth pages in French                                       */
/* ------------------------------------------------------------------ */

test("Group 2: Auth pages (FR)", async ({ page }) => {
  await auditPage(page, "/login", "auth", "Login", "01-login.png");
  await auditPage(page, "/signup", "auth", "Signup", "02-signup.png");
  await auditPage(
    page,
    "/forgot-password",
    "auth",
    "Forgot Password",
    "03-forgot-password.png"
  );
  await auditPage(
    page,
    "/reset-password",
    "auth",
    "Reset Password",
    "04-reset-password.png"
  );
});

/* ------------------------------------------------------------------ */
/* Group 3: Solve / Models (demo critical!)                            */
/* ------------------------------------------------------------------ */

test("Group 3: Solve pages (FR)", async ({ page }) => {
  await loginAsAdmin(page);

  await auditPage(page, "/solve", "solve", "My Models", "01-my-models.png");
  await auditPage(
    page,
    "/solve/create",
    "solve",
    "Create Model",
    "02-create.png"
  );
  await auditPage(
    page,
    "/solve/custom",
    "solve",
    "Custom Model",
    "03-custom.png"
  );
  await auditPage(
    page,
    "/solve/favorites",
    "solve",
    "Favorites",
    "04-favorites.png"
  );
  await auditPage(
    page,
    "/solve/multi-objective",
    "solve",
    "Multi-Objective",
    "05-multi-objective.png"
  );

  const modelId = await extractFirstId(
    page,
    "/solve",
    /\/solve\/([a-f0-9-]+)(?!\/(create|custom|favorites|multi-objective|executions))/
  );

  if (modelId) {
    await auditPage(
      page,
      `/solve/${modelId}`,
      "solve",
      "Model Detail",
      "06-model-detail.png"
    );
    await auditPage(
      page,
      `/solve/${modelId}/history`,
      "solve",
      "Model History",
      "07-model-history.png"
    );
    await auditPage(
      page,
      `/solve/${modelId}/publish`,
      "solve",
      "Model Publish",
      "08-model-publish.png"
    );
  }

  await auditPage(
    page,
    "/solve/executions",
    "solve",
    "Executions",
    "09-executions.png"
  );

  const executionId = await extractFirstId(
    page,
    "/solve/executions",
    /\/solve\/executions\/([a-f0-9-]+)(?!\/compare)/
  );
  if (executionId) {
    await auditPage(
      page,
      `/solve/executions/${executionId}`,
      "solve",
      "Execution Detail",
      "10-execution-detail.png"
    );
  }

  await auditPage(
    page,
    "/solve/executions/compare",
    "solve",
    "Execution Compare",
    "11-execution-compare.png"
  );
});

/* ------------------------------------------------------------------ */
/* Group 4: Builder (demo critical! + visual editor)                   */
/* ------------------------------------------------------------------ */

test("Group 4: Builder pages (FR)", async ({ page }) => {
  await loginAsAdmin(page);

  await auditPage(page, "/builder", "builder", "Builder Home", "01-home.png");

  const documentId = await extractFirstId(
    page,
    "/builder",
    /\/builder\/([a-f0-9-]+)(?!\/(ai-assistant|templates))/
  );

  if (documentId) {
    await auditPage(
      page,
      `/builder/${documentId}`,
      "builder",
      "Visual Editor",
      "02-visual-editor.png"
    );
    await auditPage(
      page,
      `/builder/${documentId}/chat`,
      "builder",
      "Editor Chat",
      "03-editor-chat.png"
    );
  }

  await auditPage(
    page,
    "/builder/ai-assistant",
    "builder",
    "AI Assistant",
    "04-ai-assistant.png"
  );
  await auditPage(
    page,
    "/builder/templates",
    "builder",
    "Templates",
    "05-templates.png"
  );

  const templateId = await extractFirstId(
    page,
    "/builder/templates",
    /\/builder\/templates\/([a-f0-9-]+)/
  );
  if (templateId) {
    await auditPage(
      page,
      `/builder/templates/${templateId}`,
      "builder",
      "Template Detail",
      "06-template-detail.png"
    );
  }
});

/* ------------------------------------------------------------------ */
/* Group 5: Workspace (demo critical!)                                 */
/* ------------------------------------------------------------------ */

test("Group 5: Workspace pages (FR)", async ({ page }) => {
  await loginAsAdmin(page);

  await auditPage(
    page,
    "/workspace",
    "workspace",
    "Dashboard",
    "01-dashboard.png"
  );
  await auditPage(
    page,
    "/workspace/my-profile",
    "workspace",
    "My Profile",
    "02-my-profile.png"
  );
  await auditPage(
    page,
    "/workspace/api-keys",
    "workspace",
    "API Keys",
    "03-api-keys.png"
  );
  await auditPage(
    page,
    "/workspace/credits",
    "workspace",
    "Credits",
    "04-credits.png"
  );
  await auditPage(
    page,
    "/workspace/usage",
    "workspace",
    "Usage",
    "05-usage.png"
  );
  await auditPage(
    page,
    "/workspace/settings",
    "workspace",
    "Settings",
    "06-settings.png"
  );
  await auditPage(
    page,
    "/workspace/team",
    "workspace",
    "Team",
    "07-team.png"
  );
  await auditPage(
    page,
    "/workspace/audit",
    "workspace",
    "Audit Log",
    "08-audit-log.png"
  );
});

/* ------------------------------------------------------------------ */
/* Group 6: Triggers                                                   */
/* ------------------------------------------------------------------ */

test("Group 6: Triggers (FR)", async ({ page }) => {
  await loginAsAdmin(page);

  await auditPage(
    page,
    "/triggers",
    "triggers",
    "Triggers List",
    "01-list.png"
  );
  await auditPage(
    page,
    "/triggers/new",
    "triggers",
    "New Trigger",
    "02-new.png"
  );

  const triggerId = await extractFirstId(
    page,
    "/triggers",
    /\/triggers\/([a-f0-9-]+)(?!\/new)/
  );
  if (triggerId) {
    await auditPage(
      page,
      `/triggers/${triggerId}`,
      "triggers",
      "Trigger Detail",
      "03-detail.png"
    );
  }
});

/* ------------------------------------------------------------------ */
/* Group 7: Admin panel                                                */
/* ------------------------------------------------------------------ */

test("Group 7: Admin pages (FR)", async ({ page }) => {
  await loginAsAdmin(page);

  await auditPage(page, "/admin", "admin", "Dashboard", "01-dashboard.png");
  await auditPage(page, "/admin/users", "admin", "Users", "02-users.png");
  await auditPage(
    page,
    "/admin/organizations",
    "admin",
    "Organizations",
    "03-organizations.png"
  );
  await auditPage(page, "/admin/models", "admin", "Models", "04-models.png");
  await auditPage(
    page,
    "/admin/api-keys",
    "admin",
    "API Keys",
    "05-api-keys.png"
  );
  await auditPage(
    page,
    "/admin/executions",
    "admin",
    "Executions",
    "06-executions.png"
  );
  await auditPage(page, "/admin/credits", "admin", "Credits", "07-credits.png");
  await auditPage(
    page,
    "/admin/settings",
    "admin",
    "Settings",
    "08-settings.png"
  );
  await auditPage(
    page,
    "/admin/marketplace/analytics",
    "admin",
    "Marketplace Analytics",
    "09-mkt-analytics.png"
  );
  await auditPage(
    page,
    "/admin/marketplace/verification",
    "admin",
    "Marketplace Verification",
    "10-mkt-verification.png"
  );
});

/* ------------------------------------------------------------------ */
/* Group 8: Billing & misc                                             */
/* ------------------------------------------------------------------ */

test("Group 8: Billing & misc (FR)", async ({ page }) => {
  await loginAsAdmin(page);

  await auditPage(page, "/billing", "billing", "Billing", "01-billing.png");
});

/* ------------------------------------------------------------------ */
/* Summary                                                             */
/* ------------------------------------------------------------------ */

test.afterAll(() => {
  const log = readAuditLog();
  console.log(`\n[french-audit] Total pages captured: ${log.length}`);
  const groups = new Set(log.map((e) => e.group));
  for (const g of groups) {
    const count = log.filter((e) => e.group === g).length;
    const errors = log
      .filter((e) => e.group === g)
      .reduce((sum, e) => sum + e.consoleErrors.length, 0);
    console.log(`  ${g}: ${count} pages, ${errors} console errors`);
  }
  console.log(`[french-audit] Screenshots: ${SCREENSHOT_BASE}`);
  console.log(`[french-audit] Audit log: ${AUDIT_LOG_PATH}\n`);
});
