import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CodeTabs, CodeTabProvider } from "../CodeTabs";

// Mock shiki so tests don't load WASM
vi.mock("shiki", () => ({
  codeToHtml: vi.fn(
    (code: string, opts: { lang: string }) =>
      `<pre><code class="language-${opts.lang}">${code}</code></pre>`
  ),
}));

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(window, "localStorage", { value: localStorageMock });

function renderWithProvider(ui: React.ReactElement) {
  return render(<CodeTabProvider>{ui}</CodeTabProvider>);
}

const sampleTabs = [
  { language: "python", code: 'print("hello")' },
  { language: "javascript", code: 'console.log("hello")' },
];

describe("CodeTabs", () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.clearAllMocks();
  });

  it("renders tab triggers for each tab", () => {
    renderWithProvider(<CodeTabs tabs={sampleTabs} />);

    expect(screen.getByRole("tab", { name: /python/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /javascript/i })).toBeInTheDocument();
  });

  it("shows only the active tab content", () => {
    renderWithProvider(<CodeTabs tabs={sampleTabs} />);

    // Default is python
    const pythonPanel = screen.getByRole("tabpanel");
    expect(pythonPanel).toHaveTextContent('print("hello")');
  });

  it("switches tabs on click", async () => {
    const user = userEvent.setup();
    renderWithProvider(<CodeTabs tabs={sampleTabs} />);

    await user.click(screen.getByRole("tab", { name: /javascript/i }));
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent('console.log("hello")');
  });

  it("defaults to python tab when no localStorage value", () => {
    renderWithProvider(<CodeTabs tabs={sampleTabs} />);

    const pythonTab = screen.getByRole("tab", { name: /python/i });
    expect(pythonTab).toHaveAttribute("data-state", "active");
  });

  it("persists tab selection to localStorage", async () => {
    const user = userEvent.setup();
    renderWithProvider(<CodeTabs tabs={sampleTabs} />);

    await user.click(screen.getByRole("tab", { name: /javascript/i }));
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      "docs-code-tab",
      "javascript"
    );
  });

  it("restores tab selection from localStorage", () => {
    localStorageMock.getItem.mockReturnValue("javascript");

    renderWithProvider(<CodeTabs tabs={sampleTabs} />);

    const jsTab = screen.getByRole("tab", { name: /javascript/i });
    expect(jsTab).toHaveAttribute("data-state", "active");
  });

  it("renders cURL tab with correct label", () => {
    renderWithProvider(
      <CodeTabs tabs={[{ language: "curl", code: "curl http://example.com" }]} />
    );

    expect(screen.getByRole("tab", { name: /curl/i })).toBeInTheDocument();
  });

  it("returns null for empty tabs", () => {
    const { container } = renderWithProvider(<CodeTabs tabs={[]} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("CodeTabProvider", () => {
  beforeEach(() => {
    localStorageMock.clear();
    vi.clearAllMocks();
  });

  it("renders children", () => {
    render(
      <CodeTabProvider>
        <div data-testid="child">Hello</div>
      </CodeTabProvider>
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });
});
