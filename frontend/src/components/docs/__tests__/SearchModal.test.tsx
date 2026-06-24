import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { SearchModal } from "../SearchModal";

// Mock the search-index module
const mockSearchDocs = vi.fn();
vi.mock("@/lib/docs/search-index", () => ({
  searchDocs: (...args: unknown[]) => mockSearchDocs(...args),
}));

// Mock useRouter push
const mockPush = vi.fn();
vi.mock("next/navigation", async () => {
  return {
    useRouter: () => ({
      push: mockPush,
      replace: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    }),
    usePathname: () => "/docs",
    useSearchParams: () => new URLSearchParams(),
  };
});

const mockResults = [
  {
    id: 0,
    title: "Authentication",
    description: "Learn how to authenticate with the JAOT API",
    slug: "api/authentication",
    content: "API key and JWT authentication",
    section: "api",
  },
  {
    id: 1,
    title: "Quick Start",
    description: "Get started with the JAOT API",
    slug: "getting-started/quick-start",
    content: "Go from zero to solving your first optimization problem",
    section: "getting-started",
  },
];

describe("SearchModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockSearchDocs.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders search trigger button", () => {
    render(<SearchModal />);
    expect(screen.getByLabelText("Search documentation")).toBeInTheDocument();
    expect(screen.getByText("Search docs...")).toBeInTheDocument();
  });

  it("opens modal when Ctrl+K is pressed", async () => {
    render(<SearchModal />);

    act(() => {
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    });

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type to search documentation...")
      ).toBeInTheDocument();
    });
  });

  it("opens modal when Meta+K (Cmd+K) is pressed", async () => {
    render(<SearchModal />);

    act(() => {
      fireEvent.keyDown(document, { key: "k", metaKey: true });
    });

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type to search documentation...")
      ).toBeInTheDocument();
    });
  });

  it("opens modal when trigger button is clicked", async () => {
    render(<SearchModal />);

    await act(async () => {
      fireEvent.click(screen.getByLabelText("Search documentation"));
    });

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type to search documentation...")
      ).toBeInTheDocument();
    });
  });

  it("displays initial placeholder when no query entered", async () => {
    render(<SearchModal />);

    act(() => {
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    });

    await waitFor(() => {
      // Should show the placeholder text in the results area
      const placeholders = screen.getAllByText("Type to search documentation...");
      expect(placeholders.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows search results after typing", async () => {
    mockSearchDocs.mockResolvedValue(mockResults);
    render(<SearchModal />);

    // Open modal
    act(() => {
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    });

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type to search documentation...")
      ).toBeInTheDocument();
    });

    // Type in search -- use query that won't split result text via highlighting
    const input = screen.getByPlaceholderText("Type to search documentation...");
    await act(async () => {
      fireEvent.change(input, { target: { value: "api" } });
    });

    // Wait for debounce
    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    // Results contain text that may be split by highlight spans, so use function matcher
    await waitFor(() => {
      const resultButtons = screen.getAllByRole("button").filter(
        (btn) => btn.textContent?.includes("Authentication") || btn.textContent?.includes("Quick Start")
      );
      expect(resultButtons.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("shows no results message for unmatched query", async () => {
    mockSearchDocs.mockResolvedValue([]);
    render(<SearchModal />);

    act(() => {
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    });

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type to search documentation...")
      ).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText("Type to search documentation...");
    await act(async () => {
      fireEvent.change(input, { target: { value: "xyznonexistent" } });
    });

    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    await waitFor(() => {
      expect(screen.getByText(/No results found/)).toBeInTheDocument();
    });
  });

  it("navigates to result page when clicking a result", async () => {
    mockSearchDocs.mockResolvedValue(mockResults);
    render(<SearchModal />);

    // Open and search
    act(() => {
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    });

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type to search documentation...")
      ).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText("Type to search documentation...");
    await act(async () => {
      fireEvent.change(input, { target: { value: "api" } });
    });

    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    // Find the result button containing "Authentication" text
    let authButton: HTMLElement | undefined;
    await waitFor(() => {
      authButton = screen.getAllByRole("button").find(
        (btn) => btn.textContent?.includes("Authentication")
      );
      expect(authButton).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(authButton!);
    });

    expect(mockPush).toHaveBeenCalledWith("/docs/api/authentication");
  });

  it("calls searchDocs with the query value", async () => {
    mockSearchDocs.mockResolvedValue([]);
    render(<SearchModal />);

    act(() => {
      fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    });

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Type to search documentation...")
      ).toBeInTheDocument();
    });

    const input = screen.getByPlaceholderText("Type to search documentation...");
    await act(async () => {
      fireEvent.change(input, { target: { value: "SDK" } });
    });

    await act(async () => {
      vi.advanceTimersByTime(250);
    });

    expect(mockSearchDocs).toHaveBeenCalledWith("SDK");
  });
});
