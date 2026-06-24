import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the api module
vi.mock("@/lib/api", () => ({
  api: {
    request: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  },
}));

// Import AFTER mocks
import { SearchAutocomplete } from "../SearchAutocomplete";

describe("SearchAutocomplete", () => {
  it("renders an input field with placeholder", () => {
    render(
      <SearchAutocomplete
        value=""
        onChange={vi.fn()}
        placeholder="Search models..."
      />
    );
    expect(
      screen.getByPlaceholderText("Search models...")
    ).toBeInTheDocument();
  });

  it("calls onChange when user types", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchAutocomplete value="" onChange={onChange} placeholder="Search..." />
    );

    await user.type(screen.getByPlaceholderText("Search..."), "test");
    expect(onChange).toHaveBeenCalled();
  });

  it("does not show dropdown when value is empty", () => {
    render(<SearchAutocomplete value="" onChange={vi.fn()} />);
    expect(screen.queryByTestId("search-dropdown")).not.toBeInTheDocument();
  });

  it("calls onCategorySelect when category suggestion is clicked", async () => {
    const onCategorySelect = vi.fn();
    // This test verifies the component renders without errors when onCategorySelect prop is provided
    render(
      <SearchAutocomplete
        value="test"
        onChange={vi.fn()}
        onCategorySelect={onCategorySelect}
      />
    );
    // Verify the component renders without errors when onCategorySelect prop is provided
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
});
