import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";

// --- Mocks ---

const mockUseAuth = vi.fn();
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

const mockUsePermission = vi.fn();
vi.mock("@/hooks/usePermission", () => ({
  usePermission: (role: string) => mockUsePermission(role),
}));

import { useNavItems } from "@/components/layout/nav-items";

// --- Helpers ---

interface NavItem {
  label: string;
  href: string;
  icon: unknown;
  children?: NavItem[];
  external?: boolean;
  collapsedByDefault?: boolean;
}

/** Section headers are separator items: href="#", no children, icon is null */
function getSectionHeaders(items: NavItem[]): NavItem[] {
  return items.filter(
    (item) => item.href === "#" && !item.children && item.icon === null
  );
}

/** Recursively find an item by href (searches flat + nested children) */
function findItemByHref(items: NavItem[], href: string): NavItem | undefined {
  for (const item of items) {
    if (item.href === href) return item;
    if (item.children) {
      const found = findItemByHref(item.children, href);
      if (found) return found;
    }
  }
  return undefined;
}

/** Find a collapsible group by href (has children array) */
function findCollapsibleByHref(
  items: NavItem[],
  href: string
): NavItem | undefined {
  return items.find((item) => item.href === href && item.children);
}

/** Collect all unique hrefs (flat + nested), excluding anchor-only hrefs */
function collectAllHrefs(items: NavItem[]): Set<string> {
  const hrefs = new Set<string>();
  for (const item of items) {
    if (item.href && !item.href.startsWith("#")) {
      hrefs.add(item.href);
    }
    if (item.children) {
      for (const child of item.children) {
        if (child.href && !child.href.startsWith("#")) {
          hrefs.add(child.href);
        }
      }
    }
  }
  return hrefs;
}

/** Find collapsible groups (items with children) */
function getCollapsibleGroups(items: NavItem[]): NavItem[] {
  return items.filter((item) => item.children && item.children.length > 0);
}

/** Find a collapsible group by label */
function findCollapsibleByLabel(
  items: NavItem[],
  label: string
): NavItem | undefined {
  return items.find((item) => item.label === label && item.children);
}

// --- Auth state presets ---

function setAuthState(opts: {
  isAdmin?: boolean;
  hasWorkspace?: boolean;
}) {
  mockUseAuth.mockReturnValue({
    user: { id: "usr_1", name: "Test", email: "test@test.com", is_admin: opts.isAdmin ?? false },
    activeWorkspaceId: opts.hasWorkspace ? "ws_123" : null,
    activeWorkspaceName: opts.hasWorkspace ? "Test Workspace" : null,
    isOwner: opts.isAdmin ?? false,
    workspaceRole: opts.isAdmin ? "admin" : "viewer",
    isAuthenticated: true,
    isLoading: false,
  });
  mockUsePermission.mockReturnValue(opts.isAdmin ?? false);
}

// --- Tests ---
// Labels are now translation keys rendered by the mock as "common.nav.<key>"

