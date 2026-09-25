import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

// Twelve industry guides pointed at builder screenshots that were never added to
// public/, so each page showed a broken image and logged a 404. Every image a
// docs page links by an absolute path must exist in public/.
const ROOT = path.resolve(__dirname, "../../../..");
const DOCS = path.join(ROOT, "content", "docs");
const PUBLIC = path.join(ROOT, "public");

function mdxFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return mdxFiles(full);
    return entry.name.endsWith(".mdx") ? [full] : [];
  });
}

describe("docs images", () => {
  it("every absolute image path in the docs exists in public/", () => {
    const missing: string[] = [];
    for (const file of mdxFiles(DOCS)) {
      const source = fs.readFileSync(file, "utf8");
      const links = [
        ...source.matchAll(/!\[[^\]]*\]\((\/[^)\s]+)\)/g),
        ...source.matchAll(/<img[^>]*\ssrc="(\/[^"]+)"/g),
      ];
      for (const [, src] of links) {
        if (!fs.existsSync(path.join(PUBLIC, src))) {
          missing.push(`${path.relative(DOCS, file)} -> ${src}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });
});
