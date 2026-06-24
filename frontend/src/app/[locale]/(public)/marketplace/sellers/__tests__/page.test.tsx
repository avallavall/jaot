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
    usePathname: () => "/marketplace/sellers/org-123",
    useSearchParams: () => new URLSearchParams(),
  };
});

// Import AFTER mocks - now importing the client component directly
import { SellerProfileClient } from "@/components/marketplace/SellerProfileClient";
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

describe("SellerProfileClient", () => {
  beforeEach(() => {
    mockGetOrgProfile.mockResolvedValue(mockProfile);
    mockGetOrgModels.mockResolvedValue([]);
  });

  it("renders org name after loading", async () => {
    render(<SellerProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(screen.getByText("Test Organization")).toBeInTheDocument();
    });
  });

  it("shows verified badge when org is verified", async () => {
    render(<SellerProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(
        screen.getByText("marketplace.sellerProfile.verified")
      ).toBeInTheDocument();
    });
  });

  it("does not show verified badge when org is not verified", async () => {
    mockGetOrgProfile.mockResolvedValue({
      ...mockProfile,
      is_verified: false,
    });
    render(<SellerProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(screen.getByText("Test Organization")).toBeInTheDocument();
    });
    expect(
      screen.queryByText("marketplace.sellerProfile.verified")
    ).not.toBeInTheDocument();
  });

  it("displays bio section when bio exists", async () => {
    render(<SellerProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(
        screen.getByText("We build great optimization models.")
      ).toBeInTheDocument();
    });
  });

  it("shows empty state when seller has no models", async () => {
    mockGetOrgModels.mockResolvedValue([]);
    render(<SellerProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(
        screen.getByText("marketplace.sellerProfile.noModels")
      ).toBeInTheDocument();
    });
  });

  it("renders model cards when seller has models", async () => {
    mockGetOrgModels.mockResolvedValue([
      { id: "m1", display_name: "Model One" },
      { id: "m2", display_name: "Model Two" },
    ]);
    render(<SellerProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(screen.getAllByTestId("model-card")).toHaveLength(2);
    });
  });

  it("shows back to marketplace link", async () => {
    render(<SellerProfileClient orgId="org-123" />);
    await waitFor(() => {
      expect(
        screen.getByText("marketplace.sellerProfile.backToMarketplace")
      ).toBeInTheDocument();
    });
  });
});