describe("useNavItems", () => {
  describe("NAV-01: Section structure", () => {
    it("admin user with workspace sees 3 primary separators + 4 collapsible groups", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());
      const headers = getSectionHeaders(result.current);
      const headerLabels = headers.map((h) => h.label);

      // 3 primary separator headers (always visible)
      expect(headerLabels).toContain("common.nav.build");
      expect(headerLabels).toContain("common.nav.discover");
      expect(headerLabels).toContain("common.nav.activity");
      expect(headers).toHaveLength(3);

      // 4 collapsible groups: Community, Account, Team, Admin
      const collapsibles = getCollapsibleGroups(result.current);
      const collapsibleLabels = collapsibles.map((c) => c.label);
      expect(collapsibleLabels).toContain("common.nav.community");
      expect(collapsibleLabels).toContain("common.nav.account");
      expect(collapsibleLabels).toContain("common.nav.team");
      expect(collapsibleLabels).toContain("common.nav.adminPanel");
      expect(collapsibles).toHaveLength(4);
    });

    it("non-admin without workspace sees 3 primary separators + 2 collapsible groups", () => {
      setAuthState({ isAdmin: false, hasWorkspace: false });
      const { result } = renderHook(() => useNavItems());
      const headers = getSectionHeaders(result.current);
      const headerLabels = headers.map((h) => h.label);

      // 3 primary separator headers
      expect(headerLabels).toContain("common.nav.build");
      expect(headerLabels).toContain("common.nav.discover");
      expect(headerLabels).toContain("common.nav.activity");
      expect(headers).toHaveLength(3);

      // 2 collapsible groups: Community, Account (no Team, no Admin)
      const collapsibles = getCollapsibleGroups(result.current);
      const collapsibleLabels = collapsibles.map((c) => c.label);
      expect(collapsibleLabels).toContain("common.nav.community");
      expect(collapsibleLabels).toContain("common.nav.account");
      expect(collapsibleLabels).not.toContain("common.nav.team");
      expect(collapsibleLabels).not.toContain("common.nav.adminPanel");
      expect(collapsibles).toHaveLength(2);
    });

    it("admin without workspace sees 3 primary separators + 3 collapsible groups (no Team)", () => {
      setAuthState({ isAdmin: true, hasWorkspace: false });
      const { result } = renderHook(() => useNavItems());
      const headers = getSectionHeaders(result.current);

      expect(headers).toHaveLength(3);

      const collapsibles = getCollapsibleGroups(result.current);
      const collapsibleLabels = collapsibles.map((c) => c.label);
      expect(collapsibleLabels).toContain("common.nav.community");
      expect(collapsibleLabels).toContain("common.nav.account");
      expect(collapsibleLabels).toContain("common.nav.adminPanel");
      expect(collapsibleLabels).not.toContain("common.nav.team");
      expect(collapsibles).toHaveLength(3);
    });

    it("non-admin with workspace sees 3 primary separators + 3 collapsible groups (no Admin)", () => {
      setAuthState({ isAdmin: false, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());
      const headers = getSectionHeaders(result.current);

      expect(headers).toHaveLength(3);

      const collapsibles = getCollapsibleGroups(result.current);
      const collapsibleLabels = collapsibles.map((c) => c.label);
      expect(collapsibleLabels).toContain("common.nav.community");
      expect(collapsibleLabels).toContain("common.nav.account");
      expect(collapsibleLabels).toContain("common.nav.team");
      expect(collapsibleLabels).not.toContain("common.nav.adminPanel");
      expect(collapsibles).toHaveLength(3);
    });
  });

  describe("NAV-02: Previously missing pages", () => {
    it("Build section has Templates entry at /builder/templates", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());
      const templates = findItemByHref(result.current, "/builder/templates");

      expect(templates).toBeDefined();
      expect(templates!.label).toBe("common.nav.templates");
    });

    it("Team collapsible has Team Members at /workspace/team when workspace active", () => {
      setAuthState({ isAdmin: false, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());
      const teamMembers = findItemByHref(result.current, "/workspace/team");

      expect(teamMembers).toBeDefined();
      expect(teamMembers!.label).toBe("common.nav.teamMembers");
    });

    it("Team collapsible has Audit Log at /workspace/audit when admin + workspace", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());
      const auditLog = findItemByHref(result.current, "/workspace/audit");

      expect(auditLog).toBeDefined();
      expect(auditLog!.label).toBe("common.nav.auditLog");
    });
  });

  describe("NAV-03: Admin section", () => {
    it("Admin Panel collapsible has exactly 9 children with correct hrefs and is collapsed by default", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());
      // Find Admin Panel collapsible by checking for a child with href "/admin"
      const adminPanel = result.current.find(
        (item: NavItem) => item.children && item.children.some((c: NavItem) => c.href === "/admin")
      );

      expect(adminPanel).toBeDefined();
      expect(adminPanel!.collapsedByDefault).toBe(true);
      expect(adminPanel!.children).toHaveLength(13);

      const expectedHrefs = [
        "/admin",
        "/admin/organizations",
        "/admin/users",
        "/admin/models",
        "/admin/api-keys",
        "/admin/executions",
        "/admin/reviews",
        "/admin/credits",
        "/admin/marketplace/analytics",
        "/admin/marketplace/promotions",
        "/admin/marketplace/seller-analytics",
        "/admin/marketplace/verification",
        "/admin/settings",
      ];
      const childHrefs = adminPanel!.children!.map((c: NavItem) => c.href);
      expect(childHrefs).toEqual(expectedHrefs);
    });
  });

  describe("NAV-04: Account and Team are collapsible groups", () => {
    it("Account and Team are separate collapsible groups with icons", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());

      const account = findCollapsibleByLabel(result.current, "common.nav.account");
      const team = findCollapsibleByLabel(result.current, "common.nav.team");

      expect(account).toBeDefined();
      expect(team).toBeDefined();
      // They are collapsible groups with href anchors
      expect(account!.href).toBe("#account");
      expect(account!.icon).not.toBeNull();
      expect(account!.collapsedByDefault).toBe(true);
      expect(team!.href).toBe("#team");
      expect(team!.icon).not.toBeNull();
      expect(team!.collapsedByDefault).toBe(true);
    });

    it("Account collapsible includes personal items (Dashboard, Profile, API Keys, Credits, Usage, Settings)", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());

      const account = findCollapsibleByLabel(result.current, "common.nav.account");
      expect(account).toBeDefined();
      const childLabels = account!.children!.map((c: NavItem) => c.label);

      expect(childLabels).toContain("common.nav.dashboard");
      expect(childLabels).toContain("common.nav.myProfile");
      expect(childLabels).toContain("common.nav.apiKeys");
      expect(childLabels).toContain("common.nav.credits");
      expect(childLabels).toContain("common.nav.usage");
      expect(childLabels).toContain("common.nav.settings");
    });

    it("Team collapsible includes workspace items (Organization, Workspaces, Team Members, Audit Log)", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());

      const team = findCollapsibleByLabel(result.current, "common.nav.team");
      expect(team).toBeDefined();
      const childLabels = team!.children!.map((c: NavItem) => c.label);

      expect(childLabels).toContain("common.nav.organization");
      expect(childLabels).toContain("common.nav.workspaces");
      expect(childLabels).toContain("common.nav.teamMembers");
      expect(childLabels).toContain("common.nav.auditLog");
    });
  });

  describe("NAV-05: All pages discoverable", () => {
    it("has at least 20 unique href values across all nav items", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());
      const hrefs = collectAllHrefs(result.current);

      // All page hrefs should start with /
      const pageHrefs = new Set(
        [...hrefs].filter((h) => h.startsWith("/"))
      );

      expect(pageHrefs.size).toBeGreaterThanOrEqual(20);
    });
  });

  describe("NAV-06: Collapsed by default behavior", () => {
    it("Account, Team, and Admin groups have collapsedByDefault set to true", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());

      const account = findCollapsibleByLabel(result.current, "common.nav.account");
      const team = findCollapsibleByLabel(result.current, "common.nav.team");
      const admin = result.current.find(
        (item: NavItem) => item.children && item.children.some((c: NavItem) => c.href === "/admin")
      );

      expect(account!.collapsedByDefault).toBe(true);
      expect(team!.collapsedByDefault).toBe(true);
      expect(admin!.collapsedByDefault).toBe(true);
    });

    it("Community group does NOT have collapsedByDefault (it uses backend filtering instead)", () => {
      setAuthState({ isAdmin: true, hasWorkspace: true });
      const { result } = renderHook(() => useNavItems());

      const community = findCollapsibleByHref(result.current, "#community");
      expect(community).toBeDefined();
      expect(community!.collapsedByDefault).toBeUndefined();
    });
  });
});
