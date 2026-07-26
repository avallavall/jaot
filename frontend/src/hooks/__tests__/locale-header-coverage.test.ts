import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

/**
 * Every client surface that makes the backend GENERATE prose must tell it which
 * language the reader is reading in, via the `X-JAOT-Locale` header that
 * `localeHeader()` builds.
 *
 * This is checked structurally rather than per hook because the bug it guards
 * against is one of omission: `useExplanationStream` — the hook behind "Explain
 * model" and "Explain version diff" — built its headers by hand and simply never
 * included it, so those two explanations came back in English however the app
 * was being read, while its sibling hooks were correct. A behavioural test on
 * the hooks that exist today would not have caught a fifth one being added the
 * same way.
 */

const SRC = path.resolve(__dirname, "../..");

/** Files that POST to an endpoint which streams or returns generated text. */
const GENERATING_SURFACES = [
  "hooks/useExplanationStream.ts",
  "hooks/useInfeasibilityExplanation.ts",
  "hooks/useSolutionExplanation.ts",
  "hooks/useSSE.ts",
  "lib/api.ts",
];

describe("X-JAOT-Locale coverage", () => {
  it.each(GENERATING_SURFACES)("%s sends the reader's locale", (relative) => {
    const source = fs.readFileSync(path.join(SRC, relative), "utf-8");
    expect(source).toContain("localeHeader()");
  });

  // CONTRACT-TEST: catches a NEW generating surface added without the header.
  it("no other file hand-builds a request to an LLM endpoint", () => {
    const offenders: string[] = [];

    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === "__tests__" || entry.name === "generated") continue;
          walk(full);
          continue;
        }
        if (!/\.tsx?$/.test(entry.name)) continue;

        const source = fs.readFileSync(full, "utf-8");
        const relative = path.relative(SRC, full).replace(/\\/g, "/");
        if (GENERATING_SURFACES.includes(relative)) continue;

        // A hand-rolled fetch at an LLM route: the shape that skips api.ts and
        // therefore skips its locale header.
        const callsLlmDirectly =
          source.includes("fetch(") && /\/api\/v2\/llm\/|explain-/.test(source);
        if (callsLlmDirectly && !source.includes("localeHeader")) {
          offenders.push(relative);
        }
      }
    };
    walk(SRC);

    expect(offenders).toEqual([]);
  });
});
