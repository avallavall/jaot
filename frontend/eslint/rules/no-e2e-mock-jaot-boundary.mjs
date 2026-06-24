/**
 * ESLint rule: no-e2e-mock-jaot-boundary
 *
 * Rejects `page.route(<path>).fulfill(...)` calls in Playwright E2E specs when
 * the path matches a JAOT-owned endpoint (e.g. /api/v2/, localhost:8001, jaot.io).
 *
 * External SaaS allowlist (Stripe, Resend, Anthropic, OpenAI) is permitted because
 * those services are paid-per-request or require unavailable CI credentials.
 * The allowlist is loaded from frontend/eslint/allowlist.json — single source of truth.
 *
 * See: tests/integration_proof.md §1 (antipattern), §2 (rule), §3 (allowlist)
 */

import { ESLintUtils } from "@typescript-eslint/utils";
import { createRequire } from "module";

const require = createRequire(import.meta.url);
const { domains } = require("../allowlist.json");

const createRule = ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/avallavall/jaot/blob/main/tests/integration_proof.md#${name}`,
);

/**
 * External SaaS domains loaded from allowlist.json — legitimately mocked in E2E specs (D-07).
 * Convert each pattern string to a RegExp for matching.
 */
const ALLOWLIST = domains.map((d) => new RegExp(d.pattern));

/**
 * JAOT-owned HTTP surface — mocking any of these paths is the antipattern (D-05).
 * Includes both versioned (/api/v2/) and broad catch-all (/api/) patterns, plus
 * all Docker hostnames and production domains.
 */
const JAOT_OWNED = [
  /\/api\/v[12]\//,   // versioned JAOT API in string globs: **/api/v2/*
  /\/api\//,          // broad API catch-all in string globs: **/api/**
  /^api\/v[12]\//,    // versioned API in regex-literal patterns (no leading /)
  /^api\//,           // broad API in regex-literal patterns (no leading /)
  /localhost:8001/,   // Docker backend on host
  /localhost:3000/,   // Next.js frontend proxy (re-proxies to backend)
  /frontend:3000/,    // Docker network frontend service
  /jaot\.io/,         // production hostname + subdomains
  /api:8001/,         // Docker network internal backend service name
];

/**
 * Extract a string representation of the path from a CallExpression argument node.
 * Returns null if the path is dynamic (Identifier / CallExpression) — skip those
 * to avoid false positives on variable-bound paths.
 */
