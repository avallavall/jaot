"use client";

import { ReactFlowProvider } from "@xyflow/react";
import { usePathname } from "@/i18n/navigation";
import { Sidebar } from "@/components/layout/sidebar";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { useNavItems } from "@/components/layout/nav-items";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";

export default function BuilderLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const navItems = useNavItems();

  // Canvas pages (/builder/[documentId]) are full-screen, no sidebar
  const isCanvasPage = pathname !== "/builder" && pathname !== "/builder/templates" && !pathname.startsWith("/builder/templates/");

  if (isCanvasPage) {
    return (
      <ProtectedRoute>
        <ReactFlowProvider>
          <main id="main-content" className="h-screen flex flex-col overflow-hidden">{children}</main>
        </ReactFlowProvider>
      </ProtectedRoute>
    );
  }

  return (
    <ProtectedRoute>
      <ReactFlowProvider>
        <div className="flex min-h-screen bg-background">
          <Sidebar items={navItems} title="JAOT" />
          <main id="main-content" className="flex-1 p-8">
            <div className="max-w-[96rem] mx-auto w-full">
              <Breadcrumbs />
              {children}
            </div>
          </main>
        </div>
      </ReactFlowProvider>
    </ProtectedRoute>
  );
}
