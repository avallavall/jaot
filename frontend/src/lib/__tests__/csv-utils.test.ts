import { describe, it, expect } from "vitest";
import { quoteCell } from "@/lib/csv-utils";

describe("quoteCell", () => {
  it("wraps a plain value in quotes", () => {
    expect(quoteCell("plant A")).toBe('"plant A"');
  });

  it("doubles an internal quote, per RFC 4180", () => {
    expect(quoteCell('say "hi"')).toBe('"say ""hi"""');
  });

  it("writes an empty cell for null and undefined", () => {
    expect(quoteCell(null)).toBe('""');
    expect(quoteCell(undefined)).toBe('""');
  });

  // A model, dataset or variable name is written by a person. Excel and
  // LibreOffice run a cell that opens with = + - @ as a formula even inside
  // quotes, so the name has to reach the sheet as text.
  it.each(["=1+1", "+1+1", "@SUM(A1)", "-lorries", "\tlead"])(
    "keeps %s out of the formula bar",
    (name) => {
      expect(quoteCell(name)).toBe(`"'${name}"`);
    },
  );

  it("keeps a command name out of the formula bar and still doubles its quotes", () => {
    expect(quoteCell('=cmd|" /C calc"!A0')).toBe('"\'=cmd|"" /C calc""!A0"');
  });

  it("leaves a number a number, sign and all", () => {
    expect(quoteCell(-5)).toBe('"-5"');
    expect(quoteCell("-5")).toBe('"-5"');
    expect(quoteCell("-0.0031")).toBe('"-0.0031"');
    expect(quoteCell("-1e-9")).toBe('"-1e-9"');
    expect(quoteCell("+1")).toBe('"+1"');
  });
});
