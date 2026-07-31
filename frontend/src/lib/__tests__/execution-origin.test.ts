import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import {
  ORIGIN_CHART_COLORS,
  ORIGIN_KEYS,
  UNKNOWN_ORIGIN_COLOR,
  buildOriginSlices,
  executionOriginHref,
  isOriginKey,
  resolveOriginKey,
} from "../execution-origin";

const LOCALES = ["en", "es", "ca", "fr", "de"] as const;

// vitest runs with `frontend/` as its root (see vitest.config.ts), so the repo is
// one level up. A wrong cwd surfaces as a read error naming the path it tried.
function repoFile(relativeToRepoRoot: string): string {
  return readFileSync(resolve(process.cwd(), "..", relativeToRepoRoot), "utf-8");
}

/** Only the slice these tests read; the bundle itself is far larger. */
interface OriginMessages {
  solve: { origin: Record<string, string> };
}

function originLabels(locale: string): Record<string, string> {
  const parsed = JSON.parse(repoFile(`frontend/messages/${locale}.json`)) as OriginMessages;
  return parsed.solve.origin;
}

/**
 * The origin list is a contract with the backend, not a local convenience: the
 * analytics legend printed "Automatic" three times, and called studio runs
 * automatic, precisely because this side only knew two of the nine slugs. These
 * tests fail when a slug is added on one side only — do not delete them.
 */
describe("origin coverage (contract with the backend)", () => {
  const source = repoFile("app/shared/constants/execution_provenance.py");

  // Read the membership of VALID_ORIGINS, not the ORIGIN_* constants above it:
  // that frozenset is what the backend sanitises against, so it is the set a row
  // can actually hold. A constant declared but left out of it (or a bare literal
  // added straight to it) would make the two disagree.
  const validOrigins = source.match(/VALID_ORIGINS = frozenset\(\s*\{([^}]*)\}/)?.[1] ?? "";
  const constants = new Map(
    [...source.matchAll(/^(ORIGIN_\w+) = "([a-z_]+)"$/gm)].map((m) => [m[1], m[2]])
  );
  const declared = [...validOrigins.matchAll(/(ORIGIN_\w+|"([a-z_]+)")/g)].map(
    (m) => constants.get(m[1]) ?? m[2]
  );

  it("reads the members of VALID_ORIGINS it is asserting against", () => {
    expect(declared.length).toBeGreaterThan(1);
    expect(declared).not.toContain(undefined);
  });

  it("knows every origin the backend can persist", () => {
    // `model_project` is extra on purpose: a source_kind the studio shows in
    // place of the looser origin its runs carry.
    expect([...ORIGIN_KEYS].sort()).toEqual([...declared, "model_project"].sort());
  });

  it("has a label for every origin in all five locales", () => {
    for (const locale of LOCALES) {
      const labels = originLabels(locale);
      for (const key of ORIGIN_KEYS) {
        expect(labels[key], `${locale}.solve.origin.${key}`).toBeTruthy();
      }
    }
  });

  it("gives every origin its own chart colour", () => {
    const used = ORIGIN_KEYS.map((key) => ORIGIN_CHART_COLORS[key]);
    // Half of the reported bug was three origins sharing the fallback grey.
    expect(new Set(used).size).toBe(ORIGIN_KEYS.length);
    expect(used).not.toContain(UNKNOWN_ORIGIN_COLOR);
  });
});

describe("buildOriginSlices", () => {
  // `label` echoes the key so a translated slice and a raw one are told apart.
  const label = (key: string) => `label:${key}`;

  it("gives each origin its own translated label and colour, largest first", () => {
    const slices = buildOriginSlices({ manual: 19, visual_builder: 40, api: 1 }, label);

    expect(slices).toEqual([
      { name: "label:visual_builder", value: 40, fill: ORIGIN_CHART_COLORS.visual_builder },
      { name: "label:manual", value: 19, fill: ORIGIN_CHART_COLORS.manual },
      { name: "label:api", value: 1, fill: ORIGIN_CHART_COLORS.api },
    ]);
  });

  it("is the shape of the reported bug: three origins, three labels, three colours", () => {
    // Before the fix these three collapsed to one label ("Automatic") and one
    // grey, which is what the legend showed three times.
    const slices = buildOriginSlices({ api: 1, marketplace: 4, visual_builder: 10 }, label);

    expect(new Set(slices.map((s) => s.name)).size).toBe(3);
    expect(new Set(slices.map((s) => s.fill)).size).toBe(3);
  });

  it("keeps an unknown slug as stored, with the reserved colour and its own count", () => {
    const slices = buildOriginSlices({ manual: 5, cron: 16 }, label);

    expect(slices).toEqual([
      { name: "cron", value: 16, fill: UNKNOWN_ORIGIN_COLOR },
      { name: "label:manual", value: 5, fill: ORIGIN_CHART_COLORS.manual },
    ]);
  });

  it("never merges two origins into one slice", () => {
    const slices = buildOriginSlices({ manual: 1, cron: 1, mystery: 1 }, label);

    expect(slices).toHaveLength(3);
    expect(slices.reduce((sum, s) => sum + s.value, 0)).toBe(3);
  });

  it("returns nothing for an empty period rather than a zero slice", () => {
    expect(buildOriginSlices({}, label)).toEqual([]);
  });
});

describe("resolveOriginKey", () => {
  it("lets a studio source_kind win over the looser origin slug", () => {
    expect(resolveOriginKey("visual_builder", "model_project")).toBe("model_project");
  });

  it("returns the origin when the slug is known", () => {
    expect(resolveOriginKey("mcp")).toBe("mcp");
  });

  it("returns null for a slug this build does not know, so counts stay honest", () => {
    // Folding it into "manual" would overstate manual in a distribution chart.
    expect(resolveOriginKey("some_future_channel")).toBeNull();
    expect(resolveOriginKey(undefined)).toBeNull();
    expect(isOriginKey("some_future_channel")).toBe(false);
  });
});

describe("executionOriginHref", () => {
  it("routes the visual builder to its document", () => {
    expect(executionOriginHref("visual_builder", "bld_1")).toBe("/builder/bld_1");
  });

  it("routes the AI builder to the chat view of its document", () => {
    expect(executionOriginHref("ai_builder", "bld_2")).toBe("/builder/bld_2/chat");
  });

  it("routes a template run to the template form", () => {
    expect(executionOriginHref("template", "mcat_9")).toBe("/builder/templates/mcat_9");
  });

  it("routes a marketplace run to its project workspace (P1.5 fusion)", () => {
    expect(executionOriginHref("marketplace", "mp_3")).toBe("/studio/mp_3/build");
  });

  it("returns null for imports (no persistent origin)", () => {
    expect(executionOriginHref("import", null)).toBeNull();
  });

  it("returns null when there is no source id", () => {
    expect(executionOriginHref("visual_builder", null)).toBeNull();
    expect(executionOriginHref("visual_builder", undefined)).toBeNull();
  });

  it("returns null for unknown origins", () => {
    expect(executionOriginHref("manual", "x")).toBeNull();
    expect(executionOriginHref(undefined, "x")).toBeNull();
  });

  it("routes a studio model project to its workspace (source_kind wins over the origin slug)", () => {
    expect(executionOriginHref("visual_builder", "mp_42", "model_project")).toBe(
      "/studio/mp_42/build",
    );
  });
});
