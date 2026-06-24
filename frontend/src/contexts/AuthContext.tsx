"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { PlanLimits, WorkspaceRole } from "@/lib/types";

interface User {
  id: string;
  name: string;
  email: string | null;
  is_admin: boolean;
  is_org_owner: boolean;
  email_verified?: boolean;
}

interface Organization {
  id: string;
  name: string;
  plan: string;
  credits_balance: number;
}

interface AuthState {
  user: User | null;
  organization: Organization | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  planLimits: PlanLimits | null;
  activeWorkspaceId: string | null;
  activeWorkspaceName: string | null;
  workspaceRole: WorkspaceRole | null;
  isOwner: boolean;
  login: (apiKey: string) => Promise<void>;
  loginWithEmail: (
    email: string,
    password: string,
    rememberMe?: boolean,
  ) => Promise<void>;
  logout: () => void;
  setActiveWorkspace: (id: string | null) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [planLimits, setPlanLimits] = useState<PlanLimits | null>(null);
  const [activeWorkspaceId, setActiveWorkspaceIdState] = useState<
    string | null
  >(null);
  const [activeWorkspaceName, setActiveWorkspaceName] = useState<string | null>(
    null,
  );
  const [workspaceRole, setWorkspaceRole] = useState<WorkspaceRole | null>(
    null,
  );

  const isAuthenticated = !!user;

  // Platform admins (is_admin=true) are NOT silently treated as owners of foreign orgs.
  const isOwner = user?.is_org_owner ?? false;

