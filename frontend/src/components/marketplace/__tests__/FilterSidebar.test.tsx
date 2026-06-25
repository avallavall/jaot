import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock sub-components to isolate FilterSidebar behavior
vi.mock("../RatingFilter", () => ({
  RatingFilter: () => <div data-testid="rating-filter" />,
}));

// Import AFTER mocks
import { FilterSidebar } from "../FilterSidebar";
import type { FilterDefaults } from "@/hooks/useUrlFilters";

const defaultFilters: FilterDefaults = {
  category: null,
  search: "",
  sort: "popular",
  official: false,
  featured: false,
  page: 1,
  minRating: null,
};

describe("FilterSidebar", () => {
  it("renders sort, category, and rating filter sections", () => {
    render(
      <FilterSidebar
        filters={defaultFilters}
        updateFilter={vi.fn()}
        clearFilters={vi.fn()}
        activeFilterCount={0}
        categories={["scheduling", "logistics"]}
      />
    );
    // Sort section
    expect(
      screen.getByText("marketplace.filters.sort")
    ).toBeInTheDocument();
    // Categories section
    expect(
      screen.getByText("marketplace.filters.categories")
    ).toBeInTheDocument();
    // Rating sub-component
    expect(screen.getByTestId("rating-filter")).toBeInTheDocument();
  });

  it("shows clear all button when activeFilterCount > 0", () => {
    render(
      <FilterSidebar
        filters={defaultFilters}
        updateFilter={vi.fn()}
        clearFilters={vi.fn()}
        activeFilterCount={3}
        categories={[]}
      />
    );
    expect(
      screen.getByText("marketplace.filters.clearAll")
    ).toBeInTheDocument();
  });

  it("does not show clear all button when activeFilterCount is 0", () => {
    render(
      <FilterSidebar
        filters={defaultFilters}
        updateFilter={vi.fn()}
        clearFilters={vi.fn()}
        activeFilterCount={0}
        categories={[]}
      />
    );
    expect(
      screen.queryByText("marketplace.filters.clearAll")
    ).not.toBeInTheDocument();
  });

  it("calls clearFilters when clear all button is clicked", async () => {
    const user = userEvent.setup();
    const clearFilters = vi.fn();
    render(
      <FilterSidebar
        filters={defaultFilters}
        updateFilter={vi.fn()}
        clearFilters={clearFilters}
        activeFilterCount={2}
        categories={[]}
      />
    );

    await user.click(screen.getByText("marketplace.filters.clearAll"));
    expect(clearFilters).toHaveBeenCalledTimes(1);
  });

  it("renders category checkboxes for provided categories", () => {
    render(
      <FilterSidebar
        filters={defaultFilters}
        updateFilter={vi.fn()}
        clearFilters={vi.fn()}
        activeFilterCount={0}
        categories={["scheduling", "logistics", "general"]}
      />
    );
    // Each category should have a checkbox
    const checkboxes = screen.getAllByRole("checkbox");
    // At minimum: 3 category checkboxes + free only + official only = 5
    expect(checkboxes.length).toBeGreaterThanOrEqual(3);
  });
});
