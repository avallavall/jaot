import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import {
  ConceptTooltip,
  TooltipSingletonProvider,
} from "@/components/ui/concept-tooltip";
import {
  OPTIMIZATION_TERMS,
  getTermDefinition,
} from "@/lib/optimization-terms";

// Mock useGuidance to control skill level
const mockSkillLevel = vi.fn().mockReturnValue("beginner");
vi.mock("@/contexts/GuidanceContext", () => ({
  useGuidance: () => ({ skillLevel: mockSkillLevel() }),
}));

function renderWithSingleton(ui: React.ReactElement) {
  return render(<TooltipSingletonProvider>{ui}</TooltipSingletonProvider>);
}

describe("ConceptTooltip", () => {
  beforeEach(() => {
    mockSkillLevel.mockReturnValue("beginner");
  });

  it("renders children text", () => {
    renderWithSingleton(
      <ConceptTooltip termKey="shadow-price">Shadow Price</ConceptTooltip>
    );
    expect(screen.getByText("Shadow Price")).toBeInTheDocument();
  });

  it("opens popover content on click", async () => {
    const user = userEvent.setup();
    renderWithSingleton(
      <ConceptTooltip termKey="shadow-price">Shadow Price</ConceptTooltip>
    );

    const trigger = screen.getByRole("button", { name: "Shadow Price" });
    await user.click(trigger);

    // The mock returns the i18n key path: glossary.shadowPrice.definition
    await waitFor(() => {
      expect(screen.getByText("glossary.shadowPrice.definition")).toBeInTheDocument();
    });
  });

  it("closes popover when clicking outside", async () => {
    const user = userEvent.setup();
    renderWithSingleton(
      <div>
        <ConceptTooltip termKey="shadow-price">Shadow Price</ConceptTooltip>
        <span data-testid="outside">Outside</span>
      </div>
    );

    // Open
    const trigger = screen.getByRole("button", { name: "Shadow Price" });
    await user.click(trigger);
    await waitFor(() => {
      expect(screen.getByText("glossary.shadowPrice.definition")).toBeInTheDocument();
    });

    // Click outside to dismiss
    await user.click(screen.getByTestId("outside"));
    await waitFor(() => {
      expect(screen.queryByText("glossary.shadowPrice.definition")).not.toBeInTheDocument();
    });
  });

  it("renders children without popover for unknown termKey", () => {
    const { container } = renderWithSingleton(
      <ConceptTooltip termKey="nonexistent-key">
        Plain Text
      </ConceptTooltip>
    );

    expect(screen.getByText("Plain Text")).toBeInTheDocument();
    // No button wrapper when term is unknown
    expect(container.querySelector("button")).toBeNull();
  });

  it("renders children only for expert skill level", () => {
    mockSkillLevel.mockReturnValue("expert");
    const { container } = renderWithSingleton(
      <ConceptTooltip termKey="shadow-price">Shadow Price</ConceptTooltip>
    );

    expect(screen.getByText("Shadow Price")).toBeInTheDocument();
    expect(container.querySelector("button")).toBeNull();
  });

  it("shows formula toggle when formula exists and reveals formula on click", async () => {
    const user = userEvent.setup();
    renderWithSingleton(
      <ConceptTooltip termKey="base-cost">Base Cost</ConceptTooltip>
    );

    // Open the popover
    await user.click(screen.getByRole("button", { name: "Base Cost" }));

    // "See formula" button uses translation key: glossary.seeFormula
    const formulaBtn = await screen.findByText("glossary.seeFormula");
    expect(formulaBtn).toBeInTheDocument();

    // Click to reveal formula
    await user.click(formulaBtn);
    expect(screen.getByText("1 credit (fixed)")).toBeInTheDocument();
    expect(screen.getByText("glossary.hideFormula")).toBeInTheDocument();

    // Click again to hide
    await user.click(screen.getByText("glossary.hideFormula"));
    expect(screen.queryByText("1 credit (fixed)")).not.toBeInTheDocument();
    expect(screen.getByText("glossary.seeFormula")).toBeInTheDocument();
  });

  it("singleton: opening a second tooltip closes the first", async () => {
    const user = userEvent.setup();
    renderWithSingleton(
      <div>
        <ConceptTooltip termKey="shadow-price">Shadow Price</ConceptTooltip>
        <ConceptTooltip termKey="base-cost">Base Cost</ConceptTooltip>
      </div>
    );

    // Click first tooltip
    await user.click(screen.getByRole("button", { name: "Shadow Price" }));
    await waitFor(() => {
      expect(screen.getByText("glossary.shadowPrice.definition")).toBeInTheDocument();
    });

    // Click second tooltip
    await user.click(screen.getByRole("button", { name: "Base Cost" }));
    await waitFor(() => {
      // First tooltip content should be gone
      expect(screen.queryByText("glossary.shadowPrice.definition")).not.toBeInTheDocument();
      // Second tooltip content should be visible
      expect(
        screen.getByText("glossary.baseCost.definition")
      ).toBeInTheDocument();
    });
  });
});

describe("getTermDefinition", () => {
  it("returns correct term name for known key", () => {
    const result = getTermDefinition("shadow-price");
    expect(result).toBeDefined();
    expect(result!.term).toBe("Shadow Price");
  });

  it("returns undefined for unknown key", () => {
    expect(getTermDefinition("does-not-exist")).toBeUndefined();
  });

  it("includes formula for credit terms", () => {
    const baseCost = getTermDefinition("base-cost");
    expect(baseCost).toBeDefined();
    expect(baseCost!.formula).toBe("1 credit (fixed)");

    const variableCost = getTermDefinition("variable-cost");
    expect(variableCost!.formula).toContain("0.1");
  });
});

describe("OPTIMIZATION_TERMS glossary completeness", () => {
  const requiredTerms = [
    "shadow-price",
    "binding-constraint",
    "slack-value",
    "pareto-front",
    "warm-start",
    "lp-relaxation",
    "objective-value",
    "base-cost",
    "variable-cost",
    "integer-penalty",
    "constraint-cost",
    "time-bonus",
  ];

  it.each(requiredTerms)("includes required term: %s", (termKey) => {
    expect(OPTIMIZATION_TERMS[termKey]).toBeDefined();
    expect(OPTIMIZATION_TERMS[termKey].term).toBeTruthy();
  });

  const creditTerms = [
    "base-cost",
    "variable-cost",
    "integer-penalty",
    "constraint-cost",
    "time-bonus",
  ];

  it.each(creditTerms)("credit term %s has a formula", (termKey) => {
    expect(OPTIMIZATION_TERMS[termKey].formula).toBeTruthy();
  });
});
