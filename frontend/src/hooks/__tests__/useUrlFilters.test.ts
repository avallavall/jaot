import { renderHook, act } from "@testing-library/react";
import { useUrlFilters } from "../useUrlFilters";

// Override the global mock for useSearchParams with a controllable version
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

// Mock window.history.replaceState
const replaceStateSpy = vi.fn();
Object.defineProperty(window, "history", {
  value: { replaceState: replaceStateSpy },
  writable: true,
});

// Mock window.location.pathname
Object.defineProperty(window, "location", {
  value: { pathname: "/marketplace" },
  writable: true,
});

beforeEach(() => {
  mockSearchParams = new URLSearchParams();
  replaceStateSpy.mockClear();
});

describe("useUrlFilters", () => {
  describe("parseFromUrl - defaults", () => {
    it("returns defaults when URL has no params", () => {
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.filters).toEqual({
        category: null,
        search: "",
        sort: "popular",
        official: false,
        featured: false,
        page: 1,
        minRating: null,
      });
    });
  });

  describe("parseFromUrl - reads valid params", () => {
    it("reads all valid URL params", () => {
      mockSearchParams = new URLSearchParams(
        "category=logistics&search=routing&sort=newest&official=true&featured=true&page=3"
      );
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.filters).toEqual({
        category: "logistics",
        search: "routing",
        sort: "newest",
        official: true,
        featured: true,
        page: 3,
        minRating: null,
      });
    });
  });

  describe("parseFromUrl - invalid sort", () => {
    it("falls back to 'popular' for invalid sort value", () => {
      mockSearchParams = new URLSearchParams("sort=banana");
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.filters.sort).toBe("popular");
    });
  });

  describe("parseFromUrl - invalid page", () => {
    it("falls back to 1 for negative page", () => {
      mockSearchParams = new URLSearchParams("page=-5");
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.filters.page).toBe(1);
    });

    it("falls back to 1 for non-numeric page", () => {
      mockSearchParams = new URLSearchParams("page=abc");
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.filters.page).toBe(1);
    });
  });

  describe("parseFromUrl - unknown category", () => {
    it("accepts unknown category as-is (validated server-side)", () => {
      mockSearchParams = new URLSearchParams("category=nonexistent");
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.filters.category).toBe("nonexistent");
    });
  });

  describe("activeFilterCount", () => {
    it("returns 0 when all defaults", () => {
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.activeFilterCount).toBe(0);
    });

    it("counts each non-default filter (not page)", () => {
      mockSearchParams = new URLSearchParams(
        "category=logistics&search=test&sort=newest&official=true&featured=true&page=3"
      );
      const { result } = renderHook(() => useUrlFilters());
      // category + search + sort + official + featured = 5 (page excluded)
      expect(result.current.activeFilterCount).toBe(5);
    });

    it("counts only the filters that differ from defaults", () => {
      mockSearchParams = new URLSearchParams("category=logistics&official=true");
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.activeFilterCount).toBe(2);
    });
  });

  describe("updateFilter", () => {
    it("sets category and resets page to 1", () => {
      mockSearchParams = new URLSearchParams("page=3");
      const { result } = renderHook(() => useUrlFilters());
      expect(result.current.filters.page).toBe(3);

      act(() => {
        result.current.updateFilter("category", "logistics");
      });

      expect(result.current.filters.category).toBe("logistics");
      expect(result.current.filters.page).toBe(1);
    });

    it("sets page without resetting page", () => {
      const { result } = renderHook(() => useUrlFilters());

      act(() => {
        result.current.updateFilter("page", 3);
      });

      expect(result.current.filters.page).toBe(3);
    });
  });

  describe("clearFilters", () => {
    it("resets all to defaults", () => {
      mockSearchParams = new URLSearchParams(
        "category=logistics&search=test&sort=newest&official=true&featured=true&page=3"
      );
      const { result } = renderHook(() => useUrlFilters());

      act(() => {
        result.current.clearFilters();
      });

      expect(result.current.filters).toEqual({
        category: null,
        search: "",
        sort: "popular",
        official: false,
        featured: false,
        page: 1,
        minRating: null,
      });
    });
  });

  describe("syncToUrl", () => {
    it("omits default values from URL (clean path for all-defaults)", () => {
      const { result } = renderHook(() => useUrlFilters());

      act(() => {
        result.current.clearFilters();
      });

      // Should call replaceState with clean path (no query string)
      expect(replaceStateSpy).toHaveBeenCalledWith(
        null,
        "",
        "/marketplace"
      );
    });

    it("includes only non-default values in URL", () => {
      const { result } = renderHook(() => useUrlFilters());

      act(() => {
        result.current.updateFilter("category", "logistics");
      });

      // Should include only category= in the URL
      const lastCall = replaceStateSpy.mock.calls[replaceStateSpy.mock.calls.length - 1];
      const url = lastCall[2] as string;
      expect(url).toContain("category=logistics");
      expect(url).not.toContain("sort=");
      expect(url).not.toContain("search=");
      expect(url).not.toContain("page=");
      expect(url).not.toContain("free=");
      expect(url).not.toContain("official=");
      expect(url).not.toContain("featured=");
    });
  });
});
