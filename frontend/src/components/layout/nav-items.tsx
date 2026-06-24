"use client";

import {
  Zap,
  Store,
  ClipboardList,
  LayoutDashboard,
  Wrench,
  ShoppingBag,
  Key,
  Settings,
  User,
  Building2,
  CreditCard,
  Heart,
  Blocks,
  BarChart2,
  Webhook,
  Users,
  ScrollText,
  Sparkles,
  MessageSquare,
  Bug,
  LayoutTemplate,
  Activity,
  Package,
  Flag,
  Coins,
  ShieldCheck,
  TrendingUp,
  Megaphone,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import { FEEDBACK_URL } from "@/lib/community";

export function useNavItems() {
  const { activeWorkspaceId } = useAuth();
  const isAdmin = usePermission("admin");
  const hasWorkspace = !!activeWorkspaceId;
  const t = useTranslations("common");

  return [

    { label: t("nav.build"), href: "#", icon: null },
    { label: t("nav.myModels"), href: "/solve", icon: <Zap className="w-4 h-4" /> },
    { label: t("nav.visualBuilder"), href: "/builder", icon: <Blocks className="w-4 h-4" /> },
    { label: t("nav.templates"), href: "/builder/templates", icon: <LayoutTemplate className="w-4 h-4" /> },
    { label: t("nav.aiAssistant"), href: "/builder/ai-assistant", icon: <Sparkles className="w-4 h-4" /> },

    { label: t("nav.discover"), href: "#", icon: null },
    { label: t("nav.marketplace"), href: "/marketplace", icon: <ShoppingBag className="w-4 h-4" /> },
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
        { label: t("nav.credits"), href: "/workspace/credits", icon: <CreditCard className="w-4 h-4" /> },
        { label: t("nav.usage"), href: "/workspace/usage", icon: <BarChart2 className="w-4 h-4" /> },
        { label: t("nav.forSellers"), href: "/for-sellers", icon: <Store className="w-4 h-4" /> },
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
              { label: t("nav.workspaces"), href: "/workspace/workspaces", icon: <Building2 className="w-4 h-4" /> },
              { label: t("nav.teamMembers"), href: "/workspace/team", icon: <Users className="w-4 h-4" /> },
              ...(isAdmin
                ? [
                    { label: t("nav.auditLog"), href: "/workspace/audit", icon: <ScrollText className="w-4 h-4" /> },
                  ]
                : []),
            ],
          },
        ]
      : []),

    ...(isAdmin
      ? [
          {
            label: t("nav.adminPanel"),
            href: "#admin",
            icon: <Wrench className="w-4 h-4" />,
            collapsedByDefault: true,
            children: [
              { label: t("nav.dashboard"), href: "/admin", icon: <LayoutDashboard className="w-4 h-4" /> },
              { label: t("nav.organizations"), href: "/admin/organizations", icon: <Building2 className="w-4 h-4" /> },
              { label: t("nav.users"), href: "/admin/users", icon: <Users className="w-4 h-4" /> },
              { label: t("nav.models"), href: "/admin/models", icon: <Package className="w-4 h-4" /> },
              { label: t("nav.apiKeys"), href: "/admin/api-keys", icon: <Key className="w-4 h-4" /> },
              { label: t("nav.executions"), href: "/admin/executions", icon: <Activity className="w-4 h-4" /> },
              { label: t("nav.reviews"), href: "/admin/reviews", icon: <Flag className="w-4 h-4" /> },
              { label: t("nav.credits"), href: "/admin/credits", icon: <Coins className="w-4 h-4" /> },
              { label: t("nav.marketplaceAnalytics"), href: "/admin/marketplace/analytics", icon: <TrendingUp className="w-4 h-4" /> },
              { label: t("nav.promotions"), href: "/admin/marketplace/promotions", icon: <Megaphone className="w-4 h-4" /> },
              { label: t("nav.sellerAnalytics"), href: "/admin/marketplace/seller-analytics", icon: <BarChart2 className="w-4 h-4" /> },
              { label: t("nav.verification"), href: "/admin/marketplace/verification", icon: <ShieldCheck className="w-4 h-4" /> },
              { label: t("nav.settings"), href: "/admin/settings", icon: <Settings className="w-4 h-4" /> },
            ],
          },
        ]
      : []),
  ];
}
