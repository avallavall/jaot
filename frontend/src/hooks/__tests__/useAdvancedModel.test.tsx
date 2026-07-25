import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act, render, screen } from "@testing-library/react";

import { useAdvancedModel } from "../useAdvancedModel";

function TwoPanels() {
  const [a, setA] = useAdvancedModel();
  const [b] = useAdvancedModel();
  return (
    <div>
      <button type="button" onClick={() => setA(!a)} data-testid="flip">
        flip
      </button>
      <span data-testid="panel-a">{String(a)}</span>
      <span data-testid="panel-b">{String(b)}</span>
    </div>
  );
}

describe("useAdvancedModel", () => {
  beforeEach(() => localStorage.clear());

  it("defaults to the cheap tier", () => {
    const { result } = renderHook(() => useAdvancedModel());
    expect(result.current[0]).toBe(false);
  });

  it("remembers the choice across mounts", () => {
    const first = renderHook(() => useAdvancedModel());
    act(() => first.result.current[1](true));

    const second = renderHook(() => useAdvancedModel());
    expect(second.result.current[0]).toBe(true);
  });

  // The studio sends through its provider while the toggle lives in the chat
  // panel: two copies of this preference would send the tier the user did NOT
  // pick, so every reader has to see a flip at once.
  it("keeps every reader in sync within the same page", async () => {
    render(<TwoPanels />);
    expect(screen.getByTestId("panel-b").textContent).toBe("false");

    await act(async () => {
      screen.getByTestId("flip").click();
    });

    expect(screen.getByTestId("panel-a").textContent).toBe("true");
    expect(screen.getByTestId("panel-b").textContent).toBe("true");
  });
});
