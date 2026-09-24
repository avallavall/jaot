import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

/**
 * A list that failed to load said "no keys".
 *
 * The catch swallowed the error and the empty state rendered, so after a 5xx,
 * a 429 or a dropped connection the page told the user they had no API keys
 * and offered to create one, while their integration's key was still there.
 */

const { getKeys } = vi.hoisted(() => ({ getKeys: vi.fn() }));

// ApiError too: getErrorMessage checks `instanceof ApiError`.
vi.mock("@/lib/api", () => ({ api: { getKeys }, ApiError: class ApiError extends Error {} }));
vi.mock("@/components/ui/dialog-custom", () => ({
  useDialog: () => ({
    showError: vi.fn(),
    showSuccess: vi.fn(),
    confirm: vi.fn(),
    DialogComponent: () => null,
  }),
}));
vi.mock("@/hooks/useDateFormat", () => ({ useDateFormat: () => ({ day: () => "" }) }));
vi.mock("@/components/guidance/EmptyState", () => ({
  EmptyState: ({ title }: { title: string }) => <div>{title}</div>,
}));

import ClientAPIKeysPage from "../page";

describe("API keys page", () => {
  it("says the list could not be loaded instead of saying there are no keys", async () => {
    getKeys.mockRejectedValue(Object.assign(new Error("Bad gateway"), { status: 502 }));
    render(<ClientAPIKeysPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("workspace.apiKeys.loadError");
    expect(screen.queryByText("workspace.apiKeys.noKeysTitle")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "common.retry" })).toBeInTheDocument();
  });

  it("still shows the empty state when there really are no keys", async () => {
    getKeys.mockResolvedValue([]);
    render(<ClientAPIKeysPage />);
    expect(await screen.findByText("workspace.apiKeys.noKeysTitle")).toBeInTheDocument();
  });
});
