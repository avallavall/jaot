"use client";

import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ReactNode, useState, useEffect } from "react";
import { ChevronDown, ChevronRight, ExternalLink, Menu, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { useAuth } from "@/contexts/AuthContext";
import { useGuidance } from "@/contexts/GuidanceContext";
import { fetchCommunityStatus, type CommunityStatus } from "@/lib/community";
import { HelpMenu } from "@/components/layout/HelpMenu";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { UsageIndicator } from "@/components/tier/UsageIndicator";

interface NavItem {
  label: string;
  href: string;
  icon: ReactNode;
  children?: NavItem[];
  external?: boolean;
  onClick?: () => void;
  /** When true, the collapsible group starts collapsed unless the active path is inside it */
  collapsedByDefault?: boolean;
}

interface SidebarProps {
  items: NavItem[];
  title: string;
  subtitle?: string;
}

export function Sidebar({ items, title, subtitle }: SidebarProps) {
  const pathname = usePathname();
  const { logout } = useAuth();
  const { restartWizard } = useGuidance();
  const t = useTranslations("common");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expandedSections, setExpandedSections] = useState<string[]>(() => {
    // Auto-expand section if current path is inside it.
    // Sections with collapsedByDefault only expand when the active path matches a child.
    // Sections without collapsedByDefault expand by default (preserving existing behavior).
    const expanded: string[] = [];
    items.forEach(item => {
      if (item.children) {
        const isChildActive = item.children.some(child =>
          pathname === child.href || pathname.startsWith(child.href + "/")
        );
        if (item.collapsedByDefault) {
          // Only expand if user is currently on a child page
          if (isChildActive) {
            expanded.push(item.label);
          }
        } else {
          // Legacy behavior: expand if active (Community, Admin Panel)
          if (isChildActive) {
            expanded.push(item.label);
          }
        }
      }
    });
    return expanded;
  });

  const [communityStatus, setCommunityStatus] = useState<CommunityStatus | null>(null);

  useEffect(() => {
    fetchCommunityStatus().then(setCommunityStatus);
  }, []);

  // Filter community items based on backend status (match by href for locale-safe filtering)
  const processedItems = items.map(item => {
    if (item.href === "#community" && item.children) {
      const children = item.children
        .map(child => {
          if (child.href === "#discourse") {
            if (!communityStatus?.discourse_enabled) return null;
            return { ...child, href: `${communityStatus.discourse_url}/session/sso` };
          }
          return child;
        })
        .filter((c): c is NavItem => c !== null);
      if (children.length === 0) return null;
      return { ...item, children };
    }
    return item;
  }).filter((i): i is NavItem => i !== null);

  const handleLogout = () => {
    logout();
  };

  const toggleSection = (label: string) => {
    setExpandedSections(prev =>
      prev.includes(label)
        ? prev.filter(l => l !== label)
        : [...prev, label]
    );
  };

  const handleNavKeyDown = (e: React.KeyboardEvent) => {
    const items = Array.from(
      e.currentTarget.querySelectorAll('a[href], button:not([disabled])')
    ) as HTMLElement[];
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = (currentIndex + 1) % items.length;
      items[next]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const prev = (currentIndex - 1 + items.length) % items.length;
      items[prev]?.focus();
    }
  };

  const isExactMatch = (href: string) => pathname === href;

  const isActiveSection = (item: NavItem) => {
    if (item.children) {
      return item.children.some(child =>
        pathname === child.href || pathname.startsWith(child.href + "/")
      );
    }
    return pathname === item.href;
  };

  const renderNavItem = (item: NavItem, index: number, isChild = false) => {
    // Separator item
    if (item.href === "#" && !item.children) {
      return (
        <div
          key={`sep-${index}`}
          className="pt-4 pb-2 px-3"
        >
          <span className="text-xs font-medium uppercase tracking-wider text-sidebar-foreground/70">
            {item.label !== "─────────" ? item.label : ""}
          </span>
        </div>
      );
    }

    // Item with children (collapsible section)
    if (item.children) {
      const isExpanded = expandedSections.includes(item.label);
      const hasActiveChild = isActiveSection(item);

      return (
        <div key={item.label} className="space-y-1">
          <button
            onClick={() => toggleSection(item.label)}
            aria-expanded={isExpanded}
            className={cn(
              "w-full flex items-center justify-between gap-3 px-3 py-2.5 text-sm min-h-[2.75rem] transition-colors rounded-md",
              hasActiveChild
                ? "text-sidebar-accent-foreground font-medium"
                : "text-sidebar-foreground hover:bg-sidebar-accent/50"
            )}
          >
            <div className="flex items-center gap-3">
              {item.icon && <span className="flex-shrink-0">{item.icon}</span>}
              {item.label}
            </div>
            {isExpanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </button>
          {isExpanded && (
            <div className="ml-4 pl-3 border-l border-sidebar-border space-y-1">
              {item.children.map((child, childIndex) => renderNavItem(child, childIndex, true))}
            </div>
          )}
        </div>
      );
    }

    // External link
    if (item.external || item.href.startsWith("http://") || item.href.startsWith("https://")) {
      return (
        <a
          key={item.href + item.label}
          href={item.onClick ? undefined : item.href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={item.onClick ? (e) => { e.preventDefault(); item.onClick!(); } : undefined}
          className={cn(
            "flex items-center gap-3 px-3 py-2.5 text-sm min-h-[2.75rem] transition-colors rounded-md",
            "text-sidebar-foreground hover:bg-sidebar-accent/50",
            isChild && "text-sm"
          )}
        >
          {item.icon && <span className="flex-shrink-0">{item.icon}</span>}
          {item.label}
          <ExternalLink className="w-3 h-3 ml-auto text-sidebar-foreground/40" />
        </a>
      );
    }

    // Regular nav item
    const isActive = isExactMatch(item.href);

    return (
      <Link
        key={item.href}
        href={item.href}
        className={cn(
          "flex items-center gap-3 px-3 py-2.5 text-sm min-h-[2.75rem] transition-colors rounded-md",
          isActive
            ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
            : "text-sidebar-foreground hover:bg-sidebar-accent/50",
          isChild && "text-sm"
        )}
      >
        {item.icon && <span className="flex-shrink-0">{item.icon}</span>}
        {item.label}
      </Link>
    );
  };

  const sidebarContent = (
    <>
      <div className="p-6">
        <div className="flex items-center justify-between">
          <span className="text-2xl font-serif text-sidebar-primary">{title}</span>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden text-sidebar-foreground"
              onClick={() => setMobileOpen(false)}
              aria-label={t("sidebar.closeMenu")}
            >
              <X className="w-5 h-5" />
            </Button>
          </div>
        </div>
        {subtitle && (
          <p className="text-sm text-sidebar-foreground/75 mt-1">{subtitle}</p>
        )}
      </div>

      <Separator className="bg-sidebar-border" />

      <nav aria-label="Main navigation" onKeyDown={handleNavKeyDown} className="flex-1 p-4 space-y-1 overflow-y-auto">
        {processedItems.map((item, index) => renderNavItem(item, index))}
      </nav>

      <Separator className="bg-sidebar-border" />

      {/* Footer — flex-shrink-0 prevents compression at small viewports */}
      <div className="flex-shrink-0">
        <div className="p-4 space-y-1">
          <div className="flex items-center justify-between flex-wrap gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="justify-start text-sidebar-foreground/70 hover:text-sidebar-foreground"
              title={t("sidebar.restartWizard")}
              onClick={async () => {
                await restartWizard();
                toast(t("sidebar.wizardRestarted"));
              }}
            >
              <RotateCcw className="w-4 h-4 mr-2 shrink-0" />
              <span className="whitespace-nowrap">{t("sidebar.restartWizard")}</span>
            </Button>
            <div className="flex items-center gap-1 shrink-0">
              <LanguageSwitcher />
              <HelpMenu />
              <ThemeToggle />
            </div>
          </div>
          <Button
            variant="ghost"
            className="justify-start text-sidebar-foreground/70 hover:text-sidebar-foreground w-full"
            onClick={handleLogout}
          >
            <span className="mr-2">🚪</span>
            {t("sidebar.logout")}
          </Button>
        </div>
        <UsageIndicator />
        <div className="px-4 pb-3 flex items-center justify-center gap-3 text-xs text-sidebar-foreground/70">
          <Link href="/terms" className="hover:text-sidebar-foreground hover:underline">{t("sidebar.terms")}</Link>
          <span>·</span>
          <Link href="/privacy" className="hover:text-sidebar-foreground hover:underline">{t("sidebar.privacy")}</Link>
          <span>·</span>
          <button
            onClick={() => window.dispatchEvent(new CustomEvent("jaot:show-cookie-consent"))}
            className="hover:text-sidebar-foreground hover:underline"
          >
            {t("sidebar.cookieSettings")}
          </button>
        </div>
      </div>
    </>
  );

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="fixed top-4 left-4 z-50 md:hidden bg-background border shadow-sm"
        onClick={() => setMobileOpen(true)}
        aria-label={t("sidebar.openMenu")}
      >
        <Menu className="w-5 h-5" />
      </Button>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-64 bg-sidebar border-r border-sidebar-border flex flex-col transition-transform duration-200 md:sticky md:top-0 md:translate-x-0 md:h-screen",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        {sidebarContent}
      </aside>
    </>
  );
}
