import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const { mockUseAuth, mockApi } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
  mockApi: {
    getOrgAnthropicKey: vi.fn(),
    setOrgAnthropicKey: vi.fn(),
    clearOrgAnthropicKey: vi.fn(),
  },
}));

vi.mock("@/contexts/AuthContext", () => ({ useAuth: mockUseAuth }));
vi.mock("@/lib/api", () => ({ api: mockApi }));

import { AnthropicKeySettings } from "../AnthropicKeySettings";
import { ByokHint } from "@/components/llm/ByokHint";

describe("AnthropicKeySettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the input + save button for an owner with no key", async () => {
    mockUseAuth.mockReturnValue({ user: { is_org_owner: true } });
    mockApi.getOrgAnthropicKey.mockResolvedValue({ enabled: false, hint: null });

    render(<AnthropicKeySettings />);

    expect(await screen.findByText("settings.byok.inactive")).toBeInTheDocument();
    expect(screen.getByText("settings.byok.save")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("settings.byok.placeholder")).toBeInTheDocument();
  });

  it("shows the active state + hint + remove button when a key is set", async () => {
    mockUseAuth.mockReturnValue({ user: { is_org_owner: true } });
    mockApi.getOrgAnthropicKey.mockResolvedValue({ enabled: true, hint: "sk-ant-…1234" });

    render(<AnthropicKeySettings />);

    expect(await screen.findByText("settings.byok.active")).toBeInTheDocument();
    expect(screen.getByText("sk-ant-…1234")).toBeInTheDocument();
    expect(screen.getByText("settings.byok.remove")).toBeInTheDocument();
  });

  it("hides the editor and shows an owner-only note for non-owners", async () => {
    mockUseAuth.mockReturnValue({ user: { is_org_owner: false } });
    mockApi.getOrgAnthropicKey.mockResolvedValue({ enabled: false, hint: null });

    render(<AnthropicKeySettings />);

    expect(await screen.findByText("settings.byok.ownerOnly")).toBeInTheDocument();
    expect(screen.queryByText("settings.byok.save")).not.toBeInTheDocument();
  });
});

describe("ByokHint", () => {
  it("renders the nudge text and a link to settings", () => {
    render(<ByokHint />);
    expect(screen.getByText("settings.byok.hintText")).toBeInTheDocument();
    const link = screen.getByText("settings.byok.hintLink").closest("a");
    expect(link).toHaveAttribute("href", "/en/workspace/settings");
  });
});
