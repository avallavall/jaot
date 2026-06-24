/**
 * @vitest-environment node
 *
 * RuleTester unit tests for the `jaot/no-e2e-mock-jaot-boundary` ESLint rule.
 *
 * Requirements covered:
 *   P11-LINT-01 — JAOT-owned path with synthetic fulfill → ERROR
 *   P11-LINT-02 — External allowlist domains (Stripe, Resend) → VALID
 *   P11-LINT-03 — Bare eslint-disable comment (no justification) → ERROR
 *   P11-LINT-04 — Disable comment with proper justification → VALID
 *   P11-LINT-05 — Passthrough pattern (route.fulfill({ response })) → VALID
 *   P11-LINT-06 — Regex-literal route path (no leading slash) → ERROR (WR-02)
 *   P11-LINT-07 — Program:exit justification enforcement (WR-01)
 *
 * Wave 1 (11-02) implemented the real AST logic. Tests for the disable-comment
 * branch (Program:exit) use `Linter.verify()` directly because RuleTester v9
 * strips eslint-disable directives before the rule observes them.
 */

import { Linter, RuleTester } from "eslint";
import jaotPlugin from "../../plugin.mjs";
import rule from "../no-e2e-mock-jaot-boundary.mjs";

const ruleTester = new RuleTester();

// RuleTester.run() integrates with the vitest test runner via the global
// describe/it functions (vitest globals: true in vitest.config.ts).
// Each valid/invalid case is registered as an individual test.
ruleTester.run("no-e2e-mock-jaot-boundary", rule, {
  valid: [
    // P11-LINT-02a: Stripe is in the external allowlist — must pass without error.
    {
      name: "P11-LINT-02a: Stripe allowlist domain passes (api.stripe.com)",
      code: [
        'await page.route("https://api.stripe.com/v1/charges", async (route) => {',
        '  await route.fulfill({ status: 200, body: "{}" });',
        "});",
      ].join("\n"),
    },

    // P11-LINT-02b: Resend is in the allowlist via *.resend.com pattern — must pass.
    {
      name: "P11-LINT-02b: Resend allowlist domain passes (*.resend.com)",
      code: [
        'await page.route("https://api.resend.com/emails", async (route) => {',
        "  await route.fulfill({ status: 200 });",
        "});",
      ].join("\n"),
    },

    // P11-LINT-04: Anthropic API domain is in the external allowlist (paid LLM, D-07).
    // Wave 1 will also test the `eslint-disable-next-line -- justification:` mechanism,
    // but ESLint RuleTester v9 cannot cleanly test disable directives against a stub rule
    // (the directive generates an ESLint-internal "rule not found" error that masks RED/GREEN
    // state). The disable-comment enforcement tests are deferred to Wave 1 (11-02) where
    // the real rule implementation is present and can be tested end-to-end.
    // This case validates the allowlist check on a third distinct external domain.
    {
      name: "P11-LINT-04: Anthropic API allowlist domain passes (api.anthropic.com)",
      code: [
        'await page.route("https://api.anthropic.com/v1/messages", async (route) => {',
        "  await route.fulfill({ status: 200, body: JSON.stringify({ id: 'msg_test' }) });",
        "});",
      ].join("\n"),
    },

    // P11-LINT-05: Passthrough pattern from solve-execution.spec.ts:141-148.
    // The fulfill receives { response: resp } where resp = await route.fetch() —
    // this is an observer/spy, NOT a synthetic mock. Must pass without error.
    {
      name: "P11-LINT-05: passthrough pattern (route.fulfill({ response })) passes",
      code: [
        'await page.route("**/api/v2/solve", async (route) => {',
        "  const resp = await route.fetch();",
        "  await route.fulfill({ response: resp });",
        "});",
      ].join("\n"),
    },
  ],

  invalid: [
    // P11-LINT-01: Synthetic fulfill against a JAOT-owned path (/api/v2/contact).
    // The rule must report the `noJaotBoundaryMock` message.
    {
      name: "P11-LINT-01: synthetic fulfill against JAOT-owned path reports error",
      code: [
        'await page.route("**/api/v2/contact", async (route) => {',
        "  await route.fulfill({",
        "    status: 200,",
        '    contentType: "application/json",',
        '    body: JSON.stringify({ id: "ctc_e2e" }),',
        "  });",
        "});",
      ].join("\n"),
      errors: [{ messageId: "noJaotBoundaryMock" }],
    },

    // P11-LINT-03: Bare disable comment enforcement — the real rule (Wave 1, 11-02) will
    // detect bare `eslint-disable-next-line jaot/no-e2e-mock-jaot-boundary` comments (no
    // justification text) and report a bareDisableComment error on the comment node itself
    // (so the disable cannot suppress its own error). In RED state the stub never fires, so
    // this fails "Should have 1 error but had 0" — the correct RED signal.
    //
    // Note: the disable comment is intentionally NOT included in the test code here because
    // ESLint RuleTester v9 cannot handle eslint-disable directives in stub-only tests
    // (the directive generates a "rule not found" internal lint error that masks the RED
    // failure). The directive enforcement test is restructured here to test the bare path:
    // a JAOT-owned fulfill with a localhost variant — distinct from P11-LINT-01's path.
    {
      name: "P11-LINT-03: JAOT-owned localhost path (bare disable pattern) reports error",
      code: [
        'await page.route("**/api/v2/foo", async (route) => {',
        "  await route.fulfill({ status: 200 });",
        "});",
      ].join("\n"),
      errors: [{ messageId: "noJaotBoundaryMock" }],
    },

    // P11-LINT-06 (WR-02): A Playwright spec that uses a JavaScript regex literal
    // as the route pattern (`/api\/v2\/contact/`) — `extractPath` reads the regex's
    // `.pattern` string ("api/v2/contact"), which has NO leading slash. The
    // bare-slash JAOT_OWNED patterns (`/\/api\/v[12]\//`) won't match. The
    // complementary `^api\/v[12]\/` and `^api\/` patterns added in v2.2-cleanup
    // close this gap.
    {
      name: "P11-LINT-06: regex-literal JAOT-owned path reports error (WR-02)",
      code: [
        "await page.route(/api\\/v2\\/contact/, async (route) => {",
        "  await route.fulfill({ status: 200 });",
        "});",
      ].join("\n"),
      errors: [{ messageId: "noJaotBoundaryMock" }],
    },
  ],
});

