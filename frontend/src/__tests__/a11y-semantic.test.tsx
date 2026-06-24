import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

// Read component source files for structural assertions
const dialogCustomPath = path.resolve(
  __dirname,
  "../components/ui/dialog-custom.tsx"
);
const dialogCustomContent = fs.readFileSync(dialogCustomPath, "utf-8");

const sidebarPath = path.resolve(
  __dirname,
  "../components/layout/sidebar.tsx"
);
const sidebarContent = fs.readFileSync(sidebarPath, "utf-8");

describe("Semantic HTML structure (A11Y-07)", () => {
  it('dialog-custom.tsx imports from shadcn/ui dialog (Radix-based)', () => {
    // The custom dialog should delegate to the Radix-based shadcn Dialog
    // instead of building its own <div>-based dialog
    const importsFromDialog =
      dialogCustomContent.includes('from "@/components/ui/dialog"') ||
      dialogCustomContent.includes("from './dialog'") ||
      dialogCustomContent.includes('from "./dialog"');
    expect(importsFromDialog).toBe(true);
  });

  it("dialog-custom.tsx uses DialogContent component", () => {
    // Should use the accessible DialogContent wrapper from Radix
    expect(dialogCustomContent).toContain("DialogContent");
  });

  it("sidebar.tsx title is not an h1 element", () => {
    // The sidebar title should NOT be an <h1> — the page content should own
    // the <h1>. Sidebar title should use a lower heading level or a <span>/<p>.
    // This avoids multiple <h1> elements per page (poor heading hierarchy).
    const hasH1 = /<h1[\s>]/.test(sidebarContent);
    expect(hasH1).toBe(false);
  });
});
