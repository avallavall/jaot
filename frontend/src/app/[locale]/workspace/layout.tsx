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
