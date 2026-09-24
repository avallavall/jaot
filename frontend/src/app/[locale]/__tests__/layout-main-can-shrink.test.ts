/**
 * Every app shell's <main> can shrink to the phone's width.
 *
 * The shells lay out a sidebar and <main className="flex-1"> in a flex row. A
 * flex child does not shrink below its content unless it has `min-w-0`, so a
 * wide table stretched the whole page instead of scrolling inside its own
 * `overflow-x-auto` box: 790 px on the comparer and 509 px on an execution page
 * on a 390 px phone (driving the app, 2026-09-25). Only the workspace shell had
 * the class.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const APP = path.resolve(__dirname, "..");

function layouts(): string[] {
  return fs
    .readdirSync(APP, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => path.join(APP, d.name, "layout.tsx"))
    .filter((f) => fs.existsSync(f));
}

describe("app shells", () => {
  it("finds the shells it should check", () => {
    const names = layouts().map((f) => path.basename(path.dirname(f)));
    expect(names).toEqual(expect.arrayContaining(["solve", "studio", "admin", "workspace"]));
  });

  it("gives every flex-1 <main> min-w-0", () => {
    const offenders: string[] = [];
    for (const file of layouts()) {
      const source = fs.readFileSync(file, "utf8");
      for (const match of source.matchAll(/<main\b[^>]*className="([^"]*)"/g)) {
        const classes = match[1].split(/\s+/);
        if (classes.includes("flex-1") && !classes.includes("min-w-0")) {
          offenders.push(`${path.basename(path.dirname(file))}: ${match[1]}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
