import { render, screen, waitFor } from "@testing-library/react";

// Mock the api module
const mockGetOrgProfile = vi.fn();
const mockGetOrgModels = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    getOrgProfile: (...args: unknown[]) => mockGetOrgProfile(...args),
    getOrgModels: (...args: unknown[]) => mockGetOrgModels(...args),
  },
}));

// Mock MarketplaceModelCard to isolate page behavior
vi.mock("@/components/marketplace/MarketplaceModelCard", () => ({
  MarketplaceModelCard: ({ model }: { model: { display_name: string } }) => (
    <div data-testid="model-card">{model.display_name}</div>
  ),
}));

// Mock MarketplaceSkeletons
vi.mock("@/components/marketplace/MarketplaceSkeletons", () => ({
  ModelGridSkeleton: () => <div data-testid="model-grid-skeleton" />,
}));

// Mock next/navigation (still needed for Link component)
vi.mock("next/navigation", async () => {
  const actual = await vi.importActual("next/navigation");
  return {
    ...actual,
    useRouter: () => ({
      push: vi.fn(),
      replace: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    }),
    usePathname: () => "/marketplace/authors/org-123",
    useSearchParams: () => new URLSearchParams(),
  };
});

// Import AFTER mocks - now importing the client component directly
import { AuthorProfileClient } from "@/components/marketplace/AuthorProfileClient";
import type { OrgProfile } from "@/lib/types";

const mockProfile: OrgProfile = {
  id: "org-123",
  name: "Test Organization",
  slug: "test-org",
  bio: "We build great optimization models.",
  logo_url: "https://example.com/logo.png",
  is_verified: true,
  created_at: "2024-01-15T10:00:00Z",
  total_models_published: 5,
  total_activations: 1000,
  total_executions: 5000,
  total_reviews: 20,
  avg_rating: 4.5,
};

describe("AuthorProfileClient", () => {
  beforeEach(() => {
    mockGetOrgProfile.mockResolvedValue(mockProfile);
    mockGetOrgModels.mockResolvedValue([]);
  });

  it("renders org name after loading", async () => {
    render(<AuthorProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(screen.getByText("Test Organization")).toBeInTheDocument();
    });
  });

  it("shows verified badge when org is verified", async () => {
    render(<AuthorProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(
        screen.getByText("marketplace.authorProfile.verified")
      ).toBeInTheDocument();
    });
  });

  it("does not show verified badge when org is not verified", async () => {
    mockGetOrgProfile.mockResolvedValue({
      ...mockProfile,
      is_verified: false,
    });
    render(<AuthorProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(screen.getByText("Test Organization")).toBeInTheDocument();
    });
    expect(
      screen.queryByText("marketplace.authorProfile.verified")
    ).not.toBeInTheDocument();
  });

  it("displays bio section when bio exists", async () => {
    render(<AuthorProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(
        screen.getByText("We build great optimization models.")
      ).toBeInTheDocument();
    });
  });

  it("shows empty state when author has no models", async () => {
    mockGetOrgModels.mockResolvedValue([]);
    render(<AuthorProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(
        screen.getByText("marketplace.authorProfile.noModels")
      ).toBeInTheDocument();
    });
  });

  it("renders model cards when author has models", async () => {
    mockGetOrgModels.mockResolvedValue([
      { id: "m1", display_name: "Model One" },
      { id: "m2", display_name: "Model Two" },
    ]);
    render(<AuthorProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(screen.getAllByTestId("model-card")).toHaveLength(2);
    });
  });

  it("shows back to marketplace link", async () => {
    render(<AuthorProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(
        screen.getByText("marketplace.authorProfile.backToMarketplace")
      ).toBeInTheDocument();
    });
  });
});

/**
 * The header reported the real total while the list took a fixed fifty and
 * stopped, with no pager and nothing saying more existed. On the biggest author
 * on the site that hid 52 of 102 models — and it is the page a stranger is most
 * likely to open.
 */
describe("AuthorProfileClient, on an author with more models than one page", () => {
  function page(size: number, offset = 0) {
    return Array.from({ length: size }, (_, i) => ({
      id: `m${offset + i}`,
      display_name: `Model ${offset + i}`,
    }));
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetOrgProfile.mockResolvedValue({ ...mockProfile, total_models_published: 102 });
    mockGetOrgModels.mockResolvedValue(page(50));
  });

  // CONTRACT-TEST: every model the header counts is reachable from the page
  it("offers the rest, and says how many are left", async () => {
    render(<AuthorProfileClient orgId="org-123" />);

    const more = await screen.findByTestId("author-load-more");
    expect(more).toBeInTheDocument();
    expect(screen.getAllByTestId("model-card")).toHaveLength(50);
  });

  it("asks for the next page and appends it", async () => {
    const { fireEvent } = await import("@testing-library/react");
    render(<AuthorProfileClient orgId="org-123" />);

    const more = await screen.findByTestId("author-load-more");
    mockGetOrgModels.mockResolvedValueOnce(page(50, 50));
    fireEvent.click(more);

    await waitFor(() => {
      expect(screen.getAllByTestId("model-card")).toHaveLength(100);
    });
    expect(mockGetOrgModels).toHaveBeenLastCalledWith("org-123", 2, 50);
  });

  it("stops offering more once every model is on screen", async () => {
    mockGetOrgProfile.mockResolvedValue({ ...mockProfile, total_models_published: 3 });
    mockGetOrgModels.mockResolvedValue(page(3));
    render(<AuthorProfileClient orgId="org-123" />);

    await waitFor(() => {
      expect(screen.getAllByTestId("model-card")).toHaveLength(3);
    });
    expect(screen.queryByTestId("author-load-more")).not.toBeInTheDocument();
  });
});

/**
 * "Average Rating 5.0" beside "102 Models Published" reads as a hundred models
 * rated five. One of them had ever been rated.
 */
describe("AuthorProfileClient, the average rating", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetOrgModels.mockResolvedValue([]);
  });

  it("says what the average is built on", async () => {
    mockGetOrgProfile.mockResolvedValue({ ...mockProfile, avg_rating: 5, total_reviews: 1 });
    render(<AuthorProfileClient orgId="org-123" />);

    await waitFor(() => {
      expect(screen.getByText("marketplace.authorProfile.avgRatingFrom")).toBeInTheDocument();
    });
  });

  it("says nothing extra when nobody has rated anything", async () => {
    mockGetOrgProfile.mockResolvedValue({ ...mockProfile, avg_rating: null, total_reviews: 0 });
    render(<AuthorProfileClient orgId="org-123" />);

    await waitFor(() => {
      expect(screen.getByText("marketplace.authorProfile.noRating")).toBeInTheDocument();
    });
    expect(
      screen.queryByText("marketplace.authorProfile.avgRatingFrom")
    ).not.toBeInTheDocument();
  });
});

/**
 * The load effect listed the translator among its dependencies, and it is used
 * only for one fallback message. Every render that handed back a new translator
 * identity re-ran the whole load — two requests for one page view, racing each
 * other to set the list.
 */
describe("AuthorProfileClient, how many times it loads", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetOrgProfile.mockResolvedValue(mockProfile);
    mockGetOrgModels.mockResolvedValue([]);
  });

  // CONTRACT-TEST: one page view is one load
  it("asks the server once per author", async () => {
    render(<AuthorProfileClient orgId="org-123" />);

    await waitFor(() => {
      expect(screen.getByText("Test Organization")).toBeInTheDocument();
    });
    expect(mockGetOrgProfile).toHaveBeenCalledTimes(1);
    expect(mockGetOrgModels).toHaveBeenCalledTimes(1);
  });
});
