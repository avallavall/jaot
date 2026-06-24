import { defineConfig, devices } from "@playwright/test";
import path from "path";

const authFile = path.join(__dirname, "e2e/.auth/user.json");
const adminAuthFile = path.join(__dirname, "e2e/.auth/admin.json");

// R-24 / Q-35: spec-pattern constants. Lifting these above defineConfig
// keeps the project definitions short and makes "which specs run here"
// grep-friendly (add/remove a spec in one place instead of three).
const SETUP_SPECS: RegExp[] = [/global\.setup\.ts/, /admin\.setup\.ts/];

const PUBLIC_SPECS: RegExp[] = [
  /locale\.spec\.ts/,
  /i18n-infrastructure\.spec\.ts/,
  /docs\.spec\.ts/,
  /docs-code-blocks\.spec\.ts/,
  /translations\.spec\.ts/,
  /seo-canonical-hreflang\.spec\.ts/,
  /seo-metadata\.spec\.ts/,
  /seo-structured-data\.spec\.ts/,
];

const ADMIN_SPECS: RegExp[] = [
  /admin\.spec\.ts/,
  /admin-crud\.spec\.ts/,
  /announcement-banner\.spec\.ts/,
];

const DPR_SPECS: RegExp[] = [/ui-polish\.spec\.ts/];

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  // Limit workers in CI/Docker to avoid overwhelming the dev server
  workers: process.env.CI ? 2 : undefined,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "html",

  use: {
    baseURL: process.env.BASE_URL || "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    // Setup project: authenticates regular user and saves storageState
    {
      name: "setup",
      testMatch: /global\.setup\.ts/,
    },

    // Admin setup project: authenticates admin user and saves storageState
    {
      name: "admin-setup",
      testMatch: /admin\.setup\.ts/,
    },

    // Public tests: no auth needed (locale smoke tests, etc.)
    {
      name: "public",
      use: {
        ...devices["Desktop Chrome"],
      },
      testMatch: PUBLIC_SPECS,
    },

    // Main tests run with authenticated (regular user) state
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: authFile,
      },
      dependencies: ["setup"],
      // Ignore setup files, admin specs, public specs, DPR specs.
      testIgnore: [
        ...SETUP_SPECS,
        ...PUBLIC_SPECS,
        ...ADMIN_SPECS,
        ...DPR_SPECS,
        /audit-walkthrough\.spec\.ts/,
      ],
    },

    // Admin tests run with admin auth state.
    {
      name: "admin",
      use: {
        ...devices["Desktop Chrome"],
        storageState: adminAuthFile,
      },
      dependencies: ["admin-setup"],
      testMatch: ADMIN_SPECS,
    },

    // DPR testing projects (UI polish verification)
    {
      name: "dpr-1",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1920, height: 1080 },
        deviceScaleFactor: 1,
      },
      testMatch: DPR_SPECS,
    },
    {
      name: "dpr-1.25",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 2560, height: 1440 },
        deviceScaleFactor: 1.25,
      },
      testMatch: DPR_SPECS,
    },
    {
      name: "dpr-1.5",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 2560, height: 1440 },
        deviceScaleFactor: 1.5,
      },
      testMatch: DPR_SPECS,
    },
    {
      name: "dpr-2",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 3840, height: 2160 },
        deviceScaleFactor: 2,
      },
      testMatch: DPR_SPECS,
    },
  ],

  // Auto-start Next.js dev server (Docker Compose handles this in CI)
  webServer: process.env.CI
    ? undefined
    : {
        command: "npm run dev",
        url: "http://localhost:3000",
        reuseExistingServer: true,
        timeout: 60_000,
      },
});
