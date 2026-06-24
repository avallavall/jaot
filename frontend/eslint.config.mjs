import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jaotPlugin from "./eslint/plugin.mjs";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  // Playwright e2e files: disable React-specific rules + enforce JAOT boundary rule.
  {
    files: ["e2e/**/*.ts", "e2e/**/*.tsx"],
    plugins: { jaot: jaotPlugin },
    rules: {
      "react-hooks/rules-of-hooks": "off",
      "jaot/no-e2e-mock-jaot-boundary": "error",
    },
  },
]);

export default eslintConfig;
