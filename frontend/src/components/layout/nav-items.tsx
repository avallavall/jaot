"use client";

import {
  Zap,
  ClipboardList,
  LayoutDashboard,
  Wrench,
  ShoppingBag,
  Key,
  Settings,
  User,
  Building2,
  Heart,
  BarChart2,
  Webhook,
  Users,
  ScrollText,
  Scale,
  MessageSquare,
  Bug,
  LayoutTemplate,
  Activity,
  Package,
  Plus,
  Flag,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import { FEEDBACK_URL } from "@/lib/community";

export function useNavItems() {
  const { activeWorkspaceId, user } = useAuth();
  // Two different "admin" scopes, and conflating them leaks the platform console:
  // usePermission("admin") is workspace-scoped and returns true for any org owner
  // (everyone who signs up owns the org they create), while /admin/* is gated on
  // the platform-admin flag — the same one ProtectedRoute enforces.
  const isWorkspaceAdmin = usePermission("admin");
  const isPlatformAdmin = user?.is_admin ?? false;
  const hasWorkspace = !!activeWorkspaceId;
  const t = useTranslations("common");

  return [

    // The single "Model, Analyze & Solve" hub — the home of model work. Post-P1.5
    // fusion the studio IS the one door: canvas/assistant/editor/JModel are Build
    // lenses and the launcher covers every creation path, so the legacy /builder
    // entries left the nav (the routes stay reachable for deep links).
    { label: t("nav.modelAnalyzeSolve"), href: "#", icon: null },
    { label: t("nav.myModels"), href: "/studio", icon: <Zap className="w-4 h-4" /> },
    { label: t("nav.newModel"), href: "/studio/new", icon: <Plus className="w-4 h-4" /> },
    { label: t("nav.templates"), href: "/studio/templates", icon: <LayoutTemplate className="w-4 h-4" /> },
    // Both of these are finished screens that nothing linked to: reachable only by
    // typing the URL, so in practice they did not exist (owner, 2026-08-02: surface
    // them rather than delete them).
    { label: t("nav.multiObjective"), href: "/solve/multi-objective", icon: <Scale className="w-4 h-4" /> },
    { label: t("nav.customSolve"), href: "/solve/custom", icon: <Wrench className="w-4 h-4" /> },

    { label: t("nav.discover"), href: "#", icon: null },
    { label: t("nav.marketplace"), href: "/marketplace", icon: <ShoppingBag className="w-4 h-4" /> },
    // P1.5 fusion: the legacy "Activated Models" entry is gone — a marketplace
    // model is used by forking it into the studio ("My Models" above).
    { label: t("nav.favorites"), href: "/solve/favorites", icon: <Heart className="w-4 h-4" /> },

    { label: t("nav.activity"), href: "#", icon: null },
    { label: t("nav.executions"), href: "/solve/executions", icon: <ClipboardList className="w-4 h-4" /> },
    { label: t("nav.solveAnalytics"), href: "/solve/analytics", icon: <TrendingUp className="w-4 h-4" /> },
    { label: t("nav.triggers"), href: "/triggers", icon: <Webhook className="w-4 h-4" /> },

    {
      label: t("nav.community"),
      href: "#community",
      icon: <Users className="w-4 h-4" />,
      children: [
        {
          label: t("nav.communityForum"),
          href: "#discourse",
          icon: <MessageSquare className="w-4 h-4" />,
          external: true,
        },
        {
          label: t("nav.feedbackAndBugs"),
          href: FEEDBACK_URL,
          icon: <Bug className="w-4 h-4" />,
          external: true,
        },
      ],
    },

    {
      label: t("nav.account"),
      href: "#account",
      icon: <User className="w-4 h-4" />,
      collapsedByDefault: true,
      children: [
        { label: t("nav.dashboard"), href: "/workspace", icon: <LayoutDashboard className="w-4 h-4" /> },
        { label: t("nav.myProfile"), href: "/workspace/my-profile", icon: <User className="w-4 h-4" /> },
        { label: t("nav.apiKeys"), href: "/workspace/api-keys", icon: <Key className="w-4 h-4" /> },
        { label: t("nav.settings"), href: "/workspace/settings", icon: <Settings className="w-4 h-4" /> },
      ],
    },

    ...(hasWorkspace
      ? [
          {
            label: t("nav.team"),
            href: "#team",
            icon: <Building2 className="w-4 h-4" />,
            collapsedByDefault: true,
            children: [
              { label: t("nav.organization"), href: "/workspace/profile", icon: <Building2 className="w-4 h-4" /> },
              { label: t("nav.whatIPublish"), href: "/workspace/models", icon: <Package className="w-4 h-4" /> },
              { label: t("nav.workspaces"), href: "/workspace/workspaces", icon: <Building2 className="w-4 h-4" /> },
              { label: t("nav.teamMembers"), href: "/workspace/team", icon: <Users className="w-4 h-4" /> },
              ...(isWorkspaceAdmin
                ? [
                    { label: t("nav.auditLog"), href: "/workspace/audit", icon: <ScrollText className="w-4 h-4" /> },
                  ]
                : []),
            ],
          },
        ]
      : []),

    ...(isPlatformAdmin
      ? [
          {
            label: t("nav.adminPanel"),
            href: "#admin",
            icon: <Wrench className="w-4 h-4" />,
            collapsedByDefault: true,
            children: [
              { label: t("nav.dashboard"), href: "/admin", icon: <LayoutDashboard className="w-4 h-4" /> },
              { label: t("nav.platformAnalytics"), href: "/admin/platform", icon: <BarChart2 className="w-4 h-4" /> },
              { label: t("nav.organizations"), href: "/admin/organizations", icon: <Building2 className="w-4 h-4" /> },
              { label: t("nav.users"), href: "/admin/users", icon: <Users className="w-4 h-4" /> },
              { label: t("nav.models"), href: "/admin/models", icon: <Package className="w-4 h-4" /> },
              { label: t("nav.apiKeys"), href: "/admin/api-keys", icon: <Key className="w-4 h-4" /> },
              { label: t("nav.executions"), href: "/admin/executions", icon: <Activity className="w-4 h-4" /> },
              { label: t("nav.reviews"), href: "/admin/reviews", icon: <Flag className="w-4 h-4" /> },
              { label: t("nav.marketplaceAnalytics"), href: "/admin/marketplace/analytics", icon: <TrendingUp className="w-4 h-4" /> },
              { label: t("nav.verification"), href: "/admin/marketplace/verification", icon: <ShieldCheck className="w-4 h-4" /> },
              { label: t("nav.settings"), href: "/admin/settings", icon: <Settings className="w-4 h-4" /> },
            ],
          },
        ]
      : []),
  ];
}