function extractPath(argNode) {
  if (!argNode) return null;

  // String literal: page.route("**/api/v2/contact", ...)
  if (argNode.type === "Literal" && typeof argNode.value === "string") {
    return argNode.value;
  }

  // Regex literal: page.route(/api\/v2\/contact/, ...)
  // The `.regex.pattern` string preserves the escape characters from the
  // original source (e.g. `api\/v2\/contact` keeps the backslashes), so
  // strip the redundant `\/` escapes — inside a regex `\/` and `/` are
  // equivalent — before handing it to the JAOT_OWNED matchers.
  if (argNode.type === "Literal" && argNode.regex) {
    return argNode.regex.pattern.replace(/\\\//g, "/");
  }

  // Template literal: page.route(`**/api/v2/contact`, ...) or page.route(`**/api/v2/${id}`, ...)
  // Use the first quasi's raw text as the path, whether static or dynamic.
  // Even for dynamic templates, the static prefix (e.g. "**/api/v2/models/") is enough
  // to classify JAOT-owned vs external — per plan: conservatively flag if JAOT prefix present.
  if (argNode.type === "TemplateLiteral") {
    if (argNode.quasis.length >= 1) {
      return argNode.quasis[0].value.raw;
    }
    return null;
  }

  // Identifier or call expression — cannot resolve statically, skip
  return null;
}

/** Returns true if the path matches any JAOT-owned regex. */
function isJaotOwned(path) {
  return JAOT_OWNED.some((re) => re.test(path));
}

/** Returns true if the path matches any allowlisted external domain regex. */
function isAllowlisted(path) {
  return ALLOWLIST.some((re) => re.test(path));
}

/**
 * Returns true if the fulfill call argument object is a passthrough (observer) pattern.
 * Passthrough: { response: <anything> } — typically { response: await route.fetch() }.
 * Per P11-LINT-05: presence of a "response" property key → passthrough, do NOT flag.
 */
function isFulfillPassthrough(fulfillArgs) {
  if (!fulfillArgs || fulfillArgs.length === 0) return false;
  const firstArg = fulfillArgs[0];
  if (firstArg.type !== "ObjectExpression") return false;
  return firstArg.properties.some(
    (prop) =>
      prop.type === "Property" &&
      prop.key &&
      ((prop.key.type === "Identifier" && prop.key.name === "response") ||
        (prop.key.type === "Literal" && prop.key.value === "response")),
  );
}

/**
 * Walk all descendant AST nodes of a given node, invoking the visitor for each
 * node whose type matches typeName. Skips the "parent" back-pointer to avoid
 * circular traversal.
 */
function walkDescendants(node, typeName, visitor) {
  if (!node || typeof node !== "object") return;
  if (node.type === typeName) {
    visitor(node);
  }
  for (const key of Object.keys(node)) {
    if (key === "parent") continue;
    const child = node[key];
    if (Array.isArray(child)) {
      for (const item of child) {
        if (item && typeof item === "object" && item.type) {
          walkDescendants(item, typeName, visitor);
        }
      }
    } else if (child && typeof child === "object" && child.type) {
      walkDescendants(child, typeName, visitor);
    }
  }
}

export default createRule({
  name: "no-e2e-mock-jaot-boundary",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow synthetic page.route().fulfill() calls against JAOT-owned API paths in Playwright E2E specs.",
      recommended: true,
    },
    messages: {
      noJaotBoundaryMock:
        "page.route().fulfill() against JAOT-owned path '{{path}}' is not allowed in e2e/ specs. " +
        "Use real Docker backend or mock external services only (see tests/integration_proof.md §1). " +
        "Allowed external domains in frontend/eslint/allowlist.json.",
      justificationRequired:
        "eslint-disable for jaot/no-e2e-mock-jaot-boundary requires a justification comment " +
        "citing tests/integration_proof.md §3 (e.g., '-- justification: external Stripe, see integration_proof.md §3').",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    return {
      // Visitor for page.route(path, handler) and context.route(path, handler).
      // Matches any .route() call with at least 2 arguments. Extracts the path
      // from argument[0], checks it against ALLOWLIST and JAOT_OWNED, then walks
      // the handler (argument[1]) for .fulfill() calls.
      // Covers string literals, regex literals, static template literals (D-12).
      "CallExpression[callee.property.name='route']"(node) {
        if (node.arguments.length < 2) return;

        const pathArg = node.arguments[0];
        const handlerArg = node.arguments[1];

        const path = extractPath(pathArg);

        // Cannot resolve path statically — skip to avoid false positives
        if (path === null) return;

        // External allowlisted domain — permitted (D-07)
        if (isAllowlisted(path)) return;

        // Not JAOT-owned — outside policy scope (third-party, unknown)
        if (!isJaotOwned(path)) return;

        // JAOT-owned path: walk the handler body for any .fulfill() call.
        // Known limitation (IN-01): if handlerArg is an Identifier — i.e. the
        // handler is bound to a variable rather than passed inline — the AST
        // walk finds no descendant CallExpression and the rule reports nothing.
        // This is an inherent static-analysis limitation (cross-function data
        // flow); document the pattern in code review when it appears.
        walkDescendants(
          handlerArg,
          "CallExpression",
          (fulfillCall) => {
            // Must be a MemberExpression callee with property name "fulfill"
            if (
              !fulfillCall.callee ||
              fulfillCall.callee.type !== "MemberExpression" ||
              !fulfillCall.callee.property
            ) {
              return;
            }

            const prop = fulfillCall.callee.property;
            const isFulfillCall =
              (prop.type === "Identifier" && prop.name === "fulfill") ||
              (prop.type === "Literal" && prop.value === "fulfill");

            if (!isFulfillCall) return;

            // Passthrough pattern: { response: <expr> } — allow (P11-LINT-05)
            if (isFulfillPassthrough(fulfillCall.arguments)) return;

            // Synthetic fulfill against JAOT-owned path — violation
            context.report({
              node: fulfillCall,
              messageId: "noJaotBoundaryMock",
              data: { path },
            });
          },
        );
      },

      /**
       * Program:exit — enforce eslint-disable justification (D-13, T-11-02-01).
       *
       * Walks all source comments and finds `eslint-disable-next-line` directives
       * for this rule. Rejects bare disables and disables with low-quality
       * justification text (empty, < 25 chars, or containing TODO/FIXME/HACK/XXX).
       *
       * Note: ESLint's built-in disable-comment machinery already suppresses the
       * `noJaotBoundaryMock` error when an `eslint-disable` is present. This
       * `Program:exit` pass adds a SECOND diagnostic on the COMMENT NODE ITSELF
       * when the justification is missing or insufficient — so the disable comment
       * cannot silence its own quality violation.
       */
      "Program:exit"() {
        const sourceCode = context.getSourceCode
          ? context.getSourceCode()
          : context.sourceCode;
        const comments = sourceCode.getAllComments();

        for (const comment of comments) {
          const value = comment.value || "";

          // Only care about disable-next-line directives for this rule
          if (
            !/eslint-disable-next-line\s[^*]*jaot\/no-e2e-mock-jaot-boundary/i.test(
              value,
            )
          ) {
            continue;
          }

          // Extract justification text after "--"
          const dashIdx = value.indexOf("--");

          if (dashIdx === -1) {
            // Bare disable — no justification delimiter at all
            context.report({
              loc: comment.loc,
              messageId: "justificationRequired",
            });
            continue;
          }

          const justification = value.slice(dashIdx + 2).trim();

          // Reject empty or too short (< 25 chars)
          if (!justification || justification.length < 25) {
            context.report({
              loc: comment.loc,
              messageId: "justificationRequired",
            });
            continue;
          }

          // Reject placeholder / low-quality markers (T-11-02-01)
          if (/TODO|FIXME|HACK|XXX/i.test(justification)) {
            context.report({
              loc: comment.loc,
              messageId: "justificationRequired",
            });
            continue;
          }
        }
      },
    };
  },
});
