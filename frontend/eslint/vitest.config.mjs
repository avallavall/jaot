/**
 * Vitest config for ESLint rule unit tests.
 *
 * Usage (from frontend/ directory):
 *   npx vitest run --config eslint/vitest.config.mjs
 *
 * This config is isolated from the main frontend vitest.config.ts because:
 * - ESLint rules run in Node.js, not a browser/jsdom environment.
 * - The main setup file (src/test/setup.tsx) uses browser APIs (localStorage, React mocks)
 *   that are unavailable in the node environment required by RuleTester.
 */

import { defineConfig } from "vitest/config";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: __dirname,
  test: {
    environment: "node",
    globals: true,
    setupFiles: [],
    include: ["rules/__tests__/**/*.test.{js,mjs,ts}"],
  },
});
