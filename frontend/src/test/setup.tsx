/// <reference types="vitest/globals" />
import "@testing-library/jest-dom";
import React from "react";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  redirect: vi.fn(),
}));

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Mock next-intl
vi.mock("next-intl", () => ({
  useTranslations: (namespace?: string) => {
    const t = (key: string, values?: Record<string, unknown>) => {
      const fullKey = namespace ? `${namespace}.${key}` : key;
      if (values) {
        return Object.entries(values).reduce(
          (acc, [k, v]) => acc.replace(`{${k}}`, String(v)),
          fullKey
        );
      }
      return fullKey;
    };
    t.rich = t;
    t.markup = t;
    t.raw = (key: string) => key;
    t.has = () => true;
    return t;
  },
  useFormatter: () => ({
    number: (val: number) => String(val),
    dateTime: (val: Date) => val.toISOString(),
    relativeTime: (val: Date) => val.toISOString(),
  }),
  useLocale: () => "en",
  NextIntlClientProvider: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespaceOrOpts?: string | { locale: string; namespace: string }) => {
    const ns = typeof namespaceOrOpts === "string" ? namespaceOrOpts : namespaceOrOpts?.namespace;
    const t = (key: string, values?: Record<string, unknown>) => {
      const fullKey = ns ? `${ns}.${key}` : key;
      if (values) {
        return Object.entries(values).reduce(
          (acc, [k, v]) => acc.replace(`{${k}}`, String(v)),
          fullKey
        );
      }
      return fullKey;
    };
    t.rich = t;
    t.markup = t;
    t.raw = (key: string) => key;
    return t;
  },
}));

// Suppress React Warning noise in test output
const originalConsoleError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    if (typeof args[0] === "string" && args[0].includes("Warning:")) return;
    originalConsoleError(...args);
  };
});
afterAll(() => {
  console.error = originalConsoleError;
});

afterEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});
