import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { pageLocale } from "../page-locale";

/**
 * Numbers follow the page's language, not the browser's.
 *
 * `toLocaleString(undefined, …)` used the browser's language, while every ICU
 * message on the same screen used the page's. A Spanish page on an English
 * system showed `1,234.5` next to `1.234,5`.
 */
describe("pageLocale", () => {
  afterEach(() => {
    document.documentElement.lang = "";
  });

  it("is the language of the page", () => {
    document.documentElement.lang = "es";
    expect(pageLocale()).toBe("es");
    expect((1234.5).toLocaleString(pageLocale())).toBe("1234,5");
    expect((12345.5).toLocaleString(pageLocale())).toBe("12.345,5");
  });

  it("is undefined when the page does not say", () => {
    expect(pageLocale()).toBeUndefined();
  });
});

describe("a component", () => {
  afterEach(() => {
    vi.doUnmock("next-intl");
    vi.resetModules();
  });

  it("formats its numbers in the page's language", async () => {
    vi.resetModules();
    vi.doMock("next-intl", () => ({
      useLocale: () => "de",
      useTranslations: () => (key: string) => key,
    }));
    const { SolveFactCard } = await import("@/components/solve/SolveFactCard");
    render(<SolveFactCard status="optimal" objectiveValue={12345.678} nodes={1500} />);
    expect(screen.getByText("12.345,678")).toBeInTheDocument();
    expect(screen.getByText("1.500")).toBeInTheDocument();
  });
});