// ---------------------------------------------------------------------------
// P11-LINT-07 (WR-01): Program:exit justification enforcement.
//
// `RuleTester` v9 strips `eslint-disable-next-line` directives before the rule
// observes them, so the disable-comment branch cannot be tested via
// `ruleTester.run({ invalid: [...] })`. `Linter.verify()` preserves directive
// comments in `sourceCode.getAllComments()`, which is what `Program:exit`
// inspects, so we use it directly.
// ---------------------------------------------------------------------------

const linter = new Linter({ configType: "flat" });
const linterConfig = [
  {
    plugins: { jaot: jaotPlugin },
    rules: { "jaot/no-e2e-mock-jaot-boundary": "error" },
  },
];

function justificationMessages(code) {
  return linter
    .verify(code, linterConfig)
    .filter((m) => m.messageId === "justificationRequired");
}

describe("Program:exit justification enforcement (WR-01)", () => {
  it("flags bare eslint-disable-next-line with no -- delimiter", () => {
    const code = [
      "// eslint-disable-next-line jaot/no-e2e-mock-jaot-boundary",
      'await page.route("**/api/v2/contact", async (route) => {',
      "  await route.fulfill({ status: 200 });",
      "});",
    ].join("\n");
    expect(justificationMessages(code).length).toBeGreaterThanOrEqual(1);
  });

  it("flags disable comment with short justification (< 25 chars)", () => {
    const code = [
      "// eslint-disable-next-line jaot/no-e2e-mock-jaot-boundary -- too short",
      'await page.route("**/api/v2/contact", async (route) => {',
      "  await route.fulfill({ status: 200 });",
      "});",
    ].join("\n");
    expect(justificationMessages(code).length).toBeGreaterThanOrEqual(1);
  });

  it("flags disable comment whose justification contains TODO/FIXME", () => {
    const code = [
      "// eslint-disable-next-line jaot/no-e2e-mock-jaot-boundary -- TODO clean this up before next release",
      'await page.route("**/api/v2/contact", async (route) => {',
      "  await route.fulfill({ status: 200 });",
      "});",
    ].join("\n");
    expect(justificationMessages(code).length).toBeGreaterThanOrEqual(1);
  });

  it("accepts disable comment with substantive justification (>= 25 chars, no markers)", () => {
    const code = [
      "// eslint-disable-next-line jaot/no-e2e-mock-jaot-boundary -- external Stripe webhook stub, see tests/integration_proof.md §3",
      'await page.route("**/api/v2/contact", async (route) => {',
      "  await route.fulfill({ status: 200 });",
      "});",
    ].join("\n");
    expect(justificationMessages(code)).toHaveLength(0);
  });
});
