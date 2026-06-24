/**
 * Local ESLint plugin for JAOT frontend rules.
 *
 * Usage in eslint.config.mjs:
 *   import jaotPlugin from "./eslint/plugin.mjs";
 *   // ...
 *   {
 *     files: ["e2e/**\/*.ts", "e2e/**\/*.tsx"],
 *     plugins: { jaot: jaotPlugin },
 *     rules: {
 *       "jaot/no-e2e-mock-jaot-boundary": "error",
 *     },
 *   }
 */

import noE2eMockJaotBoundary from "./rules/no-e2e-mock-jaot-boundary.mjs";

export default {
  rules: {
    "no-e2e-mock-jaot-boundary": noE2eMockJaotBoundary,
  },
};
