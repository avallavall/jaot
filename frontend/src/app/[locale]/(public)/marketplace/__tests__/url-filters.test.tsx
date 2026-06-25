/**
 * Vitest unit tests for marketplace URL filter state management.
 *
 * Replaces frontend/e2e/url-filters.spec.ts (demoted — tests client-side
 * URL-state logic, not a real integration boundary). See plan 11-05 (P11-REFACTOR-08).
 *
 * These tests verify the URL filter state sync behavior at the marketplace level:
 * - URL params are parsed to filter state (sort, free, official, search, category)
 * - Filter mutations sync back to URL via window.history.replaceState
 * - Invalid params fall back to defaults (sort=banana → popular)
 * - Multiple filters combine correctly in URL
 * - clearFilters resets to clean path
 *
 * Tests use useUrlFilters hook directly — this is the correct unit for marketplace
 * filter state. Component-level filter UI is covered by FilterSidebar.test.tsx.
 */
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useUrlFilters, DEFAULTS, VALID_SORTS } from "@/hooks/useUrlFilters";

// ── Mock overrides ──────────────────────────────────────────────────────────
// The global setup.tsx mocks next/navigation with a static URLSearchParams.
// We need a controllable version for filter state tests.

let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", async () => {
  const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
  return {
    ...actual,
    useSearchParams: () => mockSearchParams,
    useRouter: () => ({
      push: vi.fn(),
      replace: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    }),
    usePathname: () => "/marketplace",
  };
});

const replaceStateSpy = vi.fn();
Object.defineProperty(window, "history", {
  value: { replaceState: replaceStateSpy },
  writable: true,
});
Object.defineProperty(window, "location", {
  value: { pathname: "/marketplace" },
  writable: true,
});

beforeEach(() => {
  mockSearchParams = new URLSearchParams();
  replaceStateSpy.mockClear();
});

// ── Tests ───────────────────────────────────────────────────────────────────

describe("Marketplace URL filters — page loads with clean URL (no params)", () => {
  it("all filter state matches DEFAULTS when URL has no params", () => {
    const { result } = renderHook(() => useUrlFilters());
    expect(result.current.filters).toEqual(DEFAULTS);
    expect(result.current.activeFilterCount).toBe(0);
  });
});

describe("Marketplace URL filters — sort syncs to URL", () => {
  it("sort=newest appears in URL after updateFilter", () => {
    const { result } = renderHook(() => useUrlFilters());
    act(() => {
      result.current.updateFilter("sort", "newest");
    });
    const lastUrl = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1]?.[2];
    expect(lastUrl).toContain("sort=newest");
  });

  it("sort=popular (default) is omitted from URL", () => {
    const { result } = renderHook(() => useUrlFilters());
    act(() => {
      result.current.updateFilter("sort", "popular");
    });
    const lastUrl = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1]?.[2];
    expect(lastUrl).not.toContain("sort=");
  });
});

describe("Marketplace URL filters — official checkbox syncs to URL", () => {
  it("official=true appears in URL after setting official filter", () => {
    const { result } = renderHook(() => useUrlFilters());
    act(() => {
      result.current.updateFilter("official", true);
    });
    const lastUrl = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1]?.[2];
    expect(lastUrl).toContain("official=true");
    expect(result.current.filters.official).toBe(true);
  });

  it("official=false (default) is omitted from URL", () => {
    const { result } = renderHook(() => useUrlFilters());
    act(() => {
      result.current.updateFilter("official", false);
    });
    const lastUrl = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1]?.[2];
    expect(lastUrl).not.toContain("official=");
  });
});

describe("Marketplace URL filters — search input syncs to URL after debounce", () => {
  it("search=routing appears in URL after setting search filter", () => {
    const { result } = renderHook(() => useUrlFilters());
    act(() => {
      result.current.updateFilter("search", "routing");
    });
    const lastUrl = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1]?.[2];
    expect(lastUrl).toContain("search=routing");
  });

  it("empty search is omitted from URL", () => {
    const { result } = renderHook(() => useUrlFilters());
    act(() => {
      result.current.updateFilter("search", "");
    });
    const lastUrl = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1]?.[2];
    expect(lastUrl).not.toContain("search=");
  });
});

describe("Marketplace URL filters — multiple filters combine in URL", () => {
  it("sort + official + search combine correctly", () => {
    const { result } = renderHook(() => useUrlFilters());
    act(() => {
      result.current.updateFilter("sort", "newest");
    });
    act(() => {
      result.current.updateFilter("official", true);
    });
    act(() => {
      result.current.updateFilter("search", "budget");
    });
    expect(result.current.filters.sort).toBe("newest");
    expect(result.current.filters.official).toBe(true);
    expect(result.current.filters.search).toBe("budget");
    expect(result.current.activeFilterCount).toBe(3);
  });
});

describe("Marketplace URL filters — URL params restore filter state on direct navigation", () => {
  it("sort=newest&official=true&search=knapsack restores all three filters", () => {
    mockSearchParams = new URLSearchParams("sort=newest&official=true&search=knapsack");
    const { result } = renderHook(() => useUrlFilters());
    expect(result.current.filters.sort).toBe("newest");
    expect(result.current.filters.official).toBe(true);
    expect(result.current.filters.search).toBe("knapsack");
  });
});

describe("Marketplace URL filters — invalid URL params fall back to defaults", () => {
  it("sort=banana falls back to 'popular'", () => {
    mockSearchParams = new URLSearchParams("sort=banana");
    const { result } = renderHook(() => useUrlFilters());
    expect(result.current.filters.sort).toBe("popular");
  });

  it("page=-5 falls back to 1", () => {
    mockSearchParams = new URLSearchParams("page=-5");
    const { result } = renderHook(() => useUrlFilters());
    expect(result.current.filters.page).toBe(1);
  });
});

describe("Marketplace URL filters — clearFilters resets URL to clean path", () => {
  it("clearFilters resets to DEFAULTS and cleans URL", () => {
    mockSearchParams = new URLSearchParams("sort=newest&free=true&search=routing");
    const { result } = renderHook(() => useUrlFilters());

    act(() => {
      result.current.clearFilters();
    });

    expect(result.current.filters).toEqual(DEFAULTS);
    expect(result.current.activeFilterCount).toBe(0);

    const lastUrl = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1]?.[2];
    expect(lastUrl).toBe("/marketplace");
  });
});

describe("Marketplace URL filters — VALID_SORTS contract", () => {
  it("all sort options from the E2E spec are in VALID_SORTS", () => {
    // These are the exact sort values the E2E url-filters.spec.ts asserted on.
    // They must remain valid to keep the marketplace filtering working.
    expect(VALID_SORTS).toContain("popular");
    expect(VALID_SORTS).toContain("newest");
    expect(VALID_SORTS).toContain("rating");
    expect(VALID_SORTS).toHaveLength(3);
  });
});
