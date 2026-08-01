"use client";

import { Sidebar } from "@/components/layout/sidebar";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { useNavItems } from "@/components/layout/nav-items";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";

export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const navItems = useNavItems();

  return (
    <ProtectedRoute>
      <div className="flex min-h-screen bg-background">
        <Sidebar
          items={navItems}
          title="JAOT"
        />
        {/* min-w-0: a flex child refuses to shrink below its content without it,
            so a wide table pushed this column past the viewport instead of
            scrolling inside its own container (the Table primitive already has
            overflow-x-auto — it just never got the chance to apply). */}
        <main id="main-content" className="min-w-0 flex-1 p-8">
          <div className="max-w-[96rem] mx-auto w-full">
            <Breadcrumbs />
            {children}
          </div>
        </main>
      </div>
    </ProtectedRoute>
  );
}
