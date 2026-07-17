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
 * List pages (`/studio`, `/studio/new`, `/studio/templates`) render with the app
 * sidebar and normal page scroll. Workspace pages (`/studio/<modelId>/...`) are
 * full-screen (no sidebar, `overflow-hidden`) and wrapped in a ReactFlowProvider
 * so the Build/Canvas lens can mount.
 */
export default function StudioLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const navItems = useNavItems();

  // Only `/studio/<modelId>/...` is the workspace; every static segment under
  // /studio/ is a list page. Matching the segment (not the full path) keeps
  // sub-routes like /studio/templates/... out of the clipped full-screen shell
  // (the gallery rendered scroll-less inside it — live bug 2026-07-04).
  const segment = pathname.split("/")[2] ?? "";
  const isWorkspacePage =
    pathname.startsWith("/studio/") && segment !== "new" && segment !== "templates";

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