  const clearAuth = useCallback(() => {
    setUser(null);
    setOrganization(null);
    setPlanLimits(null);
    setActiveWorkspaceIdState(null);
    setActiveWorkspaceName(null);
    setWorkspaceRole(null);
    localStorage.removeItem("jaot_api_key");
    localStorage.removeItem("jaot_user_info");
    localStorage.removeItem("jaot_user");
    localStorage.removeItem("jaot_org");
    localStorage.removeItem("jaot_permissions");
    localStorage.removeItem("jaot_active_workspace");
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logoutSession();
    } catch { /* best-effort: clear local state regardless */ }
    clearAuth();
    router.push("/login");
  }, [clearAuth, router]);

  const login = useCallback(async (apiKey: string) => {
    const result = await api.login(apiKey);
    if (result.success) {
      setUser({
        id: result.user.id,
        name: result.user.name,
        email: result.user.email,
        is_admin: result.user.is_admin,
        is_org_owner: result.user.is_org_owner ?? false,
      });
      const orgExt = result.organization as unknown as Record<string, unknown>;
      setOrganization({
        id: result.organization.id,
        name: result.organization.name,
        plan: result.organization.plan,
        credits_balance: (orgExt.credits_balance as number) || 0,
      });
      localStorage.setItem(
        "jaot_user_info",
        JSON.stringify({
          user: result.user,
          organization: result.organization,
          permissions: result.permissions,
          _expires: Date.now() + 7 * 24 * 60 * 60 * 1000, // 7 days
        }),
      );

      const pendingInviteToken = sessionStorage.getItem("jaot_pending_invite");
      if (pendingInviteToken) {
        sessionStorage.removeItem("jaot_pending_invite");
        try {
          await api.acceptInvite(pendingInviteToken);
        } catch { /* invite may have expired or been revoked */ }
      }
    }
  }, []);

  const loginWithEmail = useCallback(
    async (email: string, password: string, rememberMe: boolean = false) => {
      const result = await api.loginWithEmail(email, password, rememberMe);
      if (result.success) {
        setUser({
          id: result.user.id,
          name: result.user.name,
          email: result.user.email,
          is_admin: result.user.is_admin,
          is_org_owner: result.user.is_org_owner ?? false,
          email_verified: result.email_verified,
        });
        setOrganization({
          id: result.organization.id,
          name: result.organization.name,
          plan: result.organization.plan,
          credits_balance: result.organization.credits_balance,
        });
        // Cookie-based session — no API key in localStorage. Cached user info enables optimistic UI.
        localStorage.setItem(
          "jaot_user_info",
          JSON.stringify({
            user: result.user,
            organization: result.organization,
            permissions: result.permissions,
            _expires: Date.now() + 7 * 24 * 60 * 60 * 1000, // 7 days
          }),
        );

        const pendingInviteToken = sessionStorage.getItem(
          "jaot_pending_invite",
        );
        if (pendingInviteToken) {
          sessionStorage.removeItem("jaot_pending_invite");
          try {
            await api.acceptInvite(pendingInviteToken);
          } catch { /* invite may have expired or been revoked */ }
        }
      }
    },
    [],
  );

  const setActiveWorkspace = useCallback(
    async (id: string | null) => {
      if (!id) {
        setActiveWorkspaceIdState(null);
        setActiveWorkspaceName(null);
        setWorkspaceRole(null);
        localStorage.removeItem("jaot_active_workspace");
        return;
      }

      setActiveWorkspaceIdState(id);
      localStorage.setItem("jaot_active_workspace", id);

      try {
        const [workspace, members] = await Promise.all([
          api.getWorkspace(id),
          api.listMembers(id),
        ]);
        setActiveWorkspaceName(workspace.name);
        const currentUserId = user?.id;
        const myMembership = members.find((m) => m.user_id === currentUserId);
        if (myMembership) {
          setWorkspaceRole(myMembership.role);
        } else if (isOwner) {
          // Org owner without explicit membership gets admin-equivalent access.
          setWorkspaceRole("admin");
        } else {
          setWorkspaceRole(null);
        }
      } catch {
        // Fetch failed — fall back to null role (still allows isOwner bypass).
        setActiveWorkspaceName(null);
        if (isOwner) {
          setWorkspaceRole("admin");
        } else {
          setWorkspaceRole(null);
        }
      }
    },
    [user?.id, isOwner],
  );

  // Validate existing session (API key or JWT cookie) and restore workspace on mount.
  useEffect(() => {
    const restoreWorkspace = async (userId: string, isAdmin: boolean) => {
      const savedWorkspaceId = localStorage.getItem("jaot_active_workspace");
      if (savedWorkspaceId) {
        setActiveWorkspaceIdState(savedWorkspaceId);
        try {
          const [workspace, members] = await Promise.all([
            api.getWorkspace(savedWorkspaceId),
            api.listMembers(savedWorkspaceId),
          ]);
          setActiveWorkspaceName(workspace.name);
          const myMembership = members.find((m) => m.user_id === userId);
          if (myMembership) {
            setWorkspaceRole(myMembership.role);
          } else if (isAdmin) {
            setWorkspaceRole("admin");
          }
        } catch {
          // Saved workspace no longer accessible — clear it and auto-select.
          localStorage.removeItem("jaot_active_workspace");
          setActiveWorkspaceIdState(null);
          await autoSelectWorkspace(userId, isAdmin);
        }
        return;
      }

      await autoSelectWorkspace(userId, isAdmin);
    };

    const autoSelectWorkspace = async (userId: string, isAdmin: boolean) => {
      try {
        const workspaces = await api.listWorkspaces(1, 1);
        if (workspaces.items.length > 0) {
          const ws = workspaces.items[0];
          setActiveWorkspaceIdState(ws.id);
          setActiveWorkspaceName(ws.name);
          localStorage.setItem("jaot_active_workspace", ws.id);
          try {
            const members = await api.listMembers(ws.id);
            const myMembership = members.find((m) => m.user_id === userId);
            if (myMembership) {
              setWorkspaceRole(myMembership.role);
            } else if (isAdmin) {
              setWorkspaceRole("admin");
            }
          } catch {
            if (isAdmin) setWorkspaceRole("admin");
          }
        }
      } catch { /* no workspaces available */ }
    };

    const validateSession = async () => {
      // Purge expired PII from localStorage.
      const storedInfo = localStorage.getItem("jaot_user_info");
      if (storedInfo) {
        try {
          const parsed = JSON.parse(storedInfo);
          if (parsed._expires && Date.now() > parsed._expires) {
            localStorage.removeItem("jaot_user_info");
          }
        } catch {
          localStorage.removeItem("jaot_user_info");
        }
      }

      const key = localStorage.getItem("jaot_api_key");

      // Try /me with cookies even if no API key — supports cookie-based sessions.
      if (!key) {
        try {
          const me = await api.getMe();
          setUser({
            id: me.user_id,
            name: me.user_name,
            email: me.user_email ?? null,
            is_admin: me.is_admin,
            is_org_owner: me.is_org_owner ?? false,
            email_verified:
              ((me as unknown as Record<string, unknown>).email_verified as
                | boolean
                | undefined) ?? false,
          });
          setOrganization({
            id: me.organization_id,
            name: me.organization_name,
            plan: me.plan,
            credits_balance: me.credits_balance,
          });
          setPlanLimits(me.plan_limits ?? null);
          await restoreWorkspace(me.user_id, me.is_admin);
        } catch { /* no valid session */ } finally {
          setIsLoading(false);
        }
        return;
      }

      try {
        const me = await api.getMe();
        const loadedUser: User = {
          id: me.user_id,
          name: me.user_name,
          email: me.user_email ?? null,
          is_admin: me.is_admin,
          is_org_owner: me.is_org_owner ?? false,
          email_verified:
            ((me as unknown as Record<string, unknown>).email_verified as
              | boolean
              | undefined) ?? false,
        };
        setUser(loadedUser);
        setOrganization({
          id: me.organization_id,
          name: me.organization_name,
          plan: me.plan,
          credits_balance: me.credits_balance,
        });
        setPlanLimits(me.plan_limits ?? null);
        await restoreWorkspace(me.user_id, me.is_admin);
      } catch {
        clearAuth();
      } finally {
        setIsLoading(false);
      }
    };

    validateSession();
  }, [clearAuth]);

  return (
    <AuthContext.Provider
      value={{
        user,
        organization,
        isAuthenticated,
        isLoading,
        planLimits,
        activeWorkspaceId,
        activeWorkspaceName,
        workspaceRole,
        isOwner,
        login,
        loginWithEmail,
        logout,
        setActiveWorkspace,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
