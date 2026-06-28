"use client";

import { ReactFlowProvider } from "@xyflow/react";
import { usePathname } from "@/i18n/navigation";
import { Sidebar } from "@/components/layout/sidebar";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { useNavItems } from "@/components/layout/nav-items";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";

/**
 * Studio shell — the "Model, Analyze & Solve" hub.
 *
 * List pages (`/studio`, `/studio/new`) render with the app sidebar.
 * Workspace pages (`/studio/<id>/...`) are full-screen (no sidebar) and wrapped
 * in a ReactFlowProvider so the Build/Canvas lens can mount.
 *
 * P0: additive + dark — reachable by URL only (not yet wired into the nav).
 */
export default function StudioLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const navItems = useNavItems();

  const isWorkspacePage =
    pathname.startsWith("/studio/") && pathname !== "/studio/new";

  if (isWorkspacePage) {
    return (
      <ProtectedRoute>
        <ReactFlowProvider>
          <main
            id="main-content"
            className="h-screen flex flex-col overflow-hidden"
          >
            {children}
          </main>
        </ReactFlowProvider>
      </ProtectedRoute>
    );
  }

  return (
    <ProtectedRoute>
      <div className="flex min-h-screen bg-background">
        <Sidebar items={navItems} title="JAOT" />
        <main id="main-content" className="flex-1 p-8">
          <div className="max-w-[96rem] mx-auto w-full">
            <Breadcrumbs />
            {children}
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}
