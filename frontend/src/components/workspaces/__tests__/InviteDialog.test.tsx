/**
 * The invite dialog, driven like the QA pass drove it (2026-09-25).
 *
 * Three defects: the shareable link was the bare path "/join/<token>", on screen
 * and on the clipboard; a link generated a moment ago was missing from "Pending
 * Invites" until the dialog was reopened; and the copy and revoke buttons were
 * icons with no accessible name.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const listInvites = vi.fn();
const createLinkInvite = vi.fn();
const revokeInvite = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      listInvites: (...a: unknown[]) => listInvites(...a),
      createLinkInvite: (...a: unknown[]) => createLinkInvite(...a),
      revokeInvite: (...a: unknown[]) => revokeInvite(...a),
      createEmailInvite: vi.fn(),
    },
  };
});

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ workspaceRole: "admin" }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { InviteDialog, absoluteInviteLink } from "../InviteDialog";

const linkInvite = {
  id: "inv_link",
  workspace_id: "wks_1",
  role: "editor",
  method: "link",
  invitee_email: null,
  created_at: "2026-09-25T10:00:00Z",
  expires_at: "2026-10-02T10:00:00Z",
  is_revoked: false,
};

describe("InviteDialog", () => {
  beforeEach(() => {
    listInvites.mockReset().mockResolvedValue([]);
    createLinkInvite.mockReset().mockResolvedValue({
      invite_url: "/join/tok_abc",
      expires_at: "2026-10-02T10:00:00Z",
    });
    revokeInvite.mockReset().mockResolvedValue(undefined);
  });

  it("builds the link on the page's own origin", () => {
    expect(absoluteInviteLink("/join/tok_abc", "https://jaot.example")).toBe(
      "https://jaot.example/join/tok_abc",
    );
  });

  // CONTRACT-TEST: the shareable link is absolute, on screen and on the clipboard.
  it("shows and copies an absolute link", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<InviteDialog workspaceId="wks_1" open onClose={() => {}} />);

    await user.click(screen.getByRole("tab", { name: "workspace.invite.shareableLink" }));
    await user.click(screen.getByRole("button", { name: "workspace.invite.generateLink" }));

    const expected = `${window.location.origin}/join/tok_abc`;
    expect(await screen.findByDisplayValue(expected)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "workspace.invite.copyLink" }));
    expect(writeText).toHaveBeenCalledWith(expected);
  });

  it("lists a link it just generated without being reopened", async () => {
    const user = userEvent.setup();
    listInvites.mockResolvedValueOnce([]).mockResolvedValue([linkInvite]);
    render(<InviteDialog workspaceId="wks_1" open onClose={() => {}} />);
    await waitFor(() => expect(listInvites).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("tab", { name: "workspace.invite.shareableLink" }));
    await user.click(screen.getByRole("button", { name: "workspace.invite.generateLink" }));

    expect(await screen.findByText("workspace.invite.pendingInvites")).toBeInTheDocument();
    // The role is named in the reader's language, not as the raw value.
    expect(screen.getByText("workspace.invite.roles.editor")).toBeInTheDocument();
    expect(screen.queryByText("editor")).not.toBeInTheDocument();
  });

  it("gives the revoke button a name", async () => {
    const user = userEvent.setup();
    listInvites.mockResolvedValue([linkInvite]);
    render(<InviteDialog workspaceId="wks_1" open onClose={() => {}} />);

    const revoke = await screen.findByRole("button", { name: "workspace.invite.revokeInvite" });
    await user.click(revoke);
    expect(revokeInvite).toHaveBeenCalledWith("wks_1", "inv_link");
  });
});
