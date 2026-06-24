import { render, screen } from "@testing-library/react";

// Mock embla-carousel-autoplay (will be installed in Task 2)
vi.mock("embla-carousel-autoplay", () => ({
  default: () => ({
    name: "autoplay",
  }),
}));

// Mock the carousel UI components
vi.mock("@/components/ui/carousel", () => ({
  Carousel: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="carousel">{children}</div>
  ),
  CarouselContent: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="carousel-content">{children}</div>
  ),
  CarouselItem: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="carousel-item">{children}</div>
  ),
  CarouselPrevious: () => (
    <button data-testid="carousel-prev">Previous</button>
  ),
  CarouselNext: () => <button data-testid="carousel-next">Next</button>,
}));

// Import AFTER mocks
import { FeaturedCarousel } from "../FeaturedCarousel";
import type { ModelCatalogItem } from "@/lib/types";

function makeModel(
  overrides: Partial<ModelCatalogItem> = {}
): ModelCatalogItem {
  return {
    id: "model-1",
    name: "test_model",
    display_name: "Test Model",
    description: "A test model",
    short_description: "Short desc",
    category: "scheduling",
    tags: ["test"],
    version: "1.0.0",
    is_official: false,
    is_featured: true,
    price_eur: 0,
    credits_per_execution: 0,
    total_activations: 42,
    total_executions: 100,
    avg_rating: 4.5,
    author_organization_id: "org-1",
    author_name: "Test Org",
    author_verified: true,
    logo_url: null,
    screenshot_urls: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("FeaturedCarousel", () => {
  it("renders nothing when models array is empty", () => {
    const { container } = render(<FeaturedCarousel models={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders carousel with model slides when models provided", () => {
    const models = [
      makeModel({ id: "m1", display_name: "Model One" }),
      makeModel({ id: "m2", display_name: "Model Two" }),
    ];
    render(<FeaturedCarousel models={models} />);
    expect(screen.getByTestId("carousel")).toBeInTheDocument();
    expect(screen.getAllByTestId("carousel-item")).toHaveLength(2);
  });

  it("displays model name and description in each slide", () => {
    render(
      <FeaturedCarousel
        models={[
          makeModel({
            display_name: "Alpha Model",
            short_description: "Alpha desc",
          }),
        ]}
      />
    );
    expect(screen.getByText("Alpha Model")).toBeInTheDocument();
    expect(screen.getByText("Alpha desc")).toBeInTheDocument();
  });

  it("shows navigation arrows", () => {
    render(<FeaturedCarousel models={[makeModel()]} />);
    expect(screen.getByTestId("carousel-prev")).toBeInTheDocument();
    expect(screen.getByTestId("carousel-next")).toBeInTheDocument();
  });
});
